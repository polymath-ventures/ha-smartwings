"""Tests for the SmartWings WM25/L-Z quirk, in upstream's test style."""

import asyncio
import dataclasses
import logging
import subprocess
import sys

import pytest
from zhaquirks import DoublingPowerConfigurationCluster
from zhaquirks.smartwings.wm25lz import InvertedWindowCoveringCluster, WM25LBlinds
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
    QUIRK_MODULE,
    READ,
    covering_of,
)
from tests.zha_harness import SHADE_IEEE, SHADE_NWK, report_packet


def test_quirk_imports_without_home_assistant() -> None:
    """The quirk is ZHA library code: loading it must not import Home Assistant."""
    probe = (
        "import importlib.util, sys; "
        "spec = importlib.util.spec_from_file_location('smartwings_wm25lz', sys.argv[1]); "
        "spec.loader.exec_module(importlib.util.module_from_spec(spec)); "
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] == 'homeassistant'); "
        "print(leaked); sys.exit(1 if leaked else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(QUIRK_FILE)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_shade_resolves_to_the_quirk_covering_cluster(app, wm25lz) -> None:
    """ZHA's resolver gives the WM25/L-Z the quirk's own WindowCovering cluster (v2)."""
    for ieee in (SHADE_IEEE, OTHER_IEEE):
        assert type(covering_of(app, ieee)) is wm25lz.WM25LZWindowCovering


async def test_live_read_parses_a_real_response(shade) -> None:
    """The live lift comes from zigpy's real Read Attributes path."""
    shade.motor.set_position(37)

    lift, _ = await shade.outcome(shade.covering._read_lift_live(), within=5)

    assert lift == 37
    assert shade.wire() == [READ]
    # The read only informs delivery; it does not write the cache.
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT


@pytest.mark.parametrize(
    "answer",
    [foundation.Status.UNSUPPORTED_ATTRIBUTE, 255, 101],
    ids=["unsupported", "unknown-255", "out-of-range"],
)
async def test_live_read_of_an_invalid_answer_is_unreadable(shade, answer) -> None:
    """An UNSUPPORTED_ATTRIBUTE status or a lift outside 0-100 is not a position."""
    shade.motor.script_lift_reads(answer)

    lift, _ = await shade.outcome(shade.covering._read_lift_live(), within=5)

    assert lift is None
    assert shade.wire() == [READ]
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT  # not marked unsupported


async def test_live_read_that_never_answers_is_unreadable(shade) -> None:
    """A read lost twice (first try and retry) times out into "unreadable"."""
    shade.motor.script_lift_reads(None, None)

    lift, _ = await shade.outcome(
        shade.covering._read_lift_live(),
        within=2 * shade.quirk.READ_TIMEOUT + shade.quirk.READ_RETRY_DELAY,
    )

    assert lift is None
    assert shade.wire() == [READ, READ]


def test_a_restored_lift_is_no_baseline(started_shade) -> None:
    """The lift zigpy restored is shown but is no baseline.

    Only a lift received since startup is, and it is known without sending anything.
    """
    shade = started_shade
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT
    assert shade.baseline() is None
    shade.covering.update_attribute(LIFT.id, 42)  # a read or report since startup
    assert shade.baseline() == 42
    shade.covering.update_attribute(LIFT.id, None)
    assert shade.baseline() is None
    assert shade.wire() == []


def test_wire_command_carries_frame_and_raw_target(shade) -> None:
    """WireCommand is the frozen seam between translation and delivery."""
    wire_command = shade.quirk.WireCommand(
        command_id=WindowCovering.ServerCommandDefs.go_to_lift_percentage.id,
        args=(84,),
        target_lift=84,
    )

    assert (wire_command.command_id, wire_command.args, wire_command.target_lift) == (
        0x05,
        (84,),
        84,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        wire_command.target_lift = 0


@pytest.mark.parametrize("loss", ["timeout", "delivery-error"])
async def test_read_is_retried_once_after_a_lost_attempt(shade, loss) -> None:
    """A lost first read is retried after READ_RETRY_DELAY; the caller gets the answer."""
    if loss == "timeout":
        shade.motor.script_lift_reads(None)
    else:
        shade.motor.fail_next_sends(1, delivered=False, reads=True)

    result, elapsed = await shade.outcome(
        # The form Home Assistant's refresh uses: attribute names, cache bypassed.
        shade.covering.read_attributes(
            [LIFT.name], allow_cache=False, only_cache=False
        ),
        within=2 * shade.quirk.READ_TIMEOUT + shade.quirk.READ_RETRY_DELAY + 1,
    )

    assert result == ({LIFT.name: INITIAL_LIFT}, {})
    assert shade.wire() == [READ, READ]
    assert elapsed >= shade.quirk.READ_RETRY_DELAY


async def test_read_lost_twice_raises(shade) -> None:
    """Only one retry: a second loss reaches the caller, after exactly two frames."""
    shade.motor.script_lift_reads(None, None)

    result, _ = await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False),
        within=2 * shade.quirk.READ_TIMEOUT + shade.quirk.READ_RETRY_DELAY,
    )

    assert isinstance(result, TimeoutError)
    assert shade.wire() == [READ, READ]


async def test_read_is_not_retried_on_other_errors(shade, monkeypatch) -> None:
    """An error that is not a lost frame propagates at once (guards fail closed)."""
    attempts = []

    async def broken_radio(packet) -> None:
        attempts.append(packet)
        raise RuntimeError("not a delivery failure")

    monkeypatch.setattr(shade.app, "send_packet", broken_radio)

    with pytest.raises(RuntimeError):
        await shade.clock.run(
            shade.covering.read_attributes([LIFT.id], allow_cache=False)
        )
    assert len(attempts) == 1


# --- Delivery: send once, judge after the travel time --------------------------

GO_TO = WindowCovering.ServerCommandDefs.go_to_lift_percentage
STOP = WindowCovering.ServerCommandDefs.stop
# 40 lift points at 5 points/s: the go-to 80 from INITIAL_LIFT travels 8 s, and the
# readback's arrival estimate is 40 / 100 x FULL_TRAVEL_S + ARRIVAL_MARGIN_S = 31 s.
ARRIVAL_40_S = 31.0
# Long enough for any test's travel, re-send and second travel to be over.
SETTLED_S = 400.0


def go_to(shade, target: int) -> tuple[str, int]:
    """Return go_to_lift_percentage(target), not yet started, and its frame."""
    return shade.covering.go_to_lift_percentage(target), (GO_TO.name, target)


def assert_failed(result, command_id: int = 0x05) -> None:
    """Assert delivery gave up through ZHA's own path: a FAILURE Default Response."""
    assert isinstance(result, foundation.DefaultResponse), result
    assert result.command_id == command_id
    assert result[1] is foundation.Status.FAILURE


def assert_success(result) -> None:
    """Assert the reply is one ZHA's ``res[1] is Status.SUCCESS`` check accepts."""
    assert isinstance(result, foundation.DefaultResponse), result
    assert result[1] is foundation.Status.SUCCESS


def lift_now(shade) -> int:
    """Return where the main shade's motor is now."""
    return round(shade.motor.position_at(shade.clock.time()))


async def test_a_movement_is_sent_once_and_returns_at_once(shade) -> None:
    """One frame, no read: the command returns with the radio's answer."""
    delivery, frame = go_to(shade, 80)

    result, elapsed = await shade.outcome(delivery, within=shade.quirk.T_EXEC)

    assert_success(result)
    assert shade.wire() == [frame]
    assert elapsed <= shade.motor.reply_latency + JITTER_S


async def test_the_end_of_travel_report_ends_it_without_a_read(shade) -> None:
    """The shade reports its lift when it stops: no read, no re-send, the cache at 80."""
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)

    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [frame]
    assert shade.covering.get(LIFT.id) == 80
    assert shade.baseline() == 80
    assert tracking_tasks() == []


async def test_reads_during_travel_never_count_against_it(shade) -> None:
    """Refreshes during travel answer the lift from before the move; nothing is re-sent.

    The radio answers reads from its copy of the lift, which changes only at the end of
    travel: a read 4 s into the go-to 80 still returns 40.
    """
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(3)

    await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
    )
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame]
    assert shade.covering.get(LIFT.id) == 80


async def test_reads_answer_from_the_radios_copy_without_reports(shade) -> None:
    """With no report, the read at the estimated arrival sees the end: one read."""
    shade.motor.reports = False
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)

    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [frame, READ]
    assert shade.covering.get(LIFT.id) == 80
    assert shade.baseline() == 80


@pytest.mark.parametrize("reports", [True, False], ids=["reports", "no-reports"])
async def test_an_ignored_first_frame_is_re_sent_once_after_the_travel_time(
    shade, reports
) -> None:
    """The motor ignores the first frame; at the estimated arrival the lift is unchanged.

    One read shows no travel, so the identical frame goes out once more and lands.
    Before that, the command has long returned SUCCESS.
    """
    shade.motor.reports = reports
    shade.motor.ignore_next(1)
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    assert_success(result)
    # The read leaves at the arrival estimate; its reply and the re-send follow.
    await shade.clock.advance(ARRIVAL_40_S + 2 * shade.motor.reply_latency + 1)
    assert shade.wire() == [frame, READ, frame]
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame, frame]
    assert lift_now(shade) == 80
    assert shade.covering.get(LIFT.id) == 80
    assert shade.baseline() == 80


async def test_a_shade_slower_than_the_estimate_gets_one_harmless_re_send(
    shade,
) -> None:
    """A read at the estimate catches the shade still travelling: the duplicate is safe.

    At 1 point/s the go-to 80 takes 40 s, longer than the 31 s estimate. The read
    returns the start lift, so the frame is re-sent; the motor keeps going and stops
    once, at 80. The command itself never fails.
    """
    shade.motor.rate_pct_per_s = 1.0
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands() == [frame, frame]
    assert lift_now(shade) == 80
    assert shade.covering.get(LIFT.id) == 80


async def test_a_shade_that_never_moves_is_re_sent_once_then_left(
    shade, caplog
) -> None:
    """A stuck motor: SUCCESS, one re-send after the travel time, then one WARNING.

    No error reaches Home Assistant after the command has returned.
    """
    shade.motor.ignore_commands = True
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(2 * shade.quirk.TRACK_MAX_DURATION)

    assert_success(result)
    assert shade.commands() == [frame, frame]
    [warning] = warnings_of(caplog)
    assert str(SHADE_IEEE) in warning.getMessage()
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT


