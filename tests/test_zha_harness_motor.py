"""Tests for the simulated motor and the virtual clock (issue #5, phase 2)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
import time

import pytest
import zha.quirks
import zhaquirks
import zigpy.exceptions
import zigpy.types as t
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

from tests.zha_harness import (
    SHADE_IEEE,
    SHADE_NWK,
    HarnessApp,
    MotorSim,
    VirtualClock,
    decode_frame,
    seed_database,
)

LIFT = WindowCovering.AttributeDefs.current_position_lift_percentage


@pytest.fixture
async def clock() -> AsyncIterator[VirtualClock]:
    """Install a virtual clock on the test's event loop."""
    virtual = VirtualClock(asyncio.get_running_loop())
    virtual.install()
    yield virtual
    virtual.uninstall()


@pytest.fixture
async def shade(tmp_path: Path) -> AsyncIterator[tuple[HarnessApp, MotorSim]]:
    """Open a zigpy app over a seeded database, with the motor answering for the shade."""
    db = tmp_path / "zigbee.db"
    await seed_database(db, initial_lift=40)
    zhaquirks.setup()
    app = await HarnessApp.new(
        HarnessApp.config_for(db),
        start_radio=False,
        device_resolver=zha.quirks.DEVICE_REGISTRY.resolve,
    )
    motor = MotorSim(
        position=40, rate_pct_per_s=5.0, reply_latency=1.0, commands_reversed=False
    )
    app.motor = motor
    yield app, motor
    await app.shutdown()


def _covering(app: HarnessApp) -> WindowCovering:
    return app.get_device(SHADE_IEEE).endpoints[1].window_covering


async def test_read_returns_the_motor_position(clock, shade) -> None:
    """A live read of the lift answers with the motor's position."""
    app, _ = shade
    result, _ = await clock.run(
        _covering(app).read_attributes([LIFT.id], allow_cache=False)
    )

    assert result[0][LIFT.id] == 40


async def test_motor_moves_at_its_rate_and_stops_at_the_end_of_travel(
    clock, shade
) -> None:
    """down_close (raw 0x01) runs toward 100 at the set rate and stops there."""
    app, motor = shade
    covering = _covering(app)
    # The stock quirk swaps the ids, so up_open() is what puts 0x01 on the wire.
    await clock.run(covering.up_open())

    await clock.advance(4)
    travelled = 5 * (clock.time() - motor.moving_since)
    assert motor.position_at(clock.time()) == pytest.approx(40 + travelled, abs=0.01)
    await clock.advance(60)
    assert motor.position_at(clock.time()) == 100


async def test_dropped_frame_is_retried_by_zigpy_in_virtual_time(clock, shade) -> None:
    """The first frame is dropped; zigpy's own retry lands it after its 28 s timeout."""
    app, motor = shade
    motor.drop_next(1)
    real_start = time.monotonic()

    result, elapsed = await clock.run(
        _covering(app).read_attributes([LIFT.id], allow_cache=False)
    )

    assert result[0][LIFT.id] == 40
    assert elapsed >= 28
    assert time.monotonic() - real_start < 5
    first, second = app.frames
    assert (first.dropped, second.dropped) == (True, False)
    assert first.tsn == second.tsn


async def test_stop_is_rejected(clock, shade) -> None:
    """Stop is answered with UNSUP_CLUSTER_COMMAND, as the real firmware does."""
    app, _ = shade
    result, _ = await clock.run(_covering(app).stop())

    assert result.status == foundation.Status.UNSUP_CLUSTER_COMMAND


async def test_sleep_and_motion_share_one_clock(clock, shade) -> None:
    """asyncio.sleep in any coroutine advances the same clock the motor moves on."""
    app, motor = shade
    await clock.run(_covering(app).up_open())
    before = motor.position_at(clock.time())

    await clock.run(asyncio.sleep(10))

    assert motor.position_at(clock.time()) == pytest.approx(before + 50, abs=1)


async def test_run_enforces_its_virtual_limit(clock) -> None:
    """A run that would pass its limit in one jump still times out at the limit."""
    with pytest.raises(TimeoutError):
        await clock.run(asyncio.sleep(100), limit=1)


async def test_executor_work_holds_virtual_time(clock) -> None:
    """Time does not jump past a timeout while an executor job is still running."""

    async def work() -> None:
        async with asyncio.timeout(1):
            await asyncio.get_running_loop().run_in_executor(None, time.sleep, 0.05)

    await clock.run(work())


