"""Tests for the SmartWings WM25/L-Z quirk, through zigpy's real request path.

The motor starts at rest at lift 40, travels 5 points/s, and answers 1 s after a frame.
"""

import asyncio
import subprocess
import sys

import pytest
from zhaquirks import DoublingPowerConfigurationCluster
import zigpy.exceptions
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import PowerConfiguration

from tests.quirk.conftest import (
    INITIAL_LIFT,
    JITTER_S,
    LIFT,
    OTHER_IEEE,
    OTHER_NWK,
    QUIRK_FILE,
    READ,
    covering_of,
)
from tests.zha_harness import SHADE_IEEE, report_packet

COMMANDS = WindowCovering.ServerCommandDefs
SUCCESS = foundation.Status.SUCCESS
UNSUP = foundation.Status.UNSUP_CLUSTER_COMMAND
GO_80 = ("go_to_lift_percentage", 80)
STOP = ("stop",)
# The read for a 40-point move comes 40% of 70 s plus 3 s after the reply.
ARRIVAL_40_S = 31.0
SETTLED_S = 400.0


def status(result) -> foundation.Status:
    """Return the status of a Default Response, failing on anything else."""
    assert isinstance(result, foundation.DefaultResponse), result
    return result.status


def lift_now(shade) -> int:
    """Return where the motor is now."""
    return round(shade.motor.position_at(shade.clock.time()))


def send_times(shade) -> list[float]:
    """Return when each WindowCovering command frame left for the main shade."""
    return [
        frame.sent_at
        for frame in shade.app.frames
        if frame.cluster_id == WindowCovering.cluster_id and not frame.general
    ]


async def go_to(shade, lift: int) -> foundation.Status:
    """Send go_to_lift_percentage(lift); return the status the caller gets."""
    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(lift), within=15
    )
    return status(result)


def report(shade, lift: int) -> None:
    """Deliver a lift report from the main shade through zigpy's real report path."""
    shade.app.packet_received(report_packet(WindowCovering.cluster_id, LIFT.id, lift))


def test_the_quirk_imports_without_home_assistant() -> None:
    """Loading the quirk imports nothing from Home Assistant."""
    probe = (
        "import importlib.util, sys; "
        "spec = importlib.util.spec_from_file_location('wm25lz', sys.argv[1]); "
        "spec.loader.exec_module(importlib.util.module_from_spec(spec)); "
        "sys.exit(any(m.split('.')[0] == 'homeassistant' for m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(QUIRK_FILE)], capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_the_shade_resolves_to_the_quirk(shade) -> None:
    """ZHA's registry gives the WM25/L-Z the quirk's clusters."""
    endpoint = shade.app.get_device(SHADE_IEEE).endpoints[1]
    assert type(endpoint.window_covering) is shade.quirk.WM25LZWindowCovering
    assert isinstance(endpoint.power, DoublingPowerConfigurationCluster)


# --- What goes out, and what the caller gets ------------------------------------------


@pytest.mark.parametrize(
    ("name", "args", "frame", "lift"),
    [
        ("up_open", (), ("up_open",), 0),
        ("down_close", (), ("down_close",), 100),
        ("go_to_lift_percentage", (73,), ("go_to_lift_percentage", 73), 73),
    ],
)
async def test_movements_go_out_as_zha_sends_them(
    shade, name, args, frame, lift
) -> None:
    """Open is up_open, close down_close, a go-to unchanged; no swap, no read."""
    result, elapsed = await shade.outcome(
        getattr(shade.covering, name)(*args), within=15
    )

    assert status(result) == SUCCESS
    assert elapsed <= shade.motor.reply_latency + JITTER_S
    await shade.clock.advance(SETTLED_S)
    assert shade.wire() == [frame]
    assert lift_now(shade) == lift
    assert shade.covering.get(LIFT.id) == lift


async def test_the_battery_is_doubled(shade) -> None:
    """The radio's whole-percent battery byte is cached in ZCL's half percent."""
    battery = PowerConfiguration.AttributeDefs.battery_percentage_remaining
    shade.app.packet_received(
        report_packet(PowerConfiguration.cluster_id, battery.id, 42)
    )
    await shade.clock.advance(1)

    assert shade.app.get_device(SHADE_IEEE).endpoints[1].power.get(battery.id) == 84


@pytest.mark.parametrize("order", ["success-first", "unsup-first", "unsup-only"])
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("up_open", ()),
        ("down_close", ()),
        ("go_to_lift_percentage", (60,)),
        ("stop", ()),
    ],
)
async def test_the_radios_second_reply_is_success(shade, order, name, args) -> None:
    """Whichever of SUCCESS and 0x81 zigpy matches, the caller gets SUCCESS."""
    shade.motor.double_reply = order

    result, _ = await shade.outcome(getattr(shade.covering, name)(*args), within=15)
    await shade.clock.advance(1)

    assert status(result) == SUCCESS
    assert len(shade.commands()) == 1