async def test_movement_away_from_the_target_is_not_travel(shade) -> None:
    """A shade the remote sent the other way does not count as this command landing."""
    shade.motor.start_moving(30, shade.clock.time())  # heading away from 80
    shade.motor.ignore_next(1)
    delivery, frame = go_to(shade, 80)

    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame, frame]
    assert lift_now(shade) == 80


@pytest.mark.parametrize(
    ("answers", "reads"),
    [((255,), [READ, READ]), ((None, None), [READ, READ, READ])],
    ids=["unknown-255", "lost"],
)
async def test_an_unreadable_lift_is_no_evidence(shade, answers, reads) -> None:
    """An unreadable lift neither ends travel nor calls for a re-send.

    The next read, CONFIRM_GAP_S later, shows the shade at its target.
    """
    shade.motor.reports = False
    shade.motor.script_lift_reads(*answers)
    delivery, frame = go_to(shade, 80)

    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [frame, *reads]
    assert shade.covering.get(LIFT.id) == 80


async def test_a_lost_frame_is_sent_again_once(shade) -> None:
    """A frame lost on the air goes out once more, SEND_RETRY_DELAY later."""
    quirk = shade.quirk
    shade.motor.fail_next_sends(1, delivered=False)
    delivery, frame = go_to(shade, 80)

    result, elapsed = await shade.outcome(delivery, within=quirk.T_EXEC)

    assert_success(result)
    assert shade.wire() == [frame, frame]
    assert elapsed >= quirk.SEND_RETRY_DELAY


async def test_a_frame_lost_twice_fails_and_is_never_re_sent(shade) -> None:
    """Both frames lost: FAILURE through ZHA's path; the readback then only reads."""
    shade.motor.fail_next_sends(2, delivered=False)
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_failed(result)
    assert shade.commands() == [frame, frame]
    assert READ in shade.wire()


async def test_lost_acknowledgements_fail_but_the_shade_is_shown_where_it_went(
    shade,
) -> None:
    """Both frames reach the motor but their replies are lost: FAILURE, then the truth."""
    shade.motor.fail_next_sends(2, delivered=True)
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_failed(result)
    assert shade.commands() == [frame, frame]
    assert shade.covering.get(LIFT.id) == 80


@pytest.mark.parametrize("ignored", [False, True], ids=["moving", "first-ignored"])
async def test_stop_drops_the_re_send(shade, ignored) -> None:
    """After a Stop, nothing re-sends the movement; the shade is shown where it halted."""
    shade.motor.ignore_next(1 if ignored else 0)
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(2)

    await shade.outcome(shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT)
    halted = lift_now(shade)
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame, (STOP.name,)]
    assert lift_now(shade) == halted == (INITIAL_LIFT if ignored else 55)
    assert shade.covering.get(LIFT.id) == halted