async def test_motor_can_model_reversed_run_to_limit_commands(clock, shade) -> None:
    """With reversed commands, raw down_close (0x01) raises the shade instead."""
    app, motor = shade
    motor.commands_reversed = True
    # The stock quirk's swap: up_open() puts 0x01 on the wire.
    await clock.run(_covering(app).up_open())

    await clock.advance(60)

    assert motor.position_at(clock.time()) == 0


async def test_run_limit_counts_real_time_spent_waiting(clock) -> None:
    """Work that finishes only after the limit (here, on a thread) still times out."""
    with pytest.raises(TimeoutError):
        await clock.run(
            asyncio.get_running_loop().run_in_executor(None, time.sleep, 0.05),
            limit=0.01,
        )


def test_unknown_covering_command_is_answered_as_unsupported() -> None:
    """A command id zigpy has no schema for still gets the motor's UNSUP reply."""
    header = foundation.ZCLHeader.cluster(tsn=9, command_id=0xFE)
    frame = decode_frame(
        t.ZigbeePacket(
            src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0)),
            src_ep=1,
            dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=SHADE_NWK),
            dst_ep=1,
            tsn=9,
            profile_id=0x0104,
            cluster_id=WindowCovering.cluster_id,
            data=t.SerializableBytes(header.serialize()),
        )
    )
    motor = MotorSim(position=40, commands_reversed=False)

    reply = motor.handle(frame, now=0.0)

    assert (frame.tsn, frame.command_id) == (9, 0xFE)
    assert reply is not None
    rsp_header, body = foundation.ZCLHeader.deserialize(reply)
    status = foundation.DefaultResponse.deserialize(body)[0].status
    assert (rsp_header.tsn, status) == (9, foundation.Status.UNSUP_CLUSTER_COMMAND)


async def test_unrelated_executor_work_does_not_hold_advance(clock) -> None:
    """An executor job the test did not start does not stretch an advance."""
    loop = asyncio.get_running_loop()
    background = loop.run_in_executor(None, time.sleep, 0.2)
    start = clock.time()

    await clock.advance(0.01)

    assert clock.time() - start == pytest.approx(0.01, abs=0.05)
    await background


def test_malformed_payload_for_a_known_command_is_not_acted_on() -> None:
    """A truncated go_to_lift_percentage keeps only its addressing; the motor ignores it."""
    header = foundation.ZCLHeader.cluster(
        tsn=9, command_id=WindowCovering.ServerCommandDefs.go_to_lift_percentage.id
    )
    frame = decode_frame(
        t.ZigbeePacket(
            src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0)),
            src_ep=1,
            dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=SHADE_NWK),
            dst_ep=1,
            tsn=9,
            profile_id=0x0104,
            cluster_id=WindowCovering.cluster_id,
            data=t.SerializableBytes(header.serialize()),  # the lift byte is missing
        )
    )

    assert frame.tsn is None
    assert MotorSim(position=40, commands_reversed=False).handle(frame, now=0.0) is None


async def test_scripted_lift_reads_answer_in_order_then_the_truth(clock, shade) -> None:
    """Scripted reads report 255, then a failure status, then nothing; then the position."""
    app, motor = shade
    motor.script_lift_reads(255, foundation.Status.UNSUPPORTED_ATTRIBUTE, None)
    covering = _covering(app)

    async def read() -> tuple[dict, dict]:
        async with asyncio.timeout(5):
            return await covering.read_attributes(
                [LIFT.id], allow_cache=False, retries=0
            )

    assert (await clock.run(read()))[0] == ({LIFT.id: 255}, {})
    assert (await clock.run(read()))[0] == (
        {},
        {LIFT.id: foundation.Status.UNSUPPORTED_ATTRIBUTE},
    )
    with pytest.raises(TimeoutError):
        await clock.run(read())
    assert (await clock.run(read()))[0] == ({LIFT.id: 40}, {})


@pytest.mark.parametrize("delivered", [True, False])
async def test_failed_send_raises_and_lands_only_if_delivered(
    clock, shade, delivered
) -> None:
    """The radio raises DeliveryError; a delivered frame still moves the motor."""
    app, motor = shade
    motor.fail_next_sends(1, delivered=delivered)

    with pytest.raises(zigpy.exceptions.DeliveryError):
        await clock.run(_covering(app).go_to_lift_percentage(80, retries=0))
    await clock.advance(20)

    [frame] = app.frames
    assert frame.dropped is not delivered
    assert motor.position_at(clock.time()) == (80 if delivered else 40)