async def test_a_manufacturer_specific_stop_is_sent_as_is(shade) -> None:
    """The radio refuses it, and the caller hears so."""
    result, _ = await shade.outcome(
        shade.covering.command(COMMANDS.stop.id, manufacturer=0x1002), within=15
    )

    assert status(result) == UNSUP
    assert shade.commands() == [STOP]


@pytest.mark.parametrize(
    ("command", "args", "manufacturer"),
    [
        (COMMANDS.go_to_lift_value, (1000,), None),
        (COMMANDS.go_to_tilt_value, (1000,), None),
        (COMMANDS.go_to_tilt_percentage, (30,), None),
        (COMMANDS.up_open, (), 0x1002),
        (COMMANDS.down_close, (), 0x1002),
        (COMMANDS.go_to_lift_percentage, (50,), 0x1002),
    ],
    ids=[
        "lift-value",
        "tilt-value",
        "tilt-percentage",
        "mfr-open",
        "mfr-close",
        "mfr-go-to",
    ],
)
async def test_commands_the_radio_mangles_are_refused_unsent(
    shade, command, args, manufacturer
) -> None:
    """The caller gets UNSUP_CLUSTER_COMMAND and nothing goes out."""
    result, elapsed = await shade.outcome(
        shade.covering.command(command.id, *args, manufacturer=manufacturer), within=1
    )
    await shade.clock.advance(SETTLED_S)

    assert status(result) == UNSUP
    assert result.command_id == command.id
    assert elapsed <= JITTER_S
    assert shade.wire() == []


# --- A lost frame ----------------------------------------------------------------------


async def test_an_unanswered_frame_is_sent_once_more_after_2_5_s(shade) -> None:
    """No reply within 5 s: the same frame again 2.5 s later, and SUCCESS."""
    shade.motor.drop_next(1)

    result, elapsed = await shade.outcome(shade.covering.down_close(), within=15)

    assert status(result) == SUCCESS
    assert shade.commands() == [("down_close",)] * 2
    first, second = send_times(shade)
    assert 7.5 <= second - first <= 7.5 + JITTER_S
    assert elapsed < 10


async def test_a_failed_send_is_sent_once_more_after_2_5_s(shade) -> None:
    """A DeliveryError: the same frame again 2.5 s later."""
    shade.motor.fail_next_sends(1, delivered=False)

    assert await go_to(shade, 80) == SUCCESS

    first, second = send_times(shade)
    assert 2.5 <= second - first <= 2.5 + JITTER_S
    assert shade.commands() == [GO_80] * 2


async def test_two_lost_frames_fail(shade) -> None:
    """Both frames lost: FAILURE for ZHA's own failure path, and no third frame."""
    shade.motor.drop_next(2)

    assert await go_to(shade, 80) == foundation.Status.FAILURE
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [GO_80] * 2
    assert lift_now(shade) == INITIAL_LIFT