async def test_stop_cancels_the_retry_of_a_lost_frame(shade) -> None:
    """Stop while a lost frame waits for its retry: the retry never goes out."""
    shade.motor.fail_next_sends(1, delivered=False)
    delivery, frame = go_to(shade, 80)
    task = asyncio.ensure_future(delivery)
    await shade.clock.advance(1)

    await shade.outcome(shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT)
    result, _ = await shade.outcome(task, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_failed(result)
    assert shade.commands() == [frame, (STOP.name,)]
    assert lift_now(shade) == INITIAL_LIFT


async def test_stop_cancels_a_re_send_the_readback_already_holds(shade) -> None:
    """A re-send taken by the readback before a Stop is not sent after it."""
    recorder = HookRecorder(shade.covering)
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(0)
    [resend] = recorder.resends

    await shade.outcome(shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT)
    await shade.outcome(resend(), within=shade.quirk.T_EXEC)

    assert shade.commands() == [frame, (STOP.name,)]


async def test_a_movement_queued_before_a_stop_is_dropped(shade) -> None:
    """A go_to(20) queued before a Stop never goes out after it, and answers SUCCESS.

    The user's later Stop supersedes it: go_to(80), go_to(20) waiting, then Stop.
    """
    shade.motor.reply_latency = 2.0
    first, first_frame = go_to(shade, 80)
    queued, queued_frame = go_to(shade, 20)
    first_task = asyncio.ensure_future(first)
    queued_task = asyncio.ensure_future(queued)
    await shade.clock.advance(1)

    await shade.outcome(shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT)
    (results, _) = await shade.clock.run(
        asyncio.gather(first_task, queued_task),
        limit=shade.quirk.LOCK_WAIT + shade.quirk.T_EXEC,
    )
    halted = lift_now(shade)
    await shade.clock.advance(SETTLED_S)

    assert_success(results[1])
    assert results[1].command_id == GO_TO.id
    assert queued_frame not in shade.commands()
    assert shade.commands() == [first_frame, (STOP.name,)]
    assert lift_now(shade) == halted < 80


async def test_a_movement_issued_after_a_stop_is_sent(shade) -> None:
    """Only commands issued before a Stop are dropped: one issued after it goes out."""
    await shade.outcome(shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT)
    delivery, frame = go_to(shade, 20)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert frame in shade.commands()
    assert lift_now(shade) == 20


async def test_a_stop_during_delivery_is_read_back_without_a_report(shade) -> None:
    """Stop cancels the retry and the readback; one read after the settle shows the halt.

    The first frame's reply is lost but the motor moves; Stop halts it at 45 while the
    retry waits. No report reaches the hub, so one read STOP_SETTLE_S later does.
    """
    quirk = shade.quirk
    shade.motor.reports = False
    shade.motor.fail_next_sends(1, delivered=True)
    delivery, frame = go_to(shade, 80)
    task = asyncio.ensure_future(delivery)
    await shade.clock.advance(1)

    await shade.outcome(shade.covering.stop(), within=quirk.SEND_TIMEOUT)
    result, _ = await shade.outcome(task, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_failed(result)
    assert lift_now(shade) == 45
    assert shade.covering.get(LIFT.id) == 45
    assert shade.wire() == [frame, (STOP.name,), READ]


async def test_a_movement_dropped_by_a_stop_does_not_cancel_its_read(shade) -> None:
    """A go_to(80) issued just before a Stop is dropped; Stop's read still happens.

    The remote has the shade travelling; the go-to and the Stop arrive in one loop
    turn, and no report reaches the hub. The dropped go-to must not cancel the read
    that shows where Stop halted the shade.
    """
    quirk = shade.quirk
    shade.motor.reports = False
    shade.motor.start_moving(60, shade.clock.time())
    await shade.clock.advance(2)
    delivery, frame = go_to(shade, 80)
    task = asyncio.ensure_future(delivery)

    await shade.outcome(shade.covering.stop(), within=quirk.SEND_TIMEOUT)
    result, _ = await shade.outcome(task, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert frame not in shade.commands()
    assert shade.wire() == [(STOP.name,), READ]
    assert shade.covering.get(LIFT.id) == lift_now(shade) == 50


async def test_a_stop_during_delivery_reported_by_the_shade_is_not_read(
    shade,
) -> None:
    """As above, but the shade reports where Stop halted it: no read follows."""
    quirk = shade.quirk
    shade.motor.fail_next_sends(1, delivered=True)
    delivery, frame = go_to(shade, 80)
    task = asyncio.ensure_future(delivery)
    await shade.clock.advance(1)

    await shade.outcome(shade.covering.stop(), within=quirk.SEND_TIMEOUT)
    await shade.outcome(task, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert shade.wire() == [frame, (STOP.name,)]
    assert shade.covering.get(LIFT.id) == lift_now(shade) == 45


async def test_the_re_send_is_one_frame_even_if_lost(shade) -> None:
    """The re-send after the travel time is a single frame, never retried."""
    recorder = HookRecorder(shade.covering)
    delivery, frame = go_to(shade, 80)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(0)
    [resend] = recorder.resends
    shade.motor.fail_next_sends(1, delivered=False)

    await shade.outcome(resend(), within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame, frame]


async def test_a_late_report_of_the_previous_move_does_not_mislead(
    shade, caplog
) -> None:
    """The report of a go-to 80 arrives after a go-to 20 was sent: the cover ends at 20.

    It may draw the one re-send, which is harmless; it never ends tracking early.
    """
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.report_latency = 3.0
    first, _ = go_to(shade, 80)
    await shade.outcome(first, within=shade.quirk.T_EXEC)
    await shade.clock.advance(7.5)

    second, frame = go_to(shade, 20)
    await shade.outcome(second, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert lift_now(shade) == 20
    assert shade.covering.get(LIFT.id) == 20
    assert shade.commands().count(frame) <= 2
    assert warnings_of(caplog) == []


@pytest.mark.parametrize(
    ("cached", "target"),
    [(None, 80), (40, 40), (40, 43)],
    ids=["no-baseline", "at-target", "within-tolerance"],
)
async def test_every_movement_takes_one_path(shade, cached, target) -> None:
    """No baseline, or a cache at the target: one frame as for any movement."""
    shade.covering.update_attribute(LIFT.id, cached)
    delivery, frame = go_to(shade, target)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands() == [frame]
    assert shade.covering.get(LIFT.id) == target


async def test_without_a_baseline_an_ignored_frame_is_re_sent(shade) -> None:
    """With no lift since startup, a lift away from the target at arrival is no travel."""
    shade.covering.update_attribute(LIFT.id, None)
    shade.motor.ignore_next(1)
    delivery, frame = go_to(shade, 80)

    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert shade.commands() == [frame, frame]
    assert lift_now(shade) == 80
    assert shade.covering.get(LIFT.id) == 80


async def test_a_command_without_a_target_passes_through_once(shade) -> None:
    """Stop goes out once, unverified; its lone 0x81 is reported as SUCCESS."""
    delivery = shade.covering._deliver(shade.quirk.WireCommand(STOP.id, (), None))

    result, _ = await shade.outcome(delivery, within=shade.quirk.SEND_TIMEOUT)

    assert result.status is foundation.Status.SUCCESS
    assert shade.wire() == [(STOP.name,)]


# --- Serialisation, bounds and tracking hooks -----------------------------------

TILT = WindowCovering.ServerCommandDefs.go_to_tilt_percentage


def hang_everything(shade) -> None:
    """Make the shade's radio swallow every frame: sends and reads hang to their timeouts."""
    shade.motor.drop_next(10**6)


async def test_two_commands_on_one_shade_are_serialised(shade) -> None:
    """The second command's frame goes out only after the first finished."""
    first, first_frame = go_to(shade, 80)
    second, second_frame = go_to(shade, 20)

    (results, _) = await shade.clock.run(asyncio.gather(first, second), limit=60)

    for result in results:
        assert_success(result)
    assert shade.wire() == [first_frame, second_frame]
    [first_sent, second_sent] = [f.sent_at for f in shade.app.frames]
    assert second_sent >= first_sent + shade.motor.reply_latency


async def test_a_stuck_shade_does_not_delay_another(shade) -> None:
    """Shade A's radio swallows every frame; shade B's command completes at once."""
    quirk = shade.quirk
    hang_everything(shade)
    other = covering_of(shade.app, OTHER_IEEE)
    finished: dict[str, float] = {}

    async def timed(name: str, delivery) -> object:
        start = shade.clock.time()
        try:
            return await delivery
        finally:
            finished[name] = shade.clock.time() - start

    stuck, _ = go_to(shade, 80)
    healthy = other.go_to_lift_percentage(80)

    (results, _) = await shade.clock.run(
        asyncio.gather(timed("A", stuck), timed("B", healthy), return_exceptions=True),
        limit=quirk.T_EXEC + JITTER_S,
    )

    assert_failed(results[0])
    assert_success(results[1])
    assert finished["B"] < finished["A"]
    assert finished["B"] <= quirk.T_EXEC
    assert shade.commands(OTHER_NWK) == [(GO_TO.name, 80)]


async def test_delivery_never_waits_on_its_own_lock(shade) -> None:
    """A delivery with a lost frame completes; both sends run holding the lock."""
    quirk = shade.quirk
    shade.motor.fail_next_sends(1, delivered=False)
    lock_held_at_sends = []
    send = shade.covering._send_frame

    async def spy(*args, **kwargs):
        lock_held_at_sends.append(shade.covering._command_lock.locked())
        return await send(*args, **kwargs)

    shade.covering._send_frame = spy
    delivery, frame = go_to(shade, 80)

    async def bounded():
        async with asyncio.timeout(quirk.T_EXEC + 1):
            return await delivery

    result, _ = await shade.outcome(bounded(), within=quirk.T_EXEC + 1)

    assert_success(result)
    assert shade.wire() == [frame, frame]
    assert lock_held_at_sends == [True, True]


async def test_a_busy_shade_gives_up_after_lock_wait(shade) -> None:
    """A command that cannot get the shade within LOCK_WAIT returns FAILURE, unsent."""
    quirk = shade.quirk
    await shade.covering._command_lock.acquire()
    delivery, _ = go_to(shade, 80)

    result, elapsed = await shade.outcome(delivery, within=quirk.LOCK_WAIT)

    assert_failed(result)
    assert elapsed >= quirk.LOCK_WAIT
    assert shade.wire() == []


async def test_pass_through_commands_skip_the_lock(shade) -> None:
    """Stop does not wait behind a command holding the shade."""
    await shade.covering._command_lock.acquire()
    delivery = shade.covering._deliver(shade.quirk.WireCommand(STOP.id, (), None))

    result, _ = await shade.outcome(delivery, within=shade.quirk.SEND_TIMEOUT)

    assert result.status is foundation.Status.SUCCESS
    assert shade.wire() == [(STOP.name,)]


async def test_worst_case_movement_command_ends_within_t_exec(shade) -> None:
    """Every send hangs: the command fails within T_EXEC."""
    quirk = shade.quirk
    hang_everything(shade)
    delivery, frame = go_to(shade, 80)

    result, elapsed = await shade.outcome(delivery, within=quirk.T_EXEC)

    assert_failed(result)
    assert elapsed >= quirk.T_EXEC - JITTER_S
    assert shade.wire() == [frame, frame]


async def test_worst_case_pass_through_ends_within_send_timeout(shade) -> None:
    """A hanging Stop fails within SEND_TIMEOUT."""
    quirk = shade.quirk
    hang_everything(shade)
    delivery = shade.covering._deliver(quirk.WireCommand(STOP.id, (), None))

    error, _ = await shade.outcome(delivery, within=quirk.SEND_TIMEOUT)

    assert isinstance(error, TimeoutError)
    assert shade.wire() == [(STOP.name,)]


async def test_worst_case_queued_command_ends_within_lock_wait_plus_t_exec(
    shade,
) -> None:
    """A command queued behind a worst-case one finishes within LOCK_WAIT + T_EXEC."""
    quirk = shade.quirk
    hang_everything(shade)
    first, _ = go_to(shade, 80)
    issued_after = 1.0

    async def queued():
        await asyncio.sleep(issued_after)
        start = shade.clock.time()
        delivery, _ = go_to(shade, 20)
        assert_failed(await delivery)
        return shade.clock.time() - start

    (results, _) = await shade.clock.run(
        asyncio.gather(first, queued(), return_exceptions=True),
        limit=issued_after + quirk.LOCK_WAIT + quirk.T_EXEC + JITTER_S,
    )

    assert_failed(results[0])
    assert results[1] <= quirk.LOCK_WAIT + quirk.T_EXEC + JITTER_S
    assert (GO_TO.name, 20) in shade.wire()


class HookRecorder:
    """Stands in for the position-readback hooks and records how they were called."""

    def __init__(self, covering) -> None:
        """Replace the cluster's hooks with recorders."""
        self.covering = covering
        self.calls: list[tuple] = []
        self.resends: list = []
        covering._cancel_tracking = self.cancel
        covering._on_movement_finished = self.finished

    def cancel(self) -> None:
        """Record a cancel, with whether the lock was held and anyone waited on it."""
        lock = self.covering._command_lock
        # asyncio.Lock keeps its waiters in _waiters; no public API says who waits.
        self.calls.append(("cancel", lock.locked(), bool(lock._waiters)))

    def finished(self, target_lift, resend=None) -> None:
        """Record a finish, with its target and the lock's state."""
        self.calls.append(
            ("finished", target_lift, self.covering._command_lock.locked())
        )
        self.resends.append(resend)


async def test_cancel_tracking_runs_before_waiting_for_the_lock(shade) -> None:
    """_cancel_tracking() is called before a movement command waits for a busy shade."""
    recorder = HookRecorder(shade.covering)
    await shade.covering._command_lock.acquire()
    delivery, _ = go_to(shade, 80)
    task = asyncio.ensure_future(delivery)

    await shade.clock.advance(1)

    assert not task.done()
    assert recorder.calls == [("cancel", True, False)]
    shade.covering._command_lock.release()
    await shade.clock.run(task)


@pytest.mark.parametrize(
    "wire_command",
    [(STOP.id, ()), (TILT.id, (30,))],
    ids=["stop", "tilt"],
)
async def test_pass_through_commands_call_no_hook(shade, wire_command) -> None:
    """Stop and tilt carry no target lift: neither hook runs."""
    recorder = HookRecorder(shade.covering)
    command_id, args = wire_command

    await shade.outcome(
        shade.covering._deliver(shade.quirk.WireCommand(command_id, args, None)),
        within=shade.quirk.SEND_TIMEOUT,
    )
    await shade.clock.advance(1)

    assert recorder.calls == []


async def test_finish_hook_runs_once_after_success_and_after_failure(shade) -> None:
    """_on_movement_finished(target, resend) follows each command, lock released.

    Only the command the radio answered with SUCCESS hands over a re-send.
    """
    quirk = shade.quirk
    recorder = HookRecorder(shade.covering)
    shade.motor.fail_next_sends(2, delivered=False)
    failed, _ = go_to(shade, 30)
    failure, _ = await shade.outcome(failed, within=quirk.T_EXEC)
    await shade.clock.advance(0)
    landed, _ = go_to(shade, 80)
    result, _ = await shade.outcome(landed, within=quirk.T_EXEC)
    await shade.clock.advance(0)

    assert_failed(failure)
    assert_success(result)
    [cancel_1, finished_1, cancel_2, finished_2] = recorder.calls
    assert cancel_1 == cancel_2 == ("cancel", False, False)
    assert finished_1 == ("finished", 30, False)
    assert finished_2 == ("finished", 80, False)
    [no_resend, resend] = recorder.resends
    assert no_resend is None
    assert callable(resend)


async def test_a_raising_hook_does_not_change_the_result(shade, caplog) -> None:
    """A hook that raises is reported by the event loop; the command still succeeds."""

    def broken(*_args) -> None:
        raise RuntimeError("broken tracker")

    shade.covering._cancel_tracking = broken
    shade.covering._on_movement_finished = broken
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    await shade.clock.advance(0)

    assert_success(result)
    assert shade.wire() == [frame]
    assert [r.exc_info[1].args for r in caplog.records if r.exc_info] == [
        ("broken tracker",),
        ("broken tracker",),
    ]


# --- Stock translation and wiring ----------------------------------------------------


@pytest.fixture
def vendor_covering(shade):
    """Put the released vendor quirk on the second shade; return its WindowCovering."""
    original = shade.app.get_device(OTHER_IEEE)
    vendor = WM25LBlinds(shade.app, OTHER_IEEE, OTHER_NWK, original)
    shade.app.devices[OTHER_IEEE] = vendor
    covering = vendor.endpoints[1].window_covering
    assert type(covering) is InvertedWindowCoveringCluster
    return covering


STOCK_COMMANDS = pytest.mark.parametrize(
    ("command", "args", "kwargs"),
    [
        ("go_to_lift_percentage", (37,), {}),
        ("go_to_lift_percentage", (), {"percentage_lift_value": 37}),
        ("go_to_lift_percentage", (100,), {}),
    ],
    ids=["go-to-positional", "go-to-keyword", "go-to-100"],
)


async def assert_same_frame_as_vendor(shade, vendor_covering, command, args, kwargs):
    """Send one command through the vendor quirk and through this one; compare the frames."""
    vendor_reply, _ = await shade.outcome(
        getattr(vendor_covering, command)(*args, **kwargs), within=5
    )
    ours, _ = await shade.outcome(
        getattr(shade.covering, command)(*args, **kwargs), within=shade.quirk.T_EXEC
    )

    vendor_frames = [f for f in shade.app.frames if f.dst_nwk == OTHER_NWK]
    our_frames = [
        f for f in shade.app.frames if f.dst_nwk == SHADE_NWK and not f.general
    ]
    # Delivery may re-send a lost frame; every frame it sends must be the vendor's.
    [vendor_frame] = vendor_frames
    assert our_frames
    vendor_bytes = vendor_frame.packet.data.serialize()
    for our_frame in our_frames:
        assert (our_frame.command_id, our_frame.args) == (
            vendor_frame.command_id,
            vendor_frame.args,
        )
        # Same ZCL frame control and payload; only the sequence number may differ.
        ours_bytes = our_frame.packet.data.serialize()
        assert (ours_bytes[0], ours_bytes[2:]) == (vendor_bytes[0], vendor_bytes[2:])
    assert ours[1] is vendor_reply[1]


@STOCK_COMMANDS
async def test_positions_send_the_released_quirk_frames(
    shade, vendor_covering, command, args, kwargs
) -> None:
    """A go-to goes out as the released vendor quirk sends it: ZHA's lift, unscaled."""
    await assert_same_frame_as_vendor(shade, vendor_covering, command, args, kwargs)


@pytest.mark.parametrize(
    ("command", "swapped"),
    [("up_open", "down_close"), ("down_close", "up_open")],
    ids=["open", "close"],
)
async def test_open_and_close_go_out_unswapped(
    shade, vendor_covering, command, swapped
) -> None:
    """Open is up_open and close is down_close, as ZHA sends them, not the vendor swap.

    Raw down_close lowers these units and raw up_open raises them; the motor stops
    each at its remote-set limit.
    """
    commands = WindowCovering.ServerCommandDefs
    await shade.outcome(getattr(vendor_covering, command)(), within=5)
    [vendor_frame] = [f for f in shade.app.frames if f.dst_nwk == OTHER_NWK]

    result, _ = await shade.outcome(
        getattr(shade.covering, command)(), within=shade.quirk.T_EXEC
    )

    assert_success(result)
    assert vendor_frame.command_id == getattr(commands, swapped).id
    our_frames = [
        f for f in shade.app.frames if f.dst_nwk == SHADE_NWK and not f.general
    ]
    assert our_frames
    assert {(f.command_id, tuple(f.args.values())) for f in our_frames} == {
        (getattr(commands, command).id, ())
    }
    assert shade.motor.target == (100 if command == "down_close" else 0)


@pytest.mark.parametrize(
    ("command", "args", "target"),
    [
        ("up_open", (), 0),
        ("down_close", (), 100),
        ("go_to_lift_percentage", (84,), 84),
    ],
)
def test_translation_keeps_the_command_and_targets_its_lift(
    shade, command, args, target
) -> None:
    """Open toward lift 0, close toward 100 (the remote's lower limit), a go-to its lift."""
    command_id = getattr(WindowCovering.ServerCommandDefs, command).id

    translated, kwargs = shade.covering._translate(command_id, args, {})

    assert translated == shade.quirk.WireCommand(command_id, args, target)
    assert kwargs == {}


def test_no_inverted_lift(shade) -> None:
    """Go-to 10 carries lift 10, not 90: no value swap for an id swap."""
    wire_command, _ = shade.covering._translate(GO_TO.id, (10,), {})

    assert wire_command == shade.quirk.WireCommand(GO_TO.id, (10,), 10)


@pytest.mark.parametrize(
    ("command", "args"),
    [("stop", ()), ("go_to_tilt_percentage", (30,)), ("go_to_lift_percentage", (255,))],
    ids=["stop", "tilt", "lift-out-of-range"],
)
def test_commands_without_a_lift_target_are_translated_to_pass_through(
    shade, command, args
) -> None:
    """Stop, tilt and anything without a valid lift get no target."""
    command_id = getattr(WindowCovering.ServerCommandDefs, command).id

    wire_command, _ = shade.covering._translate(command_id, args, {})

    assert wire_command == shade.quirk.WireCommand(command_id, args, None)


async def test_a_lost_first_frame_through_the_cluster_is_resent(shade) -> None:
    """ZHA's call path, cluster.go_to_lift_percentage(), re-sends a lost frame."""
    shade.motor.drop_next(1)

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(84), within=shade.quirk.T_EXEC
    )

    assert_success(result)
    assert shade.commands() == [(GO_TO.name, 84)] * 2


async def test_normal_operation_logs_nothing_at_warning(shade, caplog) -> None:
    """Lost frames, re-sends, read retries and commands without a baseline log at DEBUG.

    Only a command whose end is never seen warns.
    """
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    # A lost frame, an ignored one re-sent after the travel time, a read retry.
    shade.motor.reports = False
    shade.motor.fail_next_sends(1, delivered=False)
    shade.motor.ignore_next(1)
    shade.motor.script_lift_reads(None)
    first, _ = go_to(shade, 80)
    await shade.outcome(first, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)
    # A command without a baseline, ended by the shade's report.
    shade.motor.reports = True
    shade.covering.update_attribute(LIFT.id, None)
    blind, _ = go_to(shade, 50)
    await shade.outcome(blind, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    records = [r for r in caplog.records if r.name == QUIRK_MODULE]
    messages = " | ".join(r.getMessage() for r in records)
    for expected in ("frame lost", "re-sending once", "retrying once", "final lift"):
        assert expected in messages
    assert lift_now(shade) == 50
    assert [r for r in records if r.levelno >= logging.WARNING] == []


async def test_a_failed_command_logs_at_debug_naming_the_shade(shade, caplog) -> None:
    """Giving up logs the shade's IEEE at DEBUG; nothing reaches WARNING."""
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.fail_next_sends(2, delivered=False)
    delivery, _ = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)

    assert_failed(result)
    records = [r for r in caplog.records if r.name == QUIRK_MODULE]
    assert [r for r in records if r.levelno >= logging.WARNING] == []
    assert any(
        "giving up" in r.getMessage() and str(SHADE_IEEE) in r.getMessage()
        for r in records
    )


def test_keyword_go_to_is_translated_to_a_verified_command(shade) -> None:
    """The keyword form gets the same target as the positional one, not a pass-through."""
    wire_command, kwargs = shade.covering._translate(
        GO_TO.id, (), {"percentage_lift_value": 84, "retries": 1}
    )

    assert wire_command == shade.quirk.WireCommand(GO_TO.id, (84,), 84)
    assert kwargs == {"retries": 1}


# --- Retries and baselines -------------------------------------------------------------


async def test_caller_retries_cannot_add_frames_to_a_delivery(shade) -> None:
    """A caller's zigpy ``retries`` is overridden: each attempt is one frame."""
    quirk = shade.quirk
    shade.motor.fail_next_sends(10**3, delivered=False)
    delivery = shade.covering.command(GO_TO.id, 80, retries=1)

    result, _ = await shade.outcome(delivery, within=quirk.T_EXEC)

    assert_failed(result)
    assert shade.wire() == [(GO_TO.name, 80)] * quirk.SEND_ATTEMPTS


async def test_caller_retries_cannot_add_frames_to_a_read(shade) -> None:
    """A read lost on both attempts is two frames, even if the caller asks for retries."""
    shade.motor.fail_next_sends(10**3, delivered=False, reads=True)

    error, _ = await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False, retries=1),
        within=10,
    )

    assert isinstance(error, zigpy.exceptions.DeliveryError)
    assert shade.wire() == [READ, READ]


async def test_delivery_leaves_the_cache_and_listeners_alone(shade) -> None:
    """Delivery reads nothing and writes nothing: the cover keeps its last position.

    Only a lift the shade sends, or the readback reads, moves the position shown.
    """
    shade.motor.ignore_commands = True
    events = []
    for event_type in ("attribute_read", "attribute_updated"):
        shade.covering.on_event(event_type, events.append)
    delivery, frame = go_to(shade, 80)

    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)

    assert_success(result)
    assert shade.wire() == [frame]
    assert events == []
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT


async def test_a_command_during_travel_is_not_judged_by_the_old_baseline(shade) -> None:
    """A command sent while the shade travels has no baseline.

    A go-to 100 from 40 lands; a go-to 90 sent at once is ignored by the motor. Judged
    against 40, the shade reaching 100 would pass for travel toward 90 and the go-to 90
    would never be re-sent.
    """
    first, _ = go_to(shade, 100)
    result, _ = await shade.outcome(first, within=shade.quirk.T_EXEC)
    assert_success(result)

    shade.motor.ignore_next(1)
    second, frame = go_to(shade, 90)
    result, _ = await shade.outcome(second, within=shade.quirk.T_EXEC)
    assert shade.covering._command_origin is None
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands()[-2:] == [frame, frame]
    assert lift_now(shade) == 90


async def test_the_lift_seen_at_the_end_of_travel_is_the_next_baseline(shade) -> None:
    """Sending retires the baseline; a lift read in travel is none; the end's is."""
    delivery, _ = go_to(shade, 80)
    result, _ = await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    assert_success(result)
    assert shade.baseline() is None

    shade.covering.update_attribute(LIFT.id, 60)  # a refresh while it travels
    assert shade.baseline() is None
    await shade.clock.advance(SETTLED_S)

    assert shade.baseline() == 80


@pytest.mark.parametrize(
    ("start", "baseline"),
    [("late", 80), ("never", None)],
    ids=["ends-at-the-target", "never-moves"],
)
async def test_after_readback_gives_up_only_a_seen_end_is_a_baseline(
    shade, start, baseline
) -> None:
    """After a give-up, the re-read is a baseline only if it shows travel ended.

    A shade that starts after readback gave up is at its target by the re-read; one
    that never moves reads its start lift again, which is no end.
    """
    quirk = shade.quirk
    shade.motor.reports = False
    if start == "late":
        shade.motor.start_delay = 2 * quirk.TRACK_MAX_DURATION + 20
    else:
        shade.motor.ignore_commands = True
    delivery, _ = go_to(shade, 80)
    result, _ = await shade.outcome(delivery, within=quirk.T_EXEC)
    assert_success(result)

    await shade.clock.advance(2 * quirk.TRACK_MAX_DURATION)
    assert tracking_tasks() == [] or all(
        "re-read" in task.get_name() for task in tracking_tasks()
    )
    assert shade.baseline() is None
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY)

    assert shade.baseline() == baseline