async def test_stuck_motor_acknowledges_and_does_not_move(clock, shade) -> None:
    """With ignore_commands, a movement command is answered SUCCESS and nothing moves."""
    app, motor = shade
    motor.ignore_commands = True

    result, _ = await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(20)

    assert result.status == foundation.Status.SUCCESS
    assert motor.position_at(clock.time()) == 40


async def test_late_start_holds_position_until_the_delay(clock, shade) -> None:
    """With start_delay, travel begins that long after the command."""
    app, motor = shade
    motor.start_delay = 10

    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(8)
    assert motor.position_at(clock.time()) == 40
    await clock.advance(4)
    assert motor.position_at(clock.time()) > 40


async def test_start_moving_sets_the_shade_travelling(clock, shade) -> None:
    """start_moving models a shade already travelling, e.g. after its remote."""
    _, motor = shade
    motor.start_moving(0, clock.time())

    await clock.advance(2)

    assert motor.position_at(clock.time()) == pytest.approx(30, abs=0.1)


async def test_each_shade_is_answered_by_its_own_motor(tmp_path, clock) -> None:
    """Two seeded shades, two motors: each read reaches the right one."""
    other_ieee = t.EUI64.convert("60:83:da:ff:fe:a0:00:03")
    other_nwk = t.NWK(0x5A20)
    db = tmp_path / "zigbee.db"
    await seed_database(db, initial_lift=40)
    await seed_database(db, initial_lift=40, ieee=other_ieee, nwk=other_nwk)
    app = await HarnessApp.new(HarnessApp.config_for(db), start_radio=False)
    try:
        app.motor = MotorSim(position=10, commands_reversed=False)
        app.motors[other_nwk] = MotorSim(position=90, commands_reversed=False)

        results = [
            (
                await clock.run(
                    app.get_device(ieee)
                    .endpoints[1]
                    .window_covering.read_attributes([LIFT.id], allow_cache=False)
                )
            )[0][0][LIFT.id]
            for ieee in (SHADE_IEEE, other_ieee)
        ]
    finally:
        await app.shutdown()

    assert results == [10, 90]
    assert [f.dst_nwk for f in app.frames if f.cluster_id == 0x0102] == [
        SHADE_NWK,
        other_nwk,
    ]


async def test_a_stall_stops_travel_short_of_the_target(clock, shade) -> None:
    """With stall_at, travel through that lift stops there (Part 1 §3b)."""
    app, motor = shade
    motor.stall_at = 55

    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(30)

    assert motor.position_at(clock.time()) == 55
    assert motor.target == 80


async def test_a_stall_outside_the_travel_does_not_stop_it(clock, shade) -> None:
    """A stall lift the travel never crosses leaves the move alone."""
    app, motor = shade
    motor.stall_at = 20

    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(30)

    assert motor.position_at(clock.time()) == 80


async def test_every_frame_records_when_it_was_sent(clock, shade) -> None:
    """Frames carry the loop time they left at, dropped ones included (read counts)."""
    app, motor = shade
    motor.drop_next(1)
    start = clock.time()

    await clock.run(
        _covering(app).read_attributes([LIFT.id], allow_cache=False, retries=2)
    )
    await clock.advance(7)
    third = clock.time() - start
    await clock.run(_covering(app).read_attributes([LIFT.id], allow_cache=False))

    reads = [f for f in app.frames if f.cluster_id == 0x0102]
    assert [f.dropped for f in reads] == [True, False, False]
    sent = [f.sent_at - start for f in reads]
    assert sent[0] == pytest.approx(0, abs=0.1)
    assert sent[1] > sent[0]
    assert sent[2] == pytest.approx(third, abs=0.1)


# --- The firmware's double reply (firmware analysis §3; #45) ------------------------

COMMANDS = WindowCovering.ServerCommandDefs
# Every Window Covering command the radio has a handler for, with a valid payload.
HANDLED_COMMANDS = [
    (COMMANDS.up_open.id, ()),
    (COMMANDS.down_close.id, ()),
    (COMMANDS.stop.id, ()),
    (COMMANDS.go_to_lift_value.id, (1000,)),
    (COMMANDS.go_to_lift_percentage.id, (30,)),
    (COMMANDS.go_to_tilt_value.id, (1000,)),
    (COMMANDS.go_to_tilt_percentage.id, (30,)),
]
ORDERS = {
    "success-first": [
        foundation.Status.SUCCESS,
        foundation.Status.UNSUP_CLUSTER_COMMAND,
    ],
    "unsup-first": [
        foundation.Status.UNSUP_CLUSTER_COMMAND,
        foundation.Status.SUCCESS,
    ],
}