async def test_lost_replies_fail_but_the_end_is_still_shown(shade) -> None:
    """The motor got both frames but no reply came: FAILURE, then its report."""
    shade.motor.fail_next_sends(2, delivered=True)

    assert await go_to(shade, 80) == foundation.Status.FAILURE
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [GO_80] * 2
    assert shade.covering.get(LIFT.id) == 80


async def test_stop_cancels_the_second_send(shade) -> None:
    """A Stop during the pause after a lost frame: that frame is never sent again."""
    shade.motor.drop_next(1)
    movement = asyncio.ensure_future(shade.covering.go_to_lift_percentage(80))
    await shade.clock.advance(6)
    stop, _ = await shade.outcome(shade.covering.stop(), within=5)
    result, _ = await shade.outcome(movement, within=5)

    assert status(stop) == SUCCESS
    assert status(result) == foundation.Status.FAILURE
    await shade.clock.advance(SETTLED_S)
    assert shade.commands() == [GO_80, STOP]


# --- Following travel ------------------------------------------------------------------


async def test_the_end_of_travel_report_needs_no_read(shade) -> None:
    """The shade reports where it stopped: nothing more goes out."""
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80]
    assert shade.covering.get(LIFT.id) == 80


async def test_without_a_report_the_lift_is_read_once_at_the_arrival(shade) -> None:
    """No report: one read at the estimated arrival for the distance."""
    shade.motor.reports = False
    assert await go_to(shade, 80) == SUCCESS

    await shade.clock.advance(ARRIVAL_40_S - JITTER_S)
    assert shade.wire() == [GO_80]
    await shade.clock.advance(2 * JITTER_S + shade.motor.reply_latency)
    assert shade.wire() == [GO_80, READ]
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, READ]
    assert shade.covering.get(LIFT.id) == 80


async def test_a_short_move_waits_at_least_5_s(shade) -> None:
    """A 1-point move is read 5 s after the reply, not sooner."""
    shade.motor.reports = False
    assert await go_to(shade, 41) == SUCCESS

    await shade.clock.advance(5 - JITTER_S)
    assert READ not in shade.wire()
    await shade.clock.advance(2 * JITTER_S)
    assert READ in shade.wire()
    await shade.clock.advance(SETTLED_S)
    assert shade.covering.get(LIFT.id) == 41


async def test_an_unknown_start_waits_for_a_full_travel(shade) -> None:
    """With no cached lift the read waits 73 s, and only the target counts as travel.

    The shade stalls at 60 on the way to 80; from 60 the re-sent frame takes it there.
    """
    shade.covering.update_attribute(LIFT.id, None)
    shade.motor.reports = False
    shade.motor.stall_at = 60
    assert await go_to(shade, 80) == SUCCESS

    await shade.clock.advance(73 - JITTER_S)
    assert shade.wire() == [GO_80]
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, READ, GO_80, READ]
    assert shade.covering.get(LIFT.id) == 80


@pytest.mark.parametrize("reports", [True, False])
async def test_an_ignored_frame_is_sent_once_more(shade, reports) -> None:
    """The motor ignores the first frame: no travel by the arrival, so one re-send."""
    shade.motor.reports = reports
    shade.motor.ignore_next(1)
    assert await go_to(shade, 80) == SUCCESS

    await shade.clock.advance(ARRIVAL_40_S + 2 * shade.motor.reply_latency + JITTER_S)
    assert shade.wire() == [GO_80, READ, GO_80]
    await shade.clock.advance(SETTLED_S)

    assert lift_now(shade) == 80
    assert shade.covering.get(LIFT.id) == 80
    assert shade.wire() == [GO_80, READ, GO_80] + ([] if reports else [READ])


async def test_a_shade_that_never_moves_is_sent_one_more_frame_then_left(shade) -> None:
    """Re-sent once, read once more, then nothing for an hour."""
    shade.motor.ignore_commands = True
    assert await go_to(shade, 80) == SUCCESS

    await shade.clock.advance(3600)

    assert shade.wire() == [GO_80, READ, GO_80, READ]
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT


async def test_a_stall_after_travel_is_not_sent_again(shade) -> None:
    """Travel toward the target that stops short is travel: no re-send."""
    shade.motor.stall_at = 60
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80]
    assert shade.covering.get(LIFT.id) == 60


async def test_movement_away_from_the_target_is_not_travel(shade) -> None:
    """A read showing the shade further from the target draws the re-send."""
    shade.motor.reports = False
    shade.motor.script_lift_reads(30)
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, READ, GO_80, READ]


@pytest.mark.parametrize(("target", "resent"), [(43, False), (44, True)])
async def test_a_shade_within_3_of_the_target_is_there(shade, target, resent) -> None:
    """No travel, but within 3 points of the target: not sent again."""
    shade.motor.ignore_next(1)
    assert await go_to(shade, target) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    frame = ("go_to_lift_percentage", target)
    assert shade.commands() == [frame] * (2 if resent else 1)


async def test_an_unknown_lift_read_is_no_position(shade) -> None:
    """A read of 0xFF neither enters the cache nor draws a re-send."""
    shade.motor.reports = False
    shade.motor.ignore_next(1)
    shade.motor.script_lift_reads(0xFF)
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, READ]
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT


async def test_an_unknown_lift_report_is_no_position(shade) -> None:
    """A report of 0xFF neither enters the cache nor ends the wait for the shade."""
    shade.motor.reports = False
    assert await go_to(shade, 80) == SUCCESS
    report(shade, 0xFF)
    await shade.clock.advance(1)
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT

    await shade.clock.advance(SETTLED_S)
    assert shade.wire() == [GO_80, READ]
    assert shade.covering.get(LIFT.id) == 80


# --- Cancellation and Stop -------------------------------------------------------------


async def test_a_new_command_cancels_the_pending_follow_up(shade) -> None:
    """Only the latest movement is read; the earlier one is never re-sent."""
    shade.motor.reports = False
    shade.motor.ignore_next(1)
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(10)
    assert await go_to(shade, 20) == SUCCESS
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, ("go_to_lift_percentage", 20), READ]
    assert shade.covering.get(LIFT.id) == 20


async def test_another_shades_command_cancels_nothing(shade) -> None:
    """Follow-up is per shade."""
    shade.motor.ignore_next(1)
    assert await go_to(shade, 80) == SUCCESS
    other = covering_of(shade.app, OTHER_IEEE)
    await shade.outcome(other.down_close(), within=15)
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, READ, GO_80]
    assert shade.wire(OTHER_NWK) == [("down_close",)]


async def test_stop_mid_travel_is_shown_by_the_shades_report(shade) -> None:
    """One Stop frame; the shade reports where it halted, so nothing is read."""
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(3)

    result, _ = await shade.outcome(shade.covering.stop(), within=15)
    halted = lift_now(shade)
    await shade.clock.advance(SETTLED_S)

    assert status(result) == SUCCESS
    assert INITIAL_LIFT < halted < 80
    assert shade.wire() == [GO_80, STOP]
    assert shade.covering.get(LIFT.id) == halted


async def test_stop_without_a_report_reads_once_after_3_s(shade) -> None:
    """No report within 3 s of the Stop: one read, and no re-send of the movement."""
    shade.motor.reports = False
    shade.motor.ignore_next(1)
    assert await go_to(shade, 80) == SUCCESS
    await shade.clock.advance(5)

    await shade.outcome(shade.covering.stop(), within=15)
    await shade.clock.advance(3 - shade.motor.reply_latency - JITTER_S)
    assert shade.wire() == [GO_80, STOP]
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [GO_80, STOP, READ]


async def test_a_lost_stop_is_sent_once(shade) -> None:
    """No reply to a Stop: it is not sent again, and the caller hears of it."""
    shade.motor.drop_next(1)

    result, _ = await shade.outcome(shade.covering.stop(), within=15)
    await shade.clock.advance(SETTLED_S)

    assert isinstance(result, (TimeoutError, zigpy.exceptions.ZigbeeException))
    assert shade.commands() == [STOP]