async def test_a_lift_read_after_readback_gave_up_in_travel_is_no_baseline(
    shade,
) -> None:
    """Readback gives up before a late start; a refresh after it is no baseline.

    The go-to 80 starts only after tracking has given up, and a refresh then reads the
    lift. A go-to 90 the motor ignores is still re-sent and lands.
    """
    quirk = shade.quirk
    shade.motor.reports = False
    shade.motor.start_delay = 2 * quirk.TRACK_MAX_DURATION + 20
    delivery, _ = go_to(shade, 80)
    result, _ = await shade.outcome(delivery, within=quirk.T_EXEC)
    assert_success(result)
    await shade.clock.advance(shade.motor.moving_since + 2 - shade.clock.time())

    await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
    )
    assert shade.baseline() is None
    shade.motor.start_delay = 0
    shade.motor.ignore_next(1)
    second, frame = go_to(shade, 90)
    result, _ = await shade.outcome(second, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands()[-2:] == [frame, frame]
    assert lift_now(shade) == 90


async def test_an_unverified_go_to_retires_the_baseline(shade) -> None:
    """A go-to without a valid lift may move the shade with no readback after it."""
    await shade.outcome(
        shade.covering.go_to_lift_percentage(255), within=shade.quirk.SEND_TIMEOUT
    )

    assert shade.commands() == [(GO_TO.name, 255)]
    assert shade.baseline() is None


async def test_a_superseded_command_does_not_start_tracking(shade) -> None:
    """When a queued command takes over, the earlier one's finish hook does not run."""
    recorder = HookRecorder(shade.covering)
    first, _ = go_to(shade, 80)
    second, _ = go_to(shade, 20)

    await shade.clock.run(asyncio.gather(first, second), limit=60)
    await shade.clock.advance(0)

    assert [call[:2] for call in recorder.calls] == [
        ("cancel", False),
        ("cancel", True),
        ("finished", 20),
    ]


async def test_a_command_that_gives_up_on_the_lock_does_not_supersede(
    shade, monkeypatch
) -> None:
    """A busy timeout sends nothing and leaves the in-flight command's tracking to run."""
    quirk = shade.quirk
    monkeypatch.setattr(quirk, "LOCK_WAIT", 5.0)
    recorder = HookRecorder(shade.covering)
    hang_everything(shade)
    in_flight, _ = go_to(shade, 80)

    async def gives_up():
        await asyncio.sleep(1)
        delivery, _ = go_to(shade, 20)
        return await delivery

    (results, _) = await shade.clock.run(
        asyncio.gather(in_flight, gives_up(), return_exceptions=True),
        limit=quirk.T_EXEC + JITTER_S,
    )
    await shade.clock.advance(0)

    assert_failed(results[0])
    assert_failed(results[1])
    assert (GO_TO.name, 20) not in shade.wire()
    assert [call[:2] for call in recorder.calls] == [
        ("cancel", False),
        ("cancel", True),
        ("finished", 80),
    ]


async def resend_after_arrival_read(shade, target: int, answer: int) -> list:
    """Deliver a go-to the motor ignores; answer the arrival read; return the commands."""
    shade.motor.reports = False
    shade.motor.ignore_next(1)
    shade.motor.script_lift_reads(answer)
    delivery, _ = go_to(shade, target)
    await shade.outcome(delivery, within=shade.quirk.T_EXEC)
    # Past the first read with no baseline (full travel), and the re-send it calls for.
    quirk = shade.quirk
    await shade.clock.advance(quirk.FULL_TRAVEL_S + quirk.ARRIVAL_MARGIN_S + 5)
    return shade.commands()


@pytest.mark.parametrize(
    ("look", "expected"),
    [
        (INITIAL_LIFT + 1, "resend"),
        (INITIAL_LIFT + 2, "travel"),
        (INITIAL_LIFT - 2, "resend"),
    ],
    ids=["below-tolerance", "at-tolerance", "at-tolerance-wrong-way"],
)
async def test_movement_tolerance_boundary(shade, look, expected) -> None:
    """Travel counts from exactly MOVED_TOLERANCE points toward the target, not before."""
    assert shade.quirk.MOVED_TOLERANCE == 2
    frame = (GO_TO.name, 80)

    commands = await resend_after_arrival_read(shade, 80, look)

    assert commands == ([frame] if expected == "travel" else [frame, frame])


@pytest.mark.parametrize(
    ("look", "expected"),
    [(77, "travel"), (76, "resend"), (83, "travel"), (84, "resend")],
    ids=["within-below", "outside-below", "within-above", "outside-above"],
)
async def test_at_target_tolerance_boundary(shade, look, expected) -> None:
    """Without a baseline, only a lift within AT_TARGET_TOLERANCE of the target is travel."""
    assert shade.quirk.AT_TARGET_TOLERANCE == 3
    shade.covering.update_attribute(LIFT.id, None)
    frame = (GO_TO.name, 80)

    commands = await resend_after_arrival_read(shade, 80, look)

    assert commands == ([frame] if expected == "travel" else [frame, frame])


# --- The vendor quirk's battery reading ---------------------------------------------

BATTERY = PowerConfiguration.AttributeDefs.battery_percentage_remaining


async def test_battery_reports_are_doubled_as_the_vendor_quirk_does(
    shade, vendor_covering
) -> None:
    """The same battery report caches the same value under this and the released quirk.

    The released quirk replaces PowerConfiguration so a report of 42 caches 84; this
    quirk supersedes it, so it must keep the doubling.
    """
    ours = shade.app.get_device(SHADE_IEEE).endpoints[1].power
    vendor = shade.app.get_device(OTHER_IEEE).endpoints[1].power

    for nwk in (SHADE_NWK, OTHER_NWK):
        shade.app.packet_received(
            report_packet(PowerConfiguration.cluster_id, BATTERY.id, 42, nwk=nwk)
        )
    await shade.clock.advance(1)

    assert vendor.get(BATTERY.id) == 84
    assert ours.get(BATTERY.id) == vendor.get(BATTERY.id)
    assert isinstance(ours, DoublingPowerConfigurationCluster)


# --- Stop: once, never synthesised, its second reply no error ---------------------


@pytest.mark.parametrize("reply", [None, "success-first", "unsup-first", "unsup-only"])
async def test_stop_is_one_unchanged_frame_and_succeeds(shade, reply) -> None:
    """One Stop frame, no read or go-to; whichever reply wins, the caller gets SUCCESS.

    The radio forwards a standard Stop and the motor halts; the 0x81 is the
    firmware's second reply, as for a movement.

    A shade at rest sends no report, so one read STOP_SETTLE_S later shows where it is.
    """
    shade.motor.double_reply = reply
    translated, _ = shade.covering._translate(STOP.id, (), {})

    result, _ = await shade.outcome(
        shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT
    )
    await shade.clock.advance(shade.quirk.T_EXEC)

    assert translated == shade.quirk.WireCommand(STOP.id, (), None)
    assert result.status is foundation.Status.SUCCESS
    assert result.command_id == STOP.id
    assert shade.wire() == [(STOP.name,), READ]


async def test_a_stop_that_raises_is_not_hidden(shade) -> None:
    """Only the 0x81 is mapped: a Stop lost on the air still fails as zigpy reports it."""
    shade.motor.fail_next_sends(1, delivered=False)

    result, _ = await shade.outcome(
        shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT
    )

    assert isinstance(result, zigpy.exceptions.DeliveryError)
    assert shade.wire() == [(STOP.name,)]


# --- The displayed position is the lift the shade sent ----------------------------


def lift_events(shade) -> list[tuple[str, int | None]]:
    """Collect the lift events the cover cluster emits, as (event type, value)."""
    events: list[tuple[str, int | None]] = []

    def record(event) -> None:
        if event.attribute_id == LIFT.id:
            events.append((event.event_type, getattr(event, "value", None)))

    for event_type in ("attribute_updated", "attribute_read", "attribute_report"):
        shade.covering.on_event(event_type, record)
    return events


@pytest.mark.parametrize("lift", [100, 41, 0])
async def test_a_read_caches_the_lift_as_sent(shade, lift) -> None:
    """A read returns and caches the shade's lift unchanged; ZHA does 100 - lift."""
    shade.motor.set_position(lift)
    events = lift_events(shade)

    result, _ = await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
    )

    assert result == ({LIFT.id: lift}, {})
    assert shade.covering.get(LIFT.id) == lift
    assert events[-1][1] == lift
    assert shade.baseline() == lift