def _command_frame(command_id: int, *args: object, tsn: int = 9):
    """Decode a Window Covering command frame as the coordinator sends it."""
    header = foundation.ZCLHeader.cluster(tsn=tsn, command_id=command_id)
    payload = header.serialize()
    if command_id in WindowCovering.server_commands:
        payload += WindowCovering.server_commands[command_id].schema(*args).serialize()
    return decode_frame(
        t.ZigbeePacket(
            src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0)),
            src_ep=1,
            dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=SHADE_NWK),
            dst_ep=1,
            tsn=tsn,
            profile_id=0x0104,
            cluster_id=WindowCovering.cluster_id,
            data=t.SerializableBytes(payload),
        )
    )


@pytest.mark.parametrize(
    ("command_id", "args", "end"),
    [
        (WindowCovering.ServerCommandDefs.down_close.id, (), 100),
        (WindowCovering.ServerCommandDefs.go_to_lift_percentage.id, (100,), 100),
        (WindowCovering.ServerCommandDefs.up_open.id, (), 0),
        (WindowCovering.ServerCommandDefs.go_to_lift_percentage.id, (0,), 0),
    ],
    ids=["down-close", "go-to-100", "up-open", "go-to-0"],
)
def test_the_remote_set_limits_are_the_ends_of_lift(command_id, args, end) -> None:
    """Lift 0 and 100 are the limits set with the remote, and travel stops there (#54).

    The motor scales Zigbee positions between those limits and enforces them: go-to
    100 and raw down_close both stop at the lower limit, which it reports as 100.
    """
    motor = MotorSim(position=40, rate_pct_per_s=5.0, reports=True)

    motor.handle(_command_frame(command_id, *args), now=0.0)

    assert motor.ends_at() == pytest.approx(abs(end - 40) / 5.0)
    assert motor.position_at(1000.0) == end
    assert motor.cached_at(1000.0) == end
    assert motor.next_report_at(0.0) == motor.ends_at()


def _default_responses(replies: list[bytes]) -> list[tuple[int, int, object]]:
    """Return (TSN, command id, status) of each Default Response payload."""
    decoded = []
    for reply in replies:
        header, body = foundation.ZCLHeader.deserialize(reply)
        assert header.command_id == foundation.GeneralCommand.Default_Response
        response = foundation.DefaultResponse.deserialize(body)[0]
        decoded.append((header.tsn, response.command_id, response.status))
    return decoded


@pytest.mark.parametrize("order", list(ORDERS))
@pytest.mark.parametrize(
    ("command_id", "args"),
    HANDLED_COMMANDS,
    ids=[f"0x{command_id:02X}" for command_id, _ in HANDLED_COMMANDS],
)
def test_the_double_reply_answers_every_handled_command_twice(
    order, command_id, args
) -> None:
    """With double_reply, a handled command draws SUCCESS and 0x81, same TSN (FA §3)."""
    motor = MotorSim(position=40, commands_reversed=False, double_reply=order)

    replies = motor.replies(_command_frame(command_id, *args), now=0.0)

    assert _default_responses(replies) == [
        (9, command_id, status) for status in ORDERS[order]
    ]


@pytest.mark.parametrize(
    ("command_id", "args"),
    HANDLED_COMMANDS,
    ids=[f"0x{command_id:02X}" for command_id, _ in HANDLED_COMMANDS],
)
def test_unsup_only_models_a_lost_success(command_id, args) -> None:
    """The unsup-only mode sends the 0x81 alone, as when the SUCCESS is lost (FA §3)."""
    motor = MotorSim(position=40, commands_reversed=False, double_reply="unsup-only")

    replies = motor.replies(_command_frame(command_id, *args), now=0.0)

    assert _default_responses(replies) == [
        (9, command_id, foundation.Status.UNSUP_CLUSTER_COMMAND)
    ]


def test_without_double_reply_each_command_draws_one_reply() -> None:
    """By default the motor answers once, as the measurements recorded it (Part 1 §3d)."""
    motor = MotorSim(position=40, commands_reversed=False)

    replies = motor.replies(_command_frame(COMMANDS.stop.id), now=0.0)

    assert _default_responses(replies) == [
        (9, COMMANDS.stop.id, foundation.Status.UNSUP_CLUSTER_COMMAND)
    ]