async def test_a_report_is_cached_as_sent(shade) -> None:
    """A Report Attributes frame of lift 41 caches 41."""
    shade.app.packet_received(report_packet(WindowCovering.cluster_id, LIFT.id, 41))
    await shade.clock.advance(1)

    assert shade.covering.get(LIFT.id) == 41
    assert shade.baseline() == 41


async def test_an_unknown_lift_never_enters_the_cache(shade) -> None:
    """Lift 255 (ZCL "unknown") leaves the cache and the raw lift as they were."""
    shade.covering.update_attribute(LIFT.id, 42)
    cached = shade.covering.get(LIFT.id)
    shade.motor.script_lift_reads(255)

    await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
    )
    shade.covering.update_attribute(LIFT.id, 101)

    assert shade.covering.get(LIFT.id) == cached
    assert shade.baseline() == 42


@pytest.mark.parametrize("path", ["read", "report"])
async def test_an_unknown_lift_emits_no_event(shade, path) -> None:
    """Lift 255 is no news: no lift event reaches ZHA, which would take it as a position.

    zigpy re-announces the cached value when a quirk keeps it; that must not happen.
    """
    shade.covering.update_attribute(LIFT.id, 42)
    events = lift_events(shade)

    if path == "read":
        shade.motor.script_lift_reads(255)
        result, _ = await shade.outcome(
            shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
        )
        assert result == ({LIFT.id: 255}, {})
    else:
        shade.app.packet_received(
            report_packet(WindowCovering.cluster_id, LIFT.id, 255)
        )
        await shade.clock.advance(1)

    assert events == []
    assert shade.baseline() == 42


# --- The shade's lock ----------------------------------------------------------------


async def test_stop_passes_a_busy_shade(shade) -> None:
    """Stop never waits for the lock: one frame while another command holds the shade."""
    await shade.covering._command_lock.acquire()

    result, _ = await shade.outcome(
        shade.covering.stop(), within=shade.quirk.SEND_TIMEOUT
    )

    assert result.status is foundation.Status.SUCCESS
    assert shade.wire() == [(STOP.name,)]
    assert shade.covering._command_lock.locked()  # still the other command's


async def test_a_targetless_movement_supersedes_the_command_it_waited_behind(
    shade,
) -> None:
    """A go-to without a valid lift takes the lock, so the earlier finish is stale.

    The command it queued behind must not start tracking its old target while this
    one is being sent.
    """
    recorder = HookRecorder(shade.covering)
    first = asyncio.ensure_future(shade.covering.go_to_lift_percentage(80))
    await shade.clock.advance(0.1)
    queued = asyncio.ensure_future(shade.covering.go_to_lift_percentage(255))

    await shade.clock.run(
        asyncio.gather(first, queued), limit=shade.quirk.LOCK_WAIT + shade.quirk.T_EXEC
    )
    await shade.clock.advance(1)

    assert [call for call in recorder.calls if call[0] == "finished"] == []
    assert shade.commands()[-1] == (GO_TO.name, 255)


async def test_the_busy_message_follows_lock_wait(shade, monkeypatch, caplog) -> None:
    """Giving up on a busy shade names the wait actually used (one source: LOCK_WAIT)."""
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    monkeypatch.setattr(shade.quirk, "LOCK_WAIT", 3.0)
    await shade.covering._command_lock.acquire()

    result, elapsed = await shade.outcome(
        shade.covering.down_close(), within=shade.quirk.T_EXEC
    )

    assert_failed(result, command_id=0x01)
    assert 3.0 <= elapsed < 4.0
    assert "busy with another command for 3 s" in caplog.text


# --- Position readback: the final position after travel -----------------------------

FULL_TRAVEL_60_S = 100 / 60  # lift points per second: a full travel in 60 s


def at_rest(shade, lift: int) -> None:
    """Put the motor at ``lift`` and cache the same raw lift, as a read would."""
    shade.motor.set_position(lift)
    shade.covering.update_attribute(LIFT.id, lift)


def track(shade, target: int, resend=None) -> float:
    """Start tracking travel toward ``target`` through the hook; return the start time.

    The baseline stands for the lift before the command, as delivery records it.
    """
    start = shade.clock.time()
    shade.covering._command_origin = shade.baseline()
    shade.covering._on_movement_finished(target, resend)
    return start


def read_times(shade, since: float, nwk: int = SHADE_NWK) -> list[float]:
    """Return when each lift read attempt to a shade left, in seconds after ``since``."""
    return [
        round(frame.sent_at - since, 1)
        for frame in shade.app.frames
        if frame.dst_nwk == nwk
        and frame.cluster_id == WindowCovering.cluster_id
        and frame.general
        and frame.sent_at >= since
    ]


def tracking_tasks() -> list[asyncio.Task]:
    """Return the position-readback tasks still pending on the loop."""
    return [
        task
        for task in asyncio.all_tasks()
        if "position readback" in task.get_name() and not task.done()
    ]


def warnings_of(caplog) -> list[logging.LogRecord]:
    """Return the quirk's records at WARNING or above."""
    return [r for r in caplog.records if r.name == QUIRK_MODULE and r.levelno >= 30]


async def test_reaching_the_target_ends_tracking_after_one_read(shade) -> None:
    """A go-to lift 60 tracker ends at the first reading of 60."""
    at_rest(shade, 40)
    shade.motor.start_moving(60, shade.clock.time())

    start = track(shade, 60)
    await shade.clock.advance(600)

    # 20 points: 20 / 100 x FULL_TRAVEL_S + ARRIVAL_MARGIN_S = 17 s.
    assert read_times(shade, start) == [17.0]
    assert shade.covering.get(LIFT.id) == 60
    assert tracking_tasks() == []


async def test_a_stall_short_of_the_target_settles_where_it_stopped(shade) -> None:
    """A go-to lift 0 stalls at 45: two readings of 45 end it."""
    at_rest(shade, 80)
    shade.motor.stall_at = 45
    shade.motor.start_moving(0, shade.clock.time())

    start = track(shade, 0)
    await shade.clock.advance(600)

    # 80 points: 59 s to the arrival reading, then CONFIRM_GAP_S plus its reply.
    assert read_times(shade, start) == [59.0, 65.0]
    assert shade.covering.get(LIFT.id) == 45
    assert shade.baseline() == 45


async def test_a_moving_shade_keeps_being_tracked(shade, caplog) -> None:
    """Readings 30, 42, 55 never settle: all three are taken and cached."""
    at_rest(shade, 0)
    shade.motor.script_lift_reads(30, 42, 55)

    start = track(shade, 100)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)

    assert len(read_times(shade, start)) == 3
    assert shade.covering.get(LIFT.id) == 55


async def test_an_early_reading_never_stands_as_final(shade) -> None:
    """A refresh 10 s into a 60 s close reads the old 0; the end, 100, replaces it.

    The radio answers reads from its copy of the lift until the motor reports the end
    of travel.
    """
    at_rest(shade, 0)
    shade.motor.rate_pct_per_s = FULL_TRAVEL_60_S
    events = lift_events(shade)

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(100), within=shade.quirk.T_EXEC
    )
    assert_success(result)
    await shade.clock.advance(9)
    await shade.outcome(
        shade.covering.read_attributes([LIFT.id], allow_cache=False), within=5
    )
    assert shade.covering.get(LIFT.id) == 0
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)

    assert shade.covering.get(LIFT.id) == 100
    assert events[-1][1] == 100
    assert shade.commands() == [(GO_TO.name, 100)]


async def test_a_failed_delivery_is_tracked_and_sees_a_late_start(shade) -> None:
    """Both frames' replies are lost but the motor starts late: the end is still seen."""
    quirk = shade.quirk
    shade.motor.start_delay = 30
    shade.motor.fail_next_sends(2, delivered=True)

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(80), within=quirk.T_EXEC
    )
    assert_failed(result)
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert shade.covering.get(LIFT.id) == 80


@pytest.mark.parametrize(
    ("cached", "target", "first_read"),
    [(0, 100, 73.0), (50, 60, 10.0), (59, 60, 5.0), (None, 60, 73.0)],
    ids=["full-close", "ten-points", "never-before-min", "unknown-is-full"],
)
async def test_the_first_read_is_at_the_estimated_arrival(
    shade, cached, target, first_read
) -> None:
    """The share of full travel x FULL_TRAVEL_S + ARRIVAL_MARGIN_S, at least 5 s."""
    shade.motor.rate_pct_per_s = FULL_TRAVEL_60_S
    if cached is None:
        shade.covering.update_attribute(LIFT.id, None)
        shade.motor.set_position(0)
    else:
        at_rest(shade, cached)
    shade.motor.start_moving(target, shade.clock.time())

    start = track(shade, target)
    await shade.clock.advance(600)

    assert read_times(shade, start) == [first_read]
    assert shade.covering.get(LIFT.id) == target


async def test_a_never_stationary_shade_is_abandoned_within_the_bounds(
    shade, caplog
) -> None:
    """Every reading differs: three readings by TRACK_MAX_DURATION, one WARNING."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    at_rest(shade, 0)
    shade.motor.rate_pct_per_s = 0.1
    # Positions sent during travel, so reads show it moving.
    shade.motor.report_interval_s = 1.0
    shade.motor.start_moving(100, shade.clock.time())

    start = track(shade, 100)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    times = read_times(shade, start)
    assert len(times) == quirk.TRACK_MAX_READINGS
    assert times[0] == 73.0
    assert times[1] == 79.0  # CONFIRM_GAP_S after the arrival reading's reply
    assert times[-1] + quirk.T_READ <= quirk.TRACK_MAX_DURATION
    [warning] = warnings_of(caplog)
    assert str(SHADE_IEEE) in warning.getMessage()
    assert "still moving" in warning.getMessage()
    assert tracking_tasks()  # the deferred re-read is pending

    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY)

    assert len(read_times(shade, start)) == quirk.TRACK_MAX_READINGS + 1
    assert tracking_tasks() == []
    assert len(warnings_of(caplog)) == 1


async def test_an_unreadable_shade_stops_being_read(shade, caplog) -> None:
    """Every read fails: TRACK_MAX_READINGS readings, one WARNING, one re-read."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.fail_next_sends(10**3, delivered=False, reads=True)
    resends = []

    async def resend() -> None:
        resends.append(True)

    start = track(shade, 80, resend)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert resends == []  # an unreadable lift never calls for the re-send
    assert len(read_times(shade, start)) == quirk.TRACK_MAX_READINGS * 2
    [warning] = warnings_of(caplog)
    assert str(SHADE_IEEE) in warning.getMessage()
    assert "unreadable" in warning.getMessage()

    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)

    times = read_times(shade, start)
    # Every read with its retry, then the re-read with its retry; nothing to re-send.
    assert len(times) == (quirk.TRACK_MAX_READINGS + 1) * 2
    assert times[-2] >= quirk.DEFERRED_REREAD_DELAY
    assert len(warnings_of(caplog)) == 1
    assert tracking_tasks() == []


async def test_a_dropped_read_and_its_retry_are_one_reading(shade) -> None:
    """A lost first attempt then 30: three readings are still taken, 55 last."""
    at_rest(shade, 0)
    shade.motor.script_lift_reads(None, 30, 42, 55)

    start = track(shade, 100)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)

    assert len(read_times(shade, start)) == 4
    assert shade.covering.get(LIFT.id) == 55


async def abandon(shade) -> float:
    """Track toward 100 with readings that never settle; return the start time."""
    at_rest(shade, 0)
    shade.motor.script_lift_reads(30, 42, 55)
    start = track(shade, 100)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)
    assert len(read_times(shade, start)) == 3
    return start


async def test_the_deferred_re_read_corrects_the_position(shade) -> None:
    """After an abandoned tracking, the re-read 300 s later caches the real lift."""
    await abandon(shade)
    shade.motor.set_position(77)

    await shade.clock.advance(shade.quirk.DEFERRED_REREAD_DELAY)

    assert shade.covering.get(LIFT.id) == 77
    assert tracking_tasks() == []


async def test_a_later_movement_cancels_the_deferred_re_read(shade) -> None:
    """A command after an abandoned tracking cancels its pending re-read."""
    quirk = shade.quirk
    await abandon(shade)
    shade.motor.set_position(60)
    shade.motor.reports = False
    shade.covering.update_attribute(LIFT.id, 60)
    commanded = shade.clock.time()

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(61), within=quirk.T_EXEC
    )
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)

    assert_success(result)
    # One frame, then the new command's own tracking: one read at 5 s.
    assert len(read_times(shade, commanded)) == 1
    assert tracking_tasks() == []


async def test_a_new_command_supersedes_tracking(shade) -> None:
    """An open during a close's tracking is sent at once; a new tracker follows."""
    quirk = shade.quirk
    at_rest(shade, 80)
    shade.motor.reports = False
    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(100), within=quirk.T_EXEC
    )
    assert_success(result)
    [tracker] = tracking_tasks()
    # The close's first tracking read is due 17 s after it finished.
    await shade.clock.advance(5)
    commanded = shade.clock.time()

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(0), within=quirk.T_EXEC
    )
    await shade.clock.advance(0)

    assert_success(result)
    assert tracker.cancelled()
    frames = [f for f in shade.app.frames if f.sent_at >= commanded and not f.general]
    assert len(frames) == 1
    assert frames[0].sent_at - commanded < JITTER_S
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)
    assert shade.covering.get(LIFT.id) == 0
    # Only the open's own tracking read: the close's never ran.
    assert len(read_times(shade, commanded)) == 1