@pytest.mark.parametrize("order", list(ORDERS))
def test_a_command_without_a_handler_draws_only_the_refusal(order) -> None:
    """IDs 3, 6 and unknown ones get 0x81 alone, double reply or not (FA §3 table)."""
    motor = MotorSim(position=40, commands_reversed=False, double_reply=order)

    for command_id in (0x03, 0x06, 0xFE):
        replies = motor.replies(_command_frame(command_id), now=0.0)

        assert _default_responses(replies) == [
            (9, command_id, foundation.Status.UNSUP_CLUSTER_COMMAND)
        ]


@pytest.mark.parametrize("order", list(ORDERS))
async def test_zigpy_keeps_whichever_reply_arrives_first(clock, shade, order) -> None:
    """Both replies reach zigpy; its TSN match returns the first (session A, FA §3)."""
    app, motor = shade
    motor.double_reply = order
    received = []
    packet_received = app.packet_received

    def spy(packet: t.ZigbeePacket) -> None:
        received.append(packet)
        packet_received(packet)

    app.packet_received = spy

    result, _ = await clock.run(_covering(app).stop())
    await clock.advance(1)

    assert result.status is ORDERS[order][0]
    assert _default_responses([p.data.serialize() for p in received]) == [
        (app.frames[-1].tsn, COMMANDS.stop.id, status) for status in ORDERS[order]
    ]
    # Moving commands still move the motor once.
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(20)
    assert motor.position_at(clock.time()) == 80


@pytest.mark.parametrize("double_reply", [None, *ORDERS])
async def test_a_manufacturer_specific_command_is_refused_and_not_acted_on(
    clock, shade, double_reply
) -> None:
    """A manufacturer-specific Window Covering frame draws 0x81 alone, unacted on.

    The radio refuses it before looking at the command (FA §2, "Hidden extensions").
    """
    app, motor = shade
    motor.double_reply = double_reply

    result, _ = await clock.run(
        _covering(app).go_to_lift_percentage(80, manufacturer=0x1002)
    )
    await clock.advance(20)

    assert app.frames[-1].manufacturer == 0x1002
    assert result.status is foundation.Status.UNSUP_CLUSTER_COMMAND
    assert motor.position_at(clock.time()) == 40


# --- The radio's copy of the lift and its reports (#51) -------------------------------


def _lift_reports(app: HarnessApp) -> list[tuple[float, int]]:
    """Record every lift report the radio pushes, as (loop time, lift), from now on."""
    reports: list[tuple[float, int]] = []
    packet_received = app.packet_received

    def spy(packet: t.ZigbeePacket) -> None:
        hdr, rest = foundation.ZCLHeader.deserialize(packet.data.serialize())
        if hdr.command_id == foundation.GeneralCommand.Report_Attributes and (
            hdr.frame_control.frame_type == foundation.FrameType.GLOBAL_COMMAND
        ):
            body, _ = foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Report_Attributes
            ].schema.deserialize(rest)
            for attribute in body.attribute_reports:
                if attribute.attrid == LIFT.id:
                    reports.append(
                        (asyncio.get_running_loop().time(), attribute.value.value)
                    )
        packet_received(packet)

    app.packet_received = spy
    return reports


async def _read_lift(clock: VirtualClock, app: HarnessApp) -> int:
    result, _ = await clock.run(
        _covering(app).read_attributes([LIFT.id], allow_cache=False)
    )
    return result[0][LIFT.id]


async def test_reads_during_travel_return_the_lift_from_before_it(clock, shade) -> None:
    """The radio answers from its copy, which changes only when travel ends (#51)."""
    app, _ = shade
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(2)

    during = await _read_lift(clock, app)
    await clock.advance(10)
    after = await _read_lift(clock, app)

    assert (during, after) == (40, 80)


async def test_the_end_of_travel_is_pushed_as_a_report(clock, shade) -> None:
    """The motor sends its position on arrival; the radio reports it, unasked (#51)."""
    app, _ = shade
    reports = _lift_reports(app)
    start = clock.time()
    await clock.run(_covering(app).go_to_lift_percentage(80))

    await clock.advance(20)

    [(at, lift)] = reports
    # 8 s of travel, then the reply latency; the cache holds it without a read.
    assert (round(at - start, 1), lift) == (9.0, 80)
    assert _covering(app).get(LIFT.id) == 80
    assert [f for f in app.frames if f.general] == []