async def test_a_read_in_flight_is_abandoned_on_supersede(shade) -> None:
    """Cancelling during a tracking read leaves no task and no unretrieved error."""
    quirk = shade.quirk
    errors: list[dict] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        at_rest(shade, 59)
        shade.motor.reply_latency = 2.0
        start = track(shade, 60)
        await shade.clock.advance(quirk.TRACK_MIN_FIRST_READ_S + 1)
        assert read_times(shade, start) == [5.0]

        shade.covering._cancel_tracking()
        await shade.clock.advance(600)
    finally:
        loop.set_exception_handler(None)

    assert tracking_tasks() == []
    assert errors == []
    assert read_times(shade, start) == [5.0]


async def test_tracking_never_holds_the_lock(shade) -> None:
    """Every tracking read runs with the shade's lock free."""
    lock_held_at_reads = []
    read = shade.covering.read_attributes_raw

    async def spy(*args, **kwargs):
        lock_held_at_reads.append(shade.covering._command_lock.locked())
        return await read(*args, **kwargs)

    shade.covering.read_attributes_raw = spy
    at_rest(shade, 0)
    shade.motor.stall_at = 30
    shade.motor.start_moving(100, shade.clock.time())

    track(shade, 100)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)

    assert lock_held_at_reads == [False, False]


async def test_stop_does_not_cancel_tracking(shade) -> None:
    """Stop leaves tracking running to the real end: where the shade halted."""
    quirk = shade.quirk
    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(100), within=quirk.T_EXEC
    )
    assert_success(result)
    [tracker] = tracking_tasks()

    stopped, _ = await shade.outcome(shade.covering.stop(), within=quirk.SEND_TIMEOUT)
    halted = lift_now(shade)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert stopped[1] is foundation.Status.SUCCESS
    assert tracker.done() and not tracker.cancelled()
    assert INITIAL_LIFT < halted < 100
    assert shade.covering.get(LIFT.id) == halted == lift_now(shade)


async def test_tracking_one_shade_does_not_delay_another(shade) -> None:
    """Shade A's tracking reads hang; shade B's command ends within T_EXEC."""
    quirk = shade.quirk
    at_rest(shade, 79)
    hang_everything(shade)
    start = track(shade, 80)
    await shade.clock.advance(quirk.TRACK_MIN_FIRST_READ_S + 1)
    assert read_times(shade, start) == [5.0]  # unanswered; its retry is due
    other = covering_of(shade.app, OTHER_IEEE)

    result, elapsed = await shade.outcome(
        other.go_to_lift_percentage(80), within=quirk.T_EXEC
    )

    assert_success(result)
    assert elapsed <= shade.motor.reply_latency + JITTER_S
    assert shade.commands(OTHER_NWK) == [(GO_TO.name, 80)]
    await shade.clock.advance(quirk.READ_TIMEOUT + quirk.READ_RETRY_DELAY)
    assert len(read_times(shade, start)) == 2  # shade A's tracking went on
    assert any(str(SHADE_IEEE) in task.get_name() for task in tracking_tasks())


async def test_normal_tracking_logs_nothing_above_debug(shade, caplog) -> None:
    """Settling on target and on a stall logs at DEBUG only."""
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    at_rest(shade, 40)
    shade.motor.start_moving(60, shade.clock.time())
    track(shade, 60)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)
    shade.motor.stall_at = 20
    shade.motor.start_moving(0, shade.clock.time())
    track(shade, 0)
    await shade.clock.advance(shade.quirk.TRACK_MAX_DURATION)

    records = [r for r in caplog.records if r.name == QUIRK_MODULE]
    assert [r for r in records if r.levelno > logging.DEBUG] == []
    assert sum("final lift" in r.getMessage() for r in records) == 2


async def test_shutdown_cancels_tracking_and_the_re_read(shade) -> None:
    """Shutting zigpy down (HA stop, ZHA reload) leaves nothing behind."""
    quirk = shade.quirk
    errors: list[dict] = []
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        await abandon(shade)
        assert tracking_tasks()  # the deferred re-read
        track(shade, 30)
        await shade.clock.advance(0)
        assert len(tracking_tasks()) == 1  # a new tracking replaced the re-read
        frames = len(shade.app.frames)

        await shade.app.shutdown()
        await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)
    finally:
        loop.set_exception_handler(None)

    assert tracking_tasks() == []
    assert len(shade.app.frames) == frames
    assert errors == []


# --- Late starts, removed devices, shutdown mid-delivery ---------------------------


async def test_a_late_start_on_a_short_move_is_not_missed(shade, caplog) -> None:
    """A 40 -> 50 move that starts 100 s late ends at 50, not at the unmoved 40.

    The read at the arrival estimate shows no travel, so the frame is re-sent; the
    motor's pending start is unchanged by it. A reading still at 40 after that is no
    end: the next waits for the last slot, and the shade's report ends the wait.
    """
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.start_delay = 100

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(50), within=quirk.T_EXEC
    )
    assert_success(result)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert shade.commands() == [(GO_TO.name, 50)] * 2
    assert shade.covering.get(LIFT.id) == 50
    assert warnings_of(caplog) == []
    assert tracking_tasks() == []


async def test_a_later_start_is_caught_by_the_deferred_re_read(shade, caplog) -> None:
    """No report, a start after both readbacks: one WARNING, then the re-read finds it."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.reports = False
    shade.motor.start_delay = 2 * quirk.TRACK_MAX_DURATION + 30

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(50), within=quirk.T_EXEC
    )
    assert_success(result)
    await shade.clock.advance(2 * quirk.TRACK_MAX_DURATION)
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT
    [warning] = warnings_of(caplog)
    assert "no travel seen" in warning.getMessage()

    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY)

    assert shade.covering.get(LIFT.id) == 50


async def test_a_report_after_readback_gave_up_still_shows_the_end(
    shade, caplog
) -> None:
    """A start after both readbacks: the shade's own report shows the end, unread."""
    quirk = shade.quirk
    shade.motor.start_delay = 2 * quirk.TRACK_MAX_DURATION + 30

    await shade.outcome(shade.covering.go_to_lift_percentage(50), within=quirk.T_EXEC)
    await shade.clock.advance(2 * quirk.TRACK_MAX_DURATION + 40)
    reads = len(read_times(shade, 0))

    assert len(warnings_of(caplog)) == 1
    assert shade.covering.get(LIFT.id) == 50
    assert shade.baseline() == 50
    assert len(read_times(shade, 0)) == reads


async def test_a_shade_that_never_moves_is_never_called_final(shade, caplog) -> None:
    """A stuck shade: one re-send, and no final position is claimed."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.ignore_commands = True

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(80), within=quirk.T_EXEC
    )
    assert_success(result)
    finished = shade.clock.time()
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)

    messages = [r.getMessage() for r in caplog.records if r.name == QUIRK_MODULE]
    assert not any("final lift" in message for message in messages)
    [warning] = warnings_of(caplog)
    assert "no travel seen" in warning.getMessage()
    assert shade.covering.get(LIFT.id) == INITIAL_LIFT
    assert shade.commands() == [(GO_TO.name, 80)] * 2
    # The arrival read, the re-send, arrival and last-slot reads, then the re-read.
    assert len(read_times(shade, finished)) == 4
    assert tracking_tasks() == []


async def test_a_removed_shade_is_no_longer_read(shade) -> None:
    """Removing one shade cancels its tracking at once: no further frames."""
    quirk = shade.quirk
    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(100), within=quirk.T_EXEC
    )
    assert_success(result)
    assert tracking_tasks()
    removed = shade.clock.time()

    await shade.app.remove(SHADE_IEEE)
    await shade.clock.advance(0)
    assert tracking_tasks() == []
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)

    assert read_times(shade, removed) == []
    assert shade.wire(OTHER_NWK) == []


async def test_a_replaced_shade_is_no_longer_read(shade) -> None:
    """A re-interview tears the old device down: its tracking stops at once."""
    quirk = shade.quirk
    await abandon(shade)
    assert tracking_tasks()  # the deferred re-read
    replaced = shade.clock.time()

    # What zigpy's re-interview does to the device it replaces.
    shade.app.get_device(SHADE_IEEE).on_remove()
    await shade.clock.advance(0)
    assert tracking_tasks() == []
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)

    assert read_times(shade, replaced) == []


async def test_a_shutdown_during_delivery_starts_no_tracking(shade) -> None:
    """Shutting zigpy down mid-delivery: the delivery's finish starts nothing."""
    quirk = shade.quirk
    shade.motor.ignore_commands = True
    delivery = asyncio.ensure_future(shade.covering.go_to_lift_percentage(80))
    await shade.clock.advance(1)

    await shade.app.shutdown()
    await shade.clock.run(delivery, limit=quirk.T_EXEC)
    await shade.clock.advance(0)
    finished = shade.clock.time()

    assert tracking_tasks() == []
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)
    assert read_times(shade, finished) == []


# --- Removal during delivery, unknown start lift -----------------------------------


async def test_a_removal_during_delivery_starts_no_tracking(shade) -> None:
    """remove() mid-delivery: its finish starts no tracker, no re-read, no frame.

    zigpy announces device_removed at once and pops the device only after its leave
    request, up to 30 s later, so the finish still finds the device registered.
    """
    quirk = shade.quirk
    delivery = asyncio.ensure_future(shade.covering.go_to_lift_percentage(80))
    await shade.clock.advance(1)

    await shade.app.remove(SHADE_IEEE)
    await shade.clock.run(delivery, limit=quirk.T_EXEC)
    await shade.clock.advance(0)
    finished = shade.clock.time()

    assert tracking_tasks() == []
    await shade.clock.advance(quirk.DEFERRED_REREAD_DELAY + 600)
    assert read_times(shade, finished) == []


async def test_an_unknown_start_lift_landing_short_ends_quietly(shade, caplog) -> None:
    """No baseline, and the shade settles one point short: its final lift, no WARNING.

    Two equal readings within AT_TARGET_TOLERANCE of the target end tracking even
    with the start unknown, as after a restart.
    """
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    at_rest(shade, 10)
    shade.covering.update_attribute(LIFT.id, None)
    shade.motor.stall_at = 49

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(50), within=quirk.T_EXEC
    )
    assert_success(result)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert shade.covering.get(LIFT.id) == 49
    assert shade.commands() == [(GO_TO.name, 50)]  # within tolerance: no re-send
    # No movement was seen, so the end shown is no baseline.
    assert shade.baseline() is None
    assert warnings_of(caplog) == []
    assert tracking_tasks() == []


async def test_a_still_shade_near_its_target_ends_quietly_but_is_no_baseline(
    shade, caplog
) -> None:
    """49 toward 52 never moves during readback: a quiet end, and no baseline.

    The shade then starts late and reaches 52. Had the still 49 been the baseline,
    that old move would pass for a go-to 90 whose first frame is lost.
    """
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    at_rest(shade, 49)
    shade.motor.reports = False  # no report of the late end reaches the hub
    shade.motor.start_delay = 20
    delivery, _ = go_to(shade, 52)
    result, _ = await shade.outcome(delivery, within=quirk.T_EXEC)
    assert_success(result)
    await shade.clock.advance(30)

    assert tracking_tasks() == []
    assert warnings_of(caplog) == []
    assert shade.covering.get(LIFT.id) == 49
    assert shade.baseline() is None
    shade.motor.start_delay = 0
    shade.motor.ignore_next(1)
    second, frame = go_to(shade, 90)
    result, _ = await shade.outcome(second, within=quirk.T_EXEC)
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands()[-2:] == [frame, frame]
    assert lift_now(shade) == 90


async def test_a_short_landing_after_seen_travel_is_the_next_baseline(
    shade, caplog
) -> None:
    """40 toward 80 stalls at 78 after travel was seen: quiet end and baseline 78."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.motor.stall_at = 78
    delivery, _ = go_to(shade, 80)
    result, _ = await shade.outcome(delivery, within=quirk.T_EXEC)
    assert_success(result)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION)

    assert shade.covering.get(LIFT.id) == 78
    assert shade.baseline() == 78
    assert warnings_of(caplog) == []


async def test_an_unknown_start_lift_does_not_hide_a_late_start(shade, caplog) -> None:
    """No cached lift: equal readings at 40 do not end a move that starts late."""
    quirk = shade.quirk
    caplog.set_level(logging.DEBUG, logger=QUIRK_MODULE)
    shade.covering.update_attribute(LIFT.id, None)
    shade.motor.start_delay = 100

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(50), within=quirk.T_EXEC
    )
    assert_success(result)
    await shade.clock.advance(quirk.TRACK_MAX_DURATION + quirk.DEFERRED_REREAD_DELAY)

    assert shade.covering.get(LIFT.id) == 50
    assert tracking_tasks() == []


# --- The firmware's double reply and the commands it mangles ----------------------

ORDERS = ["success-first", "unsup-first"]
# What the cluster calls for each movement command (open, close, go-to), and the
# frame it sends.
MOVEMENTS = {
    "open": (("up_open", ()), ("up_open",)),
    "close": (("down_close", ()), ("down_close",)),
    "go-to": (("go_to_lift_percentage", (80,)), (GO_TO.name, 80)),
}


@pytest.mark.parametrize("baseline", [True, False], ids=["baseline", "no-baseline"])
@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("movement", list(MOVEMENTS))
async def test_a_movement_ignores_the_second_reply(
    shade, order, movement, baseline
) -> None:
    """The firmware's 0x81 is no failure and no re-send: one frame, SUCCESS."""
    if not baseline:
        shade.covering.update_attribute(LIFT.id, None)
    shade.motor.double_reply = order
    (method, args), frame = MOVEMENTS[movement]

    result, _ = await shade.outcome(
        getattr(shade.covering, method)(*args), within=shade.quirk.T_EXEC
    )
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands() == [frame]


@pytest.mark.parametrize("order", ORDERS)
async def test_an_unverified_go_to_ignores_the_second_reply(shade, order) -> None:
    """A go-to without a valid lift is sent once; its 0x81 is no failure either."""
    shade.motor.double_reply = order

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(255), within=shade.quirk.SEND_TIMEOUT
    )
    await shade.clock.advance(1)  # the second reply lands

    assert_success(result)
    assert shade.commands() == [(GO_TO.name, 255)]


async def test_a_lone_0x81_reports_acceptance_not_movement(started_shade) -> None:
    """No baseline, the SUCCESS lost, a motor that never moves: SUCCESS at once.

    Delivery reads no position, so its result says only that the radio took a frame;
    the radio's replies carry no motor state. The readback judges movement later and
    re-sends once.
    """
    shade = started_shade
    shade.motor.double_reply = "unsup-only"
    shade.motor.ignore_commands = True

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(80), within=shade.quirk.T_EXEC
    )

    assert_success(result)
    assert shade.wire() == [(GO_TO.name, 80)]  # no position read
    await shade.clock.advance(SETTLED_S)
    assert shade.commands() == [(GO_TO.name, 80)] * 2
    assert lift_now(shade) == INITIAL_LIFT


async def test_a_lone_0x81_on_the_targetless_path_reports_acceptance(shade) -> None:
    """A go-to without a valid lift is still a go-to the radio handles: same mapping."""
    shade.motor.double_reply = "unsup-only"

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(255), within=shade.quirk.SEND_TIMEOUT
    )

    assert_success(result)
    assert shade.wire() == [(GO_TO.name, 255)]


MANUFACTURER_SPECIFIC_MOVEMENTS = {
    "open": (WindowCovering.ServerCommandDefs.up_open.id, ()),
    "close": (WindowCovering.ServerCommandDefs.down_close.id, ()),
    "go-to": (GO_TO.id, (80,)),
    "go-to-unknown-lift": (GO_TO.id, (255,)),
}


@pytest.mark.parametrize("baseline", [True, False], ids=["verified", "blind"])
@pytest.mark.parametrize("movement", list(MANUFACTURER_SPECIFIC_MOVEMENTS))
async def test_a_manufacturer_specific_movement_is_refused_unsent(
    started_shade, baseline, movement
) -> None:
    """The radio refuses every manufacturer-specific Window Covering frame unforwarded.

    So sending one is pointless: the quirk refuses it at once, as the radio would,
    with UNSUP_CLUSTER_COMMAND. Nothing is sent, no lock is waited for or taken, and
    tracking and the baseline are left alone, on every delivery path.
    """
    shade = started_shade
    if baseline:
        shade.covering.update_attribute(LIFT.id, INITIAL_LIFT)
    before = shade.baseline()
    recorder = HookRecorder(shade.covering)
    await shade.covering._command_lock.acquire()
    command_id, args = MANUFACTURER_SPECIFIC_MOVEMENTS[movement]

    result, _ = await shade.outcome(
        shade.covering.command(command_id, *args, manufacturer=0x1002),
        within=JITTER_S,
    )
    await shade.clock.advance(1)

    assert isinstance(result, foundation.DefaultResponse), result
    assert (result.command_id, result.status) == (
        command_id,
        foundation.Status.UNSUP_CLUSTER_COMMAND,
    )
    assert shade.app.frames == []
    assert recorder.calls == []
    assert shade.baseline() == before


async def test_a_raw_manufacturer_specific_movement_request_is_refused(shade) -> None:
    """A raw request() for a manufacturer-specific movement is refused too."""
    result, _ = await shade.outcome(
        shade.covering.request(False, GO_TO.id, GO_TO.schema, 80, manufacturer=0x1002),
        within=JITTER_S,
    )

    assert result.status is foundation.Status.UNSUP_CLUSTER_COMMAND
    assert shade.app.frames == []


async def test_a_manufacturer_specific_stop_is_passed_through(shade) -> None:
    """Stop keeps its pass-through: sent once, the radio's genuine 0x81 comes back.

    The radio refuses a manufacturer-specific frame without forwarding it, so
    this 0x81 is a real refusal and is not reported as SUCCESS.
    """
    result, _ = await shade.outcome(
        shade.covering.stop(manufacturer=0x1002), within=shade.quirk.SEND_TIMEOUT
    )

    assert result.status is foundation.Status.UNSUP_CLUSTER_COMMAND
    assert [f.manufacturer for f in shade.app.frames] == [0x1002]


async def test_a_movement_without_travel_is_re_sent_whatever_the_reply(shade) -> None:
    """The replies never decide whether a movement took effect: no travel, a re-send."""
    shade.motor.double_reply = "success-first"
    shade.motor.ignore_next(1)

    result, _ = await shade.outcome(
        shade.covering.go_to_lift_percentage(80), within=shade.quirk.T_EXEC
    )
    await shade.clock.advance(SETTLED_S)

    assert_success(result)
    assert shade.commands() == [(GO_TO.name, 80)] * 2
    assert lift_now(shade) == 80


COMMANDS_REFUSED = [
    ("go_to_lift_value", (1000,)),
    ("go_to_tilt_value", (1000,)),
    ("go_to_tilt_percentage", (30,)),
]


@pytest.mark.parametrize(
    ("command", "args"), COMMANDS_REFUSED, ids=[c for c, _ in COMMANDS_REFUSED]
)
async def test_mangled_commands_are_refused_unsent(shade, command, args) -> None:
    """0x04, 0x07 and 0x08 never reach the air: a device's unsupported-command reply.

    The radio turns them into malformed serial frames. The refusal takes
    no lock, cancels no tracking and keeps the baseline, even while the shade is busy.
    """
    recorder = HookRecorder(shade.covering)
    await shade.covering._command_lock.acquire()
    command_id = getattr(WindowCovering.ServerCommandDefs, command).id

    result, _ = await shade.outcome(
        getattr(shade.covering, command)(*args), within=JITTER_S
    )
    await shade.clock.advance(1)

    assert isinstance(result, foundation.DefaultResponse), result
    assert (result.command_id, result.status) == (
        command_id,
        foundation.Status.UNSUP_CLUSTER_COMMAND,
    )
    assert shade.app.frames == []
    assert recorder.calls == []
    assert shade.baseline() == INITIAL_LIFT


@pytest.mark.parametrize(
    ("command", "args"), COMMANDS_REFUSED, ids=[c for c, _ in COMMANDS_REFUSED]
)
async def test_mangled_commands_are_refused_on_every_send_path(
    shade, command, args
) -> None:
    """A raw request for a mangled command is refused too: nothing bypasses it."""
    definition = getattr(WindowCovering.ServerCommandDefs, command)

    result, _ = await shade.outcome(
        shade.covering.request(False, definition.id, definition.schema, *args),
        within=JITTER_S,
    )

    assert result.status is foundation.Status.UNSUP_CLUSTER_COMMAND
    assert shade.app.frames == []