async def test_stop_halts_the_motor_and_reports_where(clock, shade) -> None:
    """Stop is refused with 0x81, yet the motor halts and reports its lift (#51)."""
    app, motor = shade
    reports = _lift_reports(app)
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(1)

    result, _ = await clock.run(_covering(app).stop())
    await clock.advance(20)

    halted = round(motor.position_at(clock.time()))
    assert result.status is foundation.Status.UNSUP_CLUSTER_COMMAND
    assert 40 < halted < 80
    assert [lift for _, lift in reports] == [halted]
    assert await _read_lift(clock, app) == halted


async def test_without_stop_halts_the_motor_runs_on(clock, shade) -> None:
    """``stop_halts=False`` keeps the motor travelling after a Stop."""
    app, motor = shade
    motor.stop_halts = False
    await clock.run(_covering(app).go_to_lift_percentage(80))

    await clock.run(_covering(app).stop())
    await clock.advance(20)

    assert motor.position_at(clock.time()) == 80


async def test_positions_sent_during_travel_update_the_copy(clock, shade) -> None:
    """``report_interval_s`` makes the motor send positions during travel, each reported."""
    app, motor = shade
    motor.report_interval_s = 2.0
    reports = _lift_reports(app)
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(4)

    during = await _read_lift(clock, app)
    await clock.advance(20)

    assert 40 < during < 80
    assert [lift for _, lift in reports] == [50, 60, 70, 80]


async def test_without_the_radio_copy_reads_answer_the_live_position(
    clock, shade
) -> None:
    """``radio_cache=False`` answers reads with the position at that moment."""
    app, motor = shade
    motor.radio_cache = False
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(2)

    during = await _read_lift(clock, app)

    assert 40 < during < 80


async def test_without_reports_nothing_is_pushed(clock, shade) -> None:
    """``reports=False``: the end of travel changes the copy but reaches no one."""
    app, motor = shade
    motor.reports = False
    reports = _lift_reports(app)
    await clock.run(_covering(app).go_to_lift_percentage(80))

    await clock.advance(20)

    assert reports == []
    assert await _read_lift(clock, app) == 80


async def test_an_ignored_frame_is_acknowledged_and_not_acted_on(clock, shade) -> None:
    """``ignore_next``: SUCCESS, no movement; the identical next frame is obeyed."""
    app, motor = shade
    motor.ignore_next(1)

    ignored, _ = await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(20)
    assert motor.position_at(clock.time()) == 40
    obeyed, _ = await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(20)

    assert ignored.status is obeyed.status is foundation.Status.SUCCESS
    assert motor.position_at(clock.time()) == 80


async def test_a_duplicate_go_to_moves_the_shade_once(clock, shade) -> None:
    """The same target twice, 2.5 s apart: one travel, one report at the target (#51)."""
    app, motor = shade
    reports = _lift_reports(app)
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(1.5)
    await clock.run(_covering(app).go_to_lift_percentage(80))

    await clock.advance(20)

    assert [lift for _, lift in reports] == [80]
    assert motor.position_at(clock.time()) == 80


async def test_a_shade_already_at_the_target_reports_nothing(clock, shade) -> None:
    """The radio pushes only a changed position: a go-to where the shade is, no report."""
    app, motor = shade
    reports = _lift_reports(app)

    await clock.run(_covering(app).go_to_lift_percentage(40))
    await clock.advance(20)

    assert reports == []
    assert motor.position_at(clock.time()) == 40


async def test_a_report_already_sent_survives_a_new_command(clock, shade) -> None:
    """A position the motor sent before a new command still reaches the hub, after it.

    The motor ends the go-to 80 at 8 s; its report is still on its way (``report_latency``
    3 s) when a go-to 20 is sent at 8.5 s, and arrives after that command.
    """
    app, motor = shade
    motor.report_latency = 3.0
    reports = _lift_reports(app)
    start = clock.time()
    await clock.run(_covering(app).go_to_lift_percentage(80))
    await clock.advance(start + 8.5 - clock.time())

    await clock.run(_covering(app).go_to_lift_percentage(20))
    await clock.advance(40)

    assert [lift for _, lift in reports] == [80, 20]
    assert reports[0][0] - start == pytest.approx(11, abs=0.01)
