# Installed by the SmartWings integration for Home Assistant, which keeps this file up to date. Delete this line to keep the file as your own.
"""Device handler for SmartWings WM25/L-Z roller shades.

This file sits at upstream's path (``zhaquirks/smartwings/wm25lz.py``) inside ``quirk/``,
which is never on the import path, so it cannot shadow the installed zhaquirks library.
It goes upstream as-is. To use it before release, copy this one file into the directory
ZHA's ``custom_quirks_path`` names; do not point ``custom_quirks_path`` at ``quirk/``. It
must not import Home Assistant.

Delivery
--------
Commands go out as ZHA sends them: open is ``up_open``, close is ``down_close`` and a
position is ``go_to_lift_percentage`` with ZHA's lift. The motor scales positions
between the limits set with its remote and stops every movement at them, so lift 100 is
the lower limit (Part 1 §3a). The released quirk swaps ``up_open`` and ``down_close``;
these units need no swap (Part 1 §3c), so none is made.

These motors sometimes ignore the first frame after idling while an identical re-send
works (Part 1 §3e; how often is unknown), and reads are lost the same way. The radio answers a read of the lift from its own copy, which changes only when
the motor sends a position, and the motor sends one only when travel ends: at its target,
where it stalls, or on a Stop. Then the radio also pushes that position to the
coordinator as an attribute report (Part 1 §3f; firmware analysis §4). A read during travel
returns the lift from before the move, so no read taken mid-travel says whether the shade
moves. Every WindowCovering command goes through two steps on the cluster:

1. ``_translate()`` turns it into a ``WireCommand``: the frame to send, unchanged, and
   the lift (ZCL space: 0 open, 100 closed) it should reach, or None when it has no lift
   target (Stop).
2. ``_deliver()`` sends the wire command once, as the stock quirk does, and returns the
   radio's reply (for a movement, as "Firmware replies" reports it). A frame lost on the
   air (a delivery error or timeout) is sent again once, ``SEND_RETRY_DELAY`` later, as a
   read is; if both are lost, the command fails like any failed command: a Default
   Response with status FAILURE, logged at DEBUG. Nothing is read: the command returns
   as soon as the radio has answered, and its SUCCESS reports the radio's acceptance of
   the frame, not movement.

Whether a movement took effect is judged afterwards, by the position readback (below),
when travel should be over: if by then neither a report nor a read shows travel toward
the target, the identical frame is re-sent once, the workaround for a first frame the
motor ignored, and the readback starts again. Re-sending the same target is harmless: a
duplicate go-to moves the shade once (Part 1 §3f). The re-send is one frame, never
retried. Nothing is re-sent after a command that did not get a SUCCESS; the command has
returned by then, so a re-send that fails is only logged. A Stop cancels everything
pending for the shade: it moves the shade's generation on, and every retry and re-send
checks the generation just before it is sent. A movement issued before a Stop but still
waiting for the shade's lock is dropped unsent and answered SUCCESS: the user's later
Stop is what the shade does. A Stop during a movement's delivery means no readback
follows that movement; after any Stop the quirk waits ``STOP_SETTLE_S`` for the shade's
report of where it halted, and reads the lift once if none comes.

The baseline is the lift last received from the shade, by a read or a report, since
this cluster was created at startup or ZHA reload: a lift restored from zigpy's
database may predate a move made with the remote. Sending a movement retires it, since
the shade may travel from then on. A lift received becomes the baseline again only at
the command's target, or when readback ends travel on two equal readings after seeing
the shade move ``MOVED_TOLERANCE`` from its baseline: a shade standing still near its
target may yet start late, so that end is shown but is no baseline. After readback
ends that way or gives up, only a read or refresh of the exact target restores one; a
lift received during travel is none. The readback judges travel from the baseline; with
none, only a lift within ``AT_TARGET_TOLERANCE`` of the target shows it.

Firmware replies
----------------
The radio answers each Window Covering command it handles (0x00, 0x01, 0x02, 0x04,
0x05, 0x07, 0x08) twice, with one TSN: a Default Response SUCCESS, then
UNSUP_CLUSTER_COMMAND (0x81); 0x03, 0x06 and unknown ones get only the 0x81. zigpy
returns whichever arrives first (firmware analysis §3; session A saw both for Stop).
Neither reply carries the motor's state. For an open, close, go-to or Stop sent as the
standard frame, the 0x81 only means the radio took the frame and forwarded it, as the
SUCCESS does, so delivery counts it as an answer, never as a failure or a reason to
re-send, and reports SUCCESS (``_forwarded_reply()``): ZHA's cover raises on any other
status. The radio refuses every manufacturer-specific Window Covering frame with a
genuine 0x81 and forwards nothing (firmware analysis §2), so a manufacturer-specific
open, close or go-to is refused before sending, as below; every movement frame that
goes out is standard. A manufacturer-specific Stop is passed through with its genuine
0x81. No movement reads anything before it returns, so its SUCCESS reports the radio's
acceptance of a frame, not movement; the readback judges movement later. Stop is
sent once, never synthesised from a read: the motor halts on it (Part 1 §3d), and it
drops a pending re-send.

The radio turns ``go_to_lift_value`` (0x04), ``go_to_tilt_value`` (0x07) and
``go_to_tilt_percentage`` (0x08) into malformed serial frames that can repeat the
previous command or corrupt the next (firmware analysis §3 note 3). They are refused
before anything is sent, by any path, with the Default Response a device gives for a
command it does not support, UNSUP_CLUSTER_COMMAND, which ZHA reports as for any such
command; so is a manufacturer-specific open, close or go-to. A refusal takes no lock
and leaves tracking and the baseline alone.

Movement commands on one shade are serialised by the cluster's lock; a command that
cannot get it within ``LOCK_WAIT`` fails the same way, unsent. Delivery's own frames
never take the lock again. Each movement command has a ``RadioBudget`` of
``RADIO_BUDGET`` frames and read attempts, which it shares with the position readback
that follows the shade's travel afterwards (see "Position readback"). A spent budget
also fails the command with FAILURE. Every read, ``read_attributes`` included, and every
movement frame is retried once after a lost attempt, and zigpy's own retries are off, so
every request is one frame.

Position readback
-----------------
A command returns once the radio has answered, at the start of a 30-70 s travel, so the
position shown is the one from before it. After each movement command, success or
failure, ``_on_movement_finished()`` starts a tracker for the shade that waits for the
end of travel:

* the shade's report of its lift is the signal: the motor sends its position when travel
  ends, and the radio pushes it (Part 1 §3f). Only a report wakes the tracker; it takes no
  read for it;
* without a report, the lift is read at the estimated arrival, the distance left from
  the raw lift last known since startup (full travel if none) as a share of
  ``FULL_TRAVEL_S``, plus ``ARRIVAL_MARGIN_S``, never before
  ``TRACK_MIN_FIRST_READ_S``;
* the first lift so seen decides the re-send (see "Delivery"): if it is more than
  ``AT_TARGET_TOLERANCE`` from the target and shows no travel toward it from the
  baseline (with none, any lift away from the target), the frame is re-sent once and
  the tracker starts again, judging travel from that lift, with its bounds renewed;
* travel has ended when a lift seen equals the command's raw target, or equals the
  previous one once the shade has been seen to move (``MOVED_TOLERANCE`` from
  its baseline before the command) or stands within ``AT_TARGET_TOLERANCE`` of the
  target, where a go-to lands; otherwise a confirming reading follows
  ``CONFIRM_GAP_S`` later, and while readings still differ, one more at the new
  estimated arrival. A shade still where it started, away from the target, may start
  late (Part 1 §3h), so after such a reading the next waits for the last slot that fits
  before ``TRACK_MAX_DURATION``, and a report ends that wait;
* at most ``TRACK_MAX_READINGS`` reads, all within ``TRACK_MAX_DURATION``, before and
  again after the re-send, each charged to the command's budget, of which tracking
  takes at most ``TRACKING_MAX_OPS``. If the end is not seen, one WARNING names the
  shade and one more read follows ``DEFERRED_REREAD_DELAY`` later while budget is left.

Each reading is written to the cache with ``update_attribute``, so ZHA sees a fresh
position; a report reaches the cache through zigpy, as for any device. The cache holds
the lift as the shade sent it: ZHA's ``100 - lift`` is the only conversion. The tracker
compares lifts only. It never takes the shade's lock. A new movement command cancels it,
any pending re-read and the pending re-send, through ``_cancel_tracking()`` before it
waits for the lock; Stop cancels only the re-send. Tracking runs as tasks of the zigpy
application, which cancels them when it shuts down (Home Assistant stop, ZHA reload). It also stops, and none starts,
once the shade's zigpy device is torn down (shutdown, re-interview) or removed. There
is no polling: a move made with the remote shows when the shade reports it, or after a
refresh (``homeassistant.update_entity``), which reads through the read retry.

Worst-case durations, in seconds, from the constants below::

    T_EXEC    SEND_ATTEMPTS * SEND_TIMEOUT + SEND_RETRY_DELAY   12.5  movement command
    T_PASS    SEND_TIMEOUT                                       5.0  command without a lift target
    T_QUEUED  LOCK_WAIT + T_EXEC                                25.0  command queued behind another
    T_READ    2 * READ_TIMEOUT + READ_RETRY_DELAY                6.5  one reading, with its retry

Tracking never delays a command: it ends within ``TRACK_MAX_DURATION`` (120 s) of the
command's end, or of its re-send, which follows within ``TRACK_MAX_DURATION``; or
``DEFERRED_REREAD_DELAY + T_READ`` after that with a re-read.
"""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
import functools
import logging
from typing import Any, Final

from zhaquirks import DoublingPowerConfigurationCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zigpy.exceptions import DeliveryError, ZigbeeException
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

_LOGGER = logging.getLogger(__name__)

# ZCL lift percentage: 0 = fully open (the remote's upper limit), 100 = fully closed
# (its lower limit). Every position in this module is a lift in this space.
ATTR_LIFT: Final = WindowCovering.AttributeDefs.current_position_lift_percentage
CMD_UP_OPEN: Final = WindowCovering.ServerCommandDefs.up_open.id
CMD_DOWN_CLOSE: Final = WindowCovering.ServerCommandDefs.down_close.id
CMD_GO_TO_LIFT: Final = WindowCovering.ServerCommandDefs.go_to_lift_percentage.id
CMD_STOP: Final = WindowCovering.ServerCommandDefs.stop.id
# Commands that can move the shade: each waits for the shade's lock, then is translated.
MOVEMENT_COMMANDS: Final = frozenset({CMD_UP_OPEN, CMD_DOWN_CLOSE, CMD_GO_TO_LIFT})
# Commands the radio turns into malformed serial frames, which can repeat the previous
# command or corrupt the next (firmware analysis §3): refused, never sent.
REFUSED_COMMANDS: Final = frozenset(
    {
        WindowCovering.ServerCommandDefs.go_to_lift_value.id,
        WindowCovering.ServerCommandDefs.go_to_tilt_value.id,
        WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id,
    }
)
LIFT_OPEN: Final = 0
LIFT_CLOSED: Final = 100

# The quirk ID, declared through ZHA's exposed features: ZHA lists it in the device's
# ``exposes_features``, which is how an integration tells this quirk is loaded.
QUIRK_ID: Final = "smartwings.wm25lz"

# Timing, in seconds.
SEND_TIMEOUT: Final = 5.0  # bound on one frame send, whatever zigpy's own timeout is
SEND_ATTEMPTS: Final = 2  # a frame and its single re-send after it was lost
SEND_RETRY_DELAY: Final = 2.5  # gap before re-sending a lost frame
READ_TIMEOUT: Final = 2.5  # bound on one read attempt; answered reads take under 2 s
READ_RETRY_DELAY: Final = 1.5  # gap before the single read retry
READ_ATTEMPTS: Final = 2  # a read and its single retry

# Lift points.
MOVED_TOLERANCE: Final = 2  # change from the baseline that counts as travel
# Distance from the target that counts as "already there".
AT_TARGET_TOLERANCE: Final = 3

# Worst-case durations.
T_EXEC: Final = (
    SEND_ATTEMPTS * SEND_TIMEOUT + (SEND_ATTEMPTS - 1) * SEND_RETRY_DELAY
)  # a movement command
T_PASS: Final = SEND_TIMEOUT  # a command without a target lift
LOCK_WAIT: Final = T_EXEC  # longest wait for a shade busy with another command
T_QUEUED: Final = LOCK_WAIT + T_EXEC  # a command queued behind another
T_READ: Final = READ_ATTEMPTS * READ_TIMEOUT + (READ_ATTEMPTS - 1) * READ_RETRY_DELAY

# Following travel after a movement command, in seconds unless noted. Every read costs
# a sleepy end device battery, so the lift is read only when travel should be over.
FULL_TRAVEL_S: Final = 70.0  # slowest measured full travel (Part 1 §4)
ARRIVAL_MARGIN_S: Final = 3.0  # slack past the estimated arrival
TRACK_MIN_FIRST_READ_S: Final = 5.0  # never sooner than ZHA's own movement timeout
CONFIRM_GAP_S: Final = 5.0  # gap to the reading that confirms the shade has stopped
# Reads, before and again after a re-send: arrival, confirmation, one more.
TRACK_MAX_READINGS: Final = 3
# Cap from the start, and again from a re-send; ~1.7x the longest travel.
TRACK_MAX_DURATION: Final = 120.0
# Wait after a Stop for the shade's report of where it halted, before reading it once.
STOP_SETTLE_S: Final = 3.0
# ZHA's LIFT_MOVEMENT_TIMEOUT_RANGE: one read this long after tracking gave up.
DEFERRED_REREAD_DELAY: Final = 300.0

# Radio operations (frames sent plus read attempts) per movement command. These are
# battery-powered sleepy end devices, so every frame costs. Delivery never needs more
# than DELIVERY_MAX_OPS; the rest is left for following travel afterwards, which never
# needs more than TRACKING_NEEDED_OPS: its reads before and after the re-send, the
# re-send, and the deferred re-read.
RADIO_BUDGET: Final = 25
DELIVERY_MAX_OPS: Final = SEND_ATTEMPTS
TRACKING_MAX_OPS: Final = RADIO_BUDGET - DELIVERY_MAX_OPS
TRACKING_NEEDED_OPS: Final = 2 * TRACK_MAX_READINGS * READ_ATTEMPTS + 1 + READ_ATTEMPTS


def _valid_lift(value: Any) -> int | None:
    """Return ``value`` as a lift percentage, or None if it is not one (255 = unknown)."""
    if isinstance(value, int) and LIFT_OPEN <= value <= LIFT_CLOSED:
        return int(value)
    return None


def _default_response(
    command_id: int, status: foundation.Status
) -> foundation.DefaultResponse:
    """Return a Default Response to ``command_id`` with ``status``, as zigpy decodes one."""
    return foundation.GENERAL_COMMANDS[
        foundation.GeneralCommand.Default_Response
    ].schema(command_id=command_id, status=status)


@dataclass(frozen=True)
class WireCommand:
    """One WindowCovering command as it goes on the wire.

    ``target_lift`` is the raw lift the motor should travel toward, or None for a
    command that is passed through once, unverified (Stop and anything else).
    """

    command_id: int
    args: tuple[Any, ...]
    target_lift: int | None


class _RemovalWatch:
    """A zigpy application listener that reports the removal of one device."""

    def __init__(self, device: Any, on_removed: Callable[[], None]) -> None:
        """Watch ``device``; call ``on_removed`` when the application removes it."""
        self._device = device
        self._on_removed = on_removed

    def device_removed(self, device: Any) -> None:
        """Handle zigpy's ``device_removed`` event, for any device."""
        if device is self._device:
            self._on_removed()


class RadioBudgetSpentError(ZigbeeException):
    """A movement command has spent its radio budget; nothing more may be sent for it."""


class RadioBudget:
    """The radio operations one movement command may spend: frames sent, read attempts.

    Delivery and the position tracking that follows it draw from the same budget.
    """

    def __init__(self, limit: int = RADIO_BUDGET) -> None:
        """Start with nothing spent."""
        self.limit = limit
        self.frames = 0
        self.reads = 0

    @property
    def used(self) -> int:
        """Return the operations spent so far."""
        return self.frames + self.reads

    @property
    def remaining(self) -> int:
        """Return the operations left."""
        return self.limit - self.used

    def take(self, *, read: bool) -> bool:
        """Spend one operation if any is left; return whether one was."""
        if self.remaining <= 0:
            return False
        if read:
            self.reads += 1
        else:
            self.frames += 1
        return True


# The budget of the movement command being delivered in the current task, if any.
_RADIO_BUDGET: ContextVar[RadioBudget | None] = ContextVar(
    "smartwings_radio_budget", default=None
)
# What _acquire_command_lock returns for a movement a later Stop superseded.
_STOPPED: Final = -1
# Set while zigpy handles a Report Attributes the shade pushed.
_IN_REPORT: ContextVar[bool] = ContextVar("smartwings_in_report", default=False)


def _busy() -> str:
    """Return why a movement that never got the shade's lock was not sent."""
    return f"busy with another command for {LOCK_WAIT:g} s; not sent"


def _arrival_delay(lift: int | None, target: int) -> float:
    """Return the seconds until a shade at ``lift`` should have reached ``target``.

    That is the distance as a share of full travel times FULL_TRAVEL_S, plus
    ARRIVAL_MARGIN_S; an unknown lift counts as full travel.
    """
    distance = LIFT_CLOSED if lift is None else abs(target - lift)
    return distance / LIFT_CLOSED * FULL_TRAVEL_S + ARRIVAL_MARGIN_S


def _moved_from(origin: int | None, lift: int | None) -> bool:
    """Return whether ``lift`` is at least MOVED_TOLERANCE from a known ``origin``."""
    return (
        origin is not None
        and lift is not None
        and abs(lift - origin) >= MOVED_TOLERANCE
    )


def _travel_ended(lift: int, previous: int | None, target: int, moved: bool) -> bool:
    """Return whether reading ``lift`` after ``previous`` ends travel toward ``target``.

    It does at the target, or at the previous reading once the shade has been seen
    to move (``moved``) or stands within AT_TARGET_TOLERANCE of the target, where a
    go-to lands. Equal readings anywhere else may be a shade yet to start (Part 1
    §3h), which a start lift that is not known cannot tell apart. This decides what
    is shown as final; whether it is also a baseline is decided by the caller.
    """
    if lift == target:
        return True
    return lift == previous and (moved or abs(lift - target) <= AT_TARGET_TOLERANCE)


def _moved_toward(baseline: int, lift: int, target: int) -> bool:
    """Return whether ``lift`` is travel from ``baseline`` toward ``target``."""
    return abs(lift - baseline) >= MOVED_TOLERANCE and (lift > baseline) == (
        target > baseline
    )


def _needs_resend(origin: int | None, lift: int, target: int) -> bool:
    """Return whether ``lift``, seen once travel should be over, calls for a re-send.

    It does unless it lies within AT_TARGET_TOLERANCE of ``target`` or shows travel
    toward it from a known ``origin``; with none, nothing else shows travel.
    """
    if abs(lift - target) <= AT_TARGET_TOLERANCE:
        return False
    return origin is None or not _moved_toward(origin, lift, target)


class WM25LZWindowCovering(CustomCluster, WindowCovering):
    """WindowCovering for the WM25/L-Z."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Create the cluster with its own command lock: one per shade."""
        super().__init__(*args, **kwargs)
        self._command_lock = asyncio.Lock()
        # Counts movement commands that got the lock; a finish hook runs only for the
        # newest, so a superseded command never starts tracking.
        self._generation = 0
        # The lift last received from the shade since startup. It is delivery's
        # baseline only while _raw_lift_is_baseline (see _cached_lift_raw).
        self._raw_lift: int | None = None
        self._raw_lift_is_baseline = False
        # Whether a lift received now may be a baseline: not from the sending of a
        # movement until a lift received shows its travel ended (see "Delivery").
        self._shade_settled = True
        # The target of a movement readback stopped following without a baseline
        # (gave up, or ended on a still shade): a later read of it restores one.
        self._unseen_end: int | None = None
        # Position readback after the latest movement, and its deferred re-read.
        self._tracking: asyncio.Task[None] | None = None
        self._reread: asyncio.Task[None] | None = None
        # The latest movement's single re-send, until the readback uses or drops it.
        self._resend: Callable[[RadioBudget], Awaitable[None]] | None = None
        # The futures waiting for the shade's next report of its lift.
        self._report_waiters: set[asyncio.Future[int]] = set()
        # Counts Stops: a movement issued before a Stop is dropped, unsent.
        self._stops = 0
        # The read that shows where a Stop halted the shade, if no report does.
        self._stop_read: asyncio.Task[None] | None = None
        # The baseline before the newest movement sent, if there was one.
        self._command_origin: int | None = None
        # Set once the zigpy device is torn down or removed: nothing is tracked then.
        self._device_gone = False
        # zigpy announces a removal when it starts, before it lets go of the device;
        # listened for over the cluster's whole life, so no finish can miss it.
        device = self.endpoint.device
        self._removal_watch: _RemovalWatch | None = _RemovalWatch(
            device, self._on_device_gone
        )
        device.application.add_listener(self._removal_watch)
        # zigpy calls these when it tears the device down: on shutdown (ZHA reload,
        # HA stop) and when a re-interview replaces it. There is no public hook.
        device._on_remove_callbacks.append(self._on_device_gone)

    # ------------------------------------------------------------ translation

    async def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args: Any,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ) -> Any:
        """Translate the command into its wire frame and deliver it.

        A command that can move the shade first waits for the shade's lock, then is
        translated and delivered. Stop and anything else are translated and sent at
        once, without the lock. A command ``_refusal`` names a reason for is answered at
        once, unsent, before any lock or state is touched.
        """
        reason = self._refusal(command_id, manufacturer)
        if reason is not None:
            return self._refuse(command_id, reason)
        send_kwargs = {
            "manufacturer": manufacturer,
            "expect_reply": expect_reply,
            "tsn": tsn,
        }
        if command_id not in MOVEMENT_COMMANDS:
            if command_id != CMD_STOP:
                wire, kwargs = self._translate(command_id, args, kwargs)
                return await self._deliver(wire, **send_kwargs, **kwargs)
            # A shade told to stop must not be moved again: the generation stops a
            # lost frame's retry and the readback's re-send, wherever they wait, and
            # the count drops every movement issued before it that still waits.
            self._resend = None
            self._generation += 1
            self._stops += 1
            # Listen for the shade's report of where it halts before the frame goes out.
            self._after_stop()
            wire, kwargs = self._translate(command_id, args, kwargs)
            return await self._deliver(wire, **send_kwargs, **kwargs)
        generation = await self._acquire_command_lock()
        if generation is None:
            return self._give_up(WireCommand(command_id, args, None), _busy())
        if generation == _STOPPED:
            return self._dropped(WireCommand(command_id, args, None))
        release = True
        try:
            wire, kwargs = self._translate(command_id, args, kwargs)
            if wire.target_lift is None:
                # Nothing to verify (a go-to without a valid lift): sent once, still
                # holding the shade. Its reply reports only that the radio took the
                # frame (see "Firmware replies").
                self._take_baseline()
                return await self._send_movement_frame(wire, **send_kwargs, **kwargs)
            release = False
        finally:
            if release:
                self._command_lock.release()
        return await self._deliver_holding_lock(
            wire, generation, RadioBudget(), {**send_kwargs, **kwargs}
        )

    def _translate(
        self, command_id: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[WireCommand, dict[str, Any]]:
        """Return the frame to send, as ZHA sent it, and the lift it should reach.

        Open is up_open, close is down_close and a go-to keeps ZHA's lift: the motor
        stops each at the limits set with its remote (#54). The released quirk's swap
        of up_open and down_close is not used: raw down_close lowers these units and
        raw up_open raised the one unit tried (Part 1 §3c). The target is lift 0 for
        an open, 100 (the lower limit) for a close and the lift of a go-to; a go-to
        without a valid lift, Stop and anything else have none (REFUSED_COMMANDS never
        reach the air). Return the wire command and the keyword arguments left for
        zigpy.
        """
        if command_id == CMD_UP_OPEN:
            return WireCommand(CMD_UP_OPEN, args, LIFT_OPEN), kwargs
        if command_id == CMD_DOWN_CLOSE:
            return WireCommand(CMD_DOWN_CLOSE, args, LIFT_CLOSED), kwargs
        if command_id != CMD_GO_TO_LIFT:
            return WireCommand(command_id, args, None), kwargs
        if not args and "percentage_lift_value" in kwargs:
            kwargs = dict(kwargs)
            args = (kwargs.pop("percentage_lift_value"),)
        target = _valid_lift(args[0]) if len(args) == 1 else None
        return WireCommand(CMD_GO_TO_LIFT, args, target), kwargs

    # ---------------------------------------------------------- tracking hooks

    def _cancel_tracking(self) -> None:
        """Stop following an earlier command's travel; called before each movement.

        Cancels the tracker, any deferred re-read and the pending re-send without
        waiting for them: each stops at its next await, and a read or frame then in
        flight is abandoned.
        """
        for task in (self._tracking, self._reread, self._stop_read):
            if task is not None:
                task.cancel()
        self._tracking = self._reread = self._stop_read = None
        self._resend = None

    def _on_movement_finished(
        self,
        target_lift: int,
        budget: RadioBudget,
        resend: Callable[[RadioBudget], Awaitable[None]] | None = None,
    ) -> None:
        """Start following travel toward ``target_lift``; called after each movement.

        Called once the shade's lock is released, whether delivery succeeded or failed.
        ``budget`` holds what the command has left for the reads that follow; tracking
        takes at most TRACKING_MAX_OPS of it. ``resend`` sends the command's frame once
        more, for the readback to call if travel does not show; None after a command
        that did not get a SUCCESS.
        """
        self._cancel_tracking()
        device = self.endpoint.device
        if (
            self._device_gone
            or device.application.devices.get(device.ieee) is not device
        ):
            _LOGGER.debug("%s: device gone; not following travel", device.ieee)
            return
        budget.limit = min(budget.limit, budget.used + TRACKING_MAX_OPS)
        self._resend = resend
        self._tracking = self._create_task(
            self._track(target_lift, budget, self._command_origin),
            "position readback",
        )

    def _on_device_gone(self) -> None:
        """Stop tracking for good: the zigpy device was torn down or removed."""
        self._device_gone = True
        self._cancel_tracking()
        if self._removal_watch is not None:
            self.endpoint.device.application.remove_listener(self._removal_watch)
            self._removal_watch = None

    def _create_task(
        self, coro: Coroutine[Any, Any, None], name: str
    ) -> asyncio.Task[None]:
        """Run ``coro`` as a task of the zigpy application, which cancels it on shutdown.

        Not the device's own tasks: zigpy's ``Device.on_remove()`` empties that set
        before the cancelled tasks finish, and each then fails to remove itself.
        """
        device = self.endpoint.device
        return device.application.create_task(coro, name=f"{device.ieee} {name}")

    async def _track(
        self, target: int, budget: RadioBudget, origin: int | None
    ) -> None:
        """Follow travel toward ``target`` until its end is seen; re-send once if none is.

        ``origin`` is the raw lift before the command, or None if unknown. See
        "Position readback" in the module docstring for the schedule and bounds.
        """
        ieee = self.endpoint.device.ieee
        loop = asyncio.get_running_loop()
        start = self._raw_lift
        moved = _moved_from(origin, start)
        delay = max(TRACK_MIN_FIRST_READ_S, _arrival_delay(start, target))
        _LOGGER.debug("%s: following travel toward %s for %.1f s", ieee, target, delay)
        previous: int | None = None
        reason = "unreadable"
        reads = 0
        deadline = loop.time() + TRACK_MAX_DURATION
        try:
            async with asyncio.timeout_at(deadline) as bound:
                while reads < TRACK_MAX_READINGS:
                    # Each read must still fit before the bound.
                    wait = min(delay, deadline - T_READ - loop.time())
                    if wait < 0:
                        break
                    lift = await self._reported_lift(wait)
                    if self._device_gone:
                        return
                    if lift is None:
                        reads += 1
                        lift = await self._read_lift_live(budget)
                        if lift is None:
                            delay = CONFIRM_GAP_S
                            continue
                        self.update_attribute(ATTR_LIFT.id, lift)
                    moved = moved or _moved_from(origin, lift)
                    resend, self._resend = self._resend, None
                    if resend is not None and _needs_resend(origin, lift, target):
                        _LOGGER.debug(
                            "%s: no travel toward %s seen (lift %s); re-sending once",
                            ieee,
                            target,
                            lift,
                        )
                        await resend(budget)
                        # Start again from the lift seen, with the bounds renewed.
                        deadline = loop.time() + TRACK_MAX_DURATION
                        bound.reschedule(deadline)
                        origin, moved, previous, reads = lift, False, None, 0
                        delay = max(
                            TRACK_MIN_FIRST_READ_S, _arrival_delay(lift, target)
                        )
                        continue
                    if _travel_ended(lift, previous, target, moved):
                        if lift == target or moved:
                            self._shade_settled = self._raw_lift_is_baseline = True
                        else:
                            # Still near the target: shown, but it may start late.
                            self._unseen_end = target
                        _LOGGER.debug(
                            "%s: final lift %s (target %s) after %d read(s)",
                            ieee,
                            lift,
                            target,
                            reads,
                        )
                        return
                    _LOGGER.debug("%s: lift %s, target %s", ieee, lift, target)
                    previous = lift
                    if not moved and abs(lift - target) > AT_TARGET_TOLERANCE:
                        # Not started yet: look again as late as the bound allows.
                        delay = TRACK_MAX_DURATION
                        reason = "no travel seen"
                        continue
                    # The first lift seen moving is confirmed CONFIRM_GAP_S later;
                    # after two differing ones, the next is at the new arrival.
                    delay = (
                        CONFIRM_GAP_S
                        if reason != "still moving"
                        else max(CONFIRM_GAP_S, _arrival_delay(lift, target))
                    )
                    reason = "still moving"
        except TimeoutError:
            reason = f"no end after {TRACK_MAX_DURATION:g} s"
        except RadioBudgetSpentError:
            reason = "radio budget spent"
        if self._device_gone:
            return
        # No baseline until a lift received later, by the re-read or a refresh, is
        # the target itself.
        self._unseen_end = target
        rereads = budget.remaining > 0
        _LOGGER.warning(
            "%s: final position toward lift %s not seen (%s); last lift read: %s%s",
            ieee,
            target,
            reason,
            previous,
            f", reading again in {DEFERRED_REREAD_DELAY:g} s" if rereads else "",
        )
        if rereads:
            self._reread = self._create_task(
                self._reread_later(budget), "position readback re-read"
            )

    async def _reported_lift(self, wait: float) -> int | None:
        """Wait up to ``wait`` seconds for the shade to report its lift; return it.

        Return None if no report came. Only a pushed report counts: a read during
        travel answers the lift from before the move (see "Delivery").
        """
        waiter = asyncio.get_running_loop().create_future()
        self._report_waiters.add(waiter)
        try:
            async with asyncio.timeout(wait):
                return await waiter
        except TimeoutError:
            return None
        finally:
            self._report_waiters.discard(waiter)

    async def _reread_later(self, budget: RadioBudget) -> None:
        """Read the lift once, DEFERRED_REREAD_DELAY after tracking gave up."""
        await asyncio.sleep(DEFERRED_REREAD_DELAY)
        if self._device_gone:
            return
        try:
            lift = await self._read_lift_live(budget)
        except RadioBudgetSpentError:
            lift = None
        _LOGGER.debug("%s: deferred lift read: %s", self.endpoint.device.ieee, lift)
        if lift is not None:
            self.update_attribute(ATTR_LIFT.id, lift)

    def _finish_if_newest(
        self,
        generation: int,
        target_lift: int,
        budget: RadioBudget,
        resend: Callable[[RadioBudget], Awaitable[None]] | None,
    ) -> None:
        """Call _on_movement_finished unless a newer command has taken the lock since.

        A queued command takes the lock as soon as this command releases it, before this
        callback runs; its own finish follows. A command that gives up waiting for the
        lock never takes it, so it does not suppress the command it waited behind.
        """
        if generation == self._generation:
            self._on_movement_finished(target_lift, budget, resend)

    @staticmethod
    def _run_hook(hook: Callable[..., None], *args: Any) -> None:
        """Run a tracking hook as an event-loop callback.

        An exception in a hook is then reported by the event loop and cannot change the
        command's result.
        """
        asyncio.get_running_loop().call_soon(hook, *args)

    # ---------------------------------------------------------------- delivery

    async def _deliver(
        self,
        wire: WireCommand,
        *,
        manufacturer: Any = None,
        expect_reply: bool = True,
        tsn: Any = None,
        budget: RadioBudget | None = None,
        **kwargs: Any,
    ) -> Any:
        """Send ``wire`` to the shade and return the reply to report.

        A command without a target lift is sent once and its reply or exception is
        returned unchanged, except that a standard Stop's reply is reported as
        ``_forwarded_reply`` reports it. A command with one waits for the shade's lock,
        then is sent once (again only if the frame was lost), and the readback that
        follows judges whether it took effect. Its frames and reads are charged to ``budget`` (a new
        one by default).
        """
        send_kwargs = {
            "manufacturer": manufacturer,
            "expect_reply": expect_reply,
            "tsn": tsn,
            **kwargs,
        }
        if wire.target_lift is None:
            reply = await self._send_frame(wire, **send_kwargs)
            if wire.command_id == CMD_STOP and manufacturer in (None, UNDEFINED):
                return self._forwarded_reply(wire, reply)
            return reply
        generation = await self._acquire_command_lock()
        if generation is None:
            return self._give_up(wire, _busy())
        if generation == _STOPPED:
            return self._dropped(wire)
        return await self._deliver_holding_lock(
            wire, generation, RadioBudget() if budget is None else budget, send_kwargs
        )

    async def _acquire_command_lock(self) -> int | None:
        """Stop following earlier travel, then wait up to LOCK_WAIT for the shade.

        Return the command's generation once the lock is taken, or None if it was not.
        Every command that takes the lock is the newest from then on, so a command it
        waited behind no longer starts tracking. The caller releases the lock. A Stop
        since the command was issued supersedes it: the lock is released at once and
        _STOPPED returned, so nothing moves the shade after the user's Stop.
        """
        issued = self._stops
        self._run_hook(self._cancel_unless_stopped, issued)
        await asyncio.sleep(0)  # let the cancel run before waiting for the lock
        try:
            async with asyncio.timeout(LOCK_WAIT):
                await self._command_lock.acquire()
        except TimeoutError:
            return None
        if self._stops != issued:
            self._command_lock.release()
            return _STOPPED
        self._generation += 1
        return self._generation

    def _cancel_unless_stopped(self, issued: int) -> None:
        """Run _cancel_tracking() for a movement issued when ``issued`` Stops were sent.

        A Stop since then drops that movement unsent, so it must not cancel anything:
        least of all the read that shows where the Stop halted the shade.
        """
        if self._stops == issued:
            self._cancel_tracking()

    def _dropped(self, wire: WireCommand) -> foundation.DefaultResponse:
        """Answer a movement a later Stop superseded before it was sent: SUCCESS, unsent.

        The user's Stop, sent after it, is what the shade does, so ZHA takes the
        command's stock success path rather than reporting an error for it.
        """
        _LOGGER.debug(
            "%s: %s dropped, unsent: a Stop came after it",
            self.endpoint.device.ieee,
            self.server_commands[wire.command_id].name,
        )
        return _default_response(wire.command_id, foundation.Status.SUCCESS)

    def _after_stop(self) -> None:
        """Show where a Stop halts the shade: wait for its report, else read it once.

        Called as the Stop is sent; the wait counts from then.
        """
        if self._stop_read is not None:
            self._stop_read.cancel()
        device = self.endpoint.device
        if (
            self._device_gone
            or device.application.devices.get(device.ieee) is not device
        ):
            self._stop_read = None
            return
        self._stop_read = self._create_task(self._read_after_stop(), "stop read")

    async def _read_after_stop(self) -> None:
        """Read the lift once, unless the shade reports it within STOP_SETTLE_S."""
        if await self._reported_lift(STOP_SETTLE_S) is not None or self._device_gone:
            return
        try:
            lift = await self._read_lift_live(RadioBudget(limit=READ_ATTEMPTS))
        except RadioBudgetSpentError:
            lift = None
        _LOGGER.debug("%s: lift after Stop: %s", self.endpoint.device.ieee, lift)
        if lift is not None:
            self.update_attribute(ATTR_LIFT.id, lift)

    async def _deliver_holding_lock(
        self,
        wire: WireCommand,
        generation: int,
        budget: RadioBudget,
        send_kwargs: dict[str, Any],
    ) -> Any:
        """Send a movement while holding the shade's lock, then release it.

        A command the radio answered with SUCCESS hands the readback its re-send.
        """
        assert wire.target_lift is not None
        resend = None
        try:
            self._command_origin = self._take_baseline()
            token = _RADIO_BUDGET.set(budget)
            try:
                reply = await self._send_movement(wire, send_kwargs, generation)
            except RadioBudgetSpentError as exc:
                return self._give_up(wire, str(exc))
            finally:
                _RADIO_BUDGET.reset(token)
            if getattr(reply, "status", None) is foundation.Status.SUCCESS:
                resend = functools.partial(
                    self._resend_frame, wire, send_kwargs, generation
                )
            return reply
        finally:
            self._command_lock.release()
            self._run_hook(
                self._finish_if_newest, generation, wire.target_lift, budget, resend
            )

    async def _send_frame(self, wire: WireCommand, **kwargs: Any) -> Any:
        """Send one frame through zigpy, bounded by SEND_TIMEOUT, without zigpy's retries.

        Delivery does its own re-sending; a caller's ``retries`` is overridden so that
        each budgeted request is exactly one frame.
        """
        kwargs["retries"] = 0
        async with asyncio.timeout(SEND_TIMEOUT):
            return await super().command(wire.command_id, *wire.args, **kwargs)

    async def _send_movement(
        self, wire: WireCommand, send_kwargs: dict[str, Any], generation: int
    ) -> Any:
        """Send a movement frame, once more SEND_RETRY_DELAY later if it was lost.

        Return its reply as ``_forwarded_reply`` reports it, or FAILURE if both frames
        were lost (a delivery error or timeout), or if a Stop came before the second.
        """
        for attempt in range(SEND_ATTEMPTS):
            if attempt:
                await asyncio.sleep(SEND_RETRY_DELAY)
            if generation != self._generation:
                return self._give_up(wire, "stopped before the frame was sent again")
            try:
                return await self._send_movement_frame(wire, **send_kwargs)
            except (DeliveryError, TimeoutError) as exc:
                _LOGGER.debug(
                    "%s: %s frame lost: %r",
                    self.endpoint.device.ieee,
                    self._describe(wire),
                    exc,
                )
        return self._give_up(wire, f"{SEND_ATTEMPTS} frames lost")

    async def _resend_frame(
        self,
        wire: WireCommand,
        send_kwargs: dict[str, Any],
        generation: int,
        budget: RadioBudget,
    ) -> None:
        """Send a movement's frame once more, for the readback, charged to ``budget``.

        One frame, never retried. Nothing is sent after a Stop or a newer movement (the
        generation has moved on). The command has returned, so the outcome is only
        logged.
        """
        ieee = self.endpoint.device.ieee
        if generation != self._generation:
            _LOGGER.debug("%s: stopped; %s not re-sent", ieee, self._describe(wire))
            return
        token = _RADIO_BUDGET.set(budget)
        try:
            reply = await self._send_movement_frame(wire, **send_kwargs)
        except (DeliveryError, TimeoutError) as exc:
            reply = exc
        finally:
            _RADIO_BUDGET.reset(token)
        _LOGGER.debug(
            "%s: %s re-sent: %r",
            ieee,
            self._describe(wire),
            getattr(reply, "status", reply),
        )

    async def _send_movement_frame(self, wire: WireCommand, **kwargs: Any) -> Any:
        """Send one movement frame; return its reply as ``_forwarded_reply`` reports it."""
        reply = await self._send_frame(wire, **kwargs)
        return self._forwarded_reply(wire, reply)

    def _forwarded_reply(self, wire: WireCommand, reply: Any) -> Any:
        """Return the reply to report for a standard frame the radio forwarded.

        The radio's firmware answers every Window Covering command it handles twice,
        with one TSN: SUCCESS, then UNSUP_CLUSTER_COMMAND (firmware analysis §3), and
        zigpy returns whichever arrives first. For an open, close, go-to or Stop, that
        0x81 only says the frame was taken and forwarded to the motor, as the SUCCESS
        does, so it is reported as SUCCESS: ZHA's cover raises on anything else. It is
        never a reason to re-send. Any other reply is returned unchanged. Only standard
        frames come here, which the radio forwards: a manufacturer-specific movement,
        which it refuses with a genuine 0x81, is refused before sending (``_refusal``),
        and a manufacturer-specific Stop's reply is passed through (``_deliver``).

        Neither reply says whether the motor moved, so the result reports the radio's
        acceptance of a frame, not movement; the readback judges movement afterwards.
        Every frame sent here is an up_open, down_close, go_to_lift_percentage or Stop,
        all handled by the radio and so answered SUCCESS then 0x81. The motor halts on
        a forwarded Stop (Part 1 §3d).
        """
        if (
            isinstance(reply, foundation.DefaultResponse)
            and reply.status is foundation.Status.UNSUP_CLUSTER_COMMAND
        ):
            _LOGGER.debug(
                "%s: %s answered UNSUP_CLUSTER_COMMAND, the firmware's second reply",
                self.endpoint.device.ieee,
                self._describe(wire),
            )
            return _default_response(reply.command_id, foundation.Status.SUCCESS)
        return reply

    def _give_up(self, wire: WireCommand, reason: str) -> foundation.DefaultResponse:
        """Return the reply for a movement command delivery could not make take effect.

        The command fails the way any failed command does: a Default Response with a
        failure status, which ZHA handles on its own non-SUCCESS path. FAILURE is ZCL's
        status for "the operation was not successful", the one a device would send for a
        command it did not carry out.
        """
        _LOGGER.debug(
            "%s: giving up on %s: %s",
            self.endpoint.device.ieee,
            self._describe(wire),
            reason,
        )
        return _default_response(wire.command_id, foundation.Status.FAILURE)

    def _describe(self, wire: WireCommand) -> str:
        """Name a wire command as ``name(args)``, e.g. ``go_to_lift_percentage(84)``."""
        name = self.server_commands[wire.command_id].name
        return f"{name}({', '.join(str(arg) for arg in wire.args)})"

    # ------------------------------------------------------------- live reads

    def _cached_lift_raw(self) -> int | None:
        """Return delivery's baseline, the shade's current raw lift, without radio traffic.

        That is the lift last received from the shade since startup, unless a movement
        has been sent since whose travel was not seen to end before it (see "Delivery").
        A lift restored from zigpy's database, or derived for display, is none.
        """
        return self._raw_lift if self._raw_lift_is_baseline else None

    def _take_baseline(self) -> int | None:
        """Return the baseline for a movement about to be sent, and retire it."""
        baseline = self._cached_lift_raw()
        self._raw_lift_is_baseline = self._shade_settled = False
        self._unseen_end = None
        return baseline

    # ------------------------------------------------------- displayed position

    def _update_attribute(self, attrid: Any, value: Any) -> None:
        """Cache a lift from the shade as it sent it, and keep it as the baseline.

        Every lift the shade sends, read or reported, arrives here. A lift outside
        0-100 (255 is "unknown") is not a position and leaves both as they were.
        """
        if attrid not in (ATTR_LIFT.id, ATTR_LIFT.name, ATTR_LIFT):
            super()._update_attribute(attrid, value)
            return
        if value is None:
            self._raw_lift, self._raw_lift_is_baseline = None, False
            super()._update_attribute(attrid, None)
            return
        raw_lift = _valid_lift(value)
        if raw_lift is None:
            _LOGGER.debug(
                "%s: lift %r is not a position; ignored",
                self.endpoint.device.ieee,
                value,
            )
            return
        if self._unseen_end is not None and raw_lift == self._unseen_end:
            self._shade_settled, self._unseen_end = True, None
        self._raw_lift, self._raw_lift_is_baseline = raw_lift, self._shade_settled
        super()._update_attribute(attrid, raw_lift)
        if _IN_REPORT.get():
            for waiter in self._report_waiters:
                if not waiter.done():
                    waiter.set_result(raw_lift)

    def handle_cluster_general_request(
        self, hdr: foundation.ZCLHeader, *args: Any, **kwargs: Any
    ) -> Any:
        """Handle a general request, marking a Report Attributes as the shade's report."""
        token = _IN_REPORT.set(
            hdr.command_id == foundation.GeneralCommand.Report_Attributes
        )
        try:
            return super().handle_cluster_general_request(hdr, *args, **kwargs)
        finally:
            _IN_REPORT.reset(token)

    def _legacy_apply_quirk_attribute_update(
        self, attr_def: foundation.ZCLAttributeDef, value: Any
    ) -> Any | None:
        """Swallow an unreadable lift from a read or report: no cache change, no event.

        zigpy routes every read and reported value through here; when the cache keeps
        its value for one it then announces that cached value as an update, which ZHA
        would take as a fresh position. None tells zigpy the value was swallowed.
        """
        if attr_def.id == ATTR_LIFT.id and _valid_lift(value) is None:
            _LOGGER.debug(
                "%s: lift %r is not a position; ignored",
                self.endpoint.device.ieee,
                value,
            )
            return None
        return super()._legacy_apply_quirk_attribute_update(attr_def, value)

    async def _read_lift_live(self, budget: RadioBudget | None = None) -> int | None:
        """Read the motor's raw lift; None if the read fails or the answer is no lift.

        The read goes through zigpy's request path but leaves the attribute cache and
        its listeners alone. Callers that want the cache updated
        write the returned raw lift with ``update_attribute``. With ``budget``, the read
        attempts are charged to it, and RadioBudgetSpentError is raised once it is
        spent. During delivery the command's budget is used.
        """
        token = _RADIO_BUDGET.set(budget) if budget is not None else None
        try:
            result = await self._with_read_retry(
                self.read_attributes_raw, [ATTR_LIFT.id]
            )
        except (DeliveryError, TimeoutError) as exc:
            _LOGGER.debug("%s: lift read failed: %r", self.endpoint.device.ieee, exc)
            return None
        finally:
            if token is not None:
                _RADIO_BUDGET.reset(token)
        records = result[0]
        if not isinstance(records, list):
            return None  # one failure status for the whole request
        for record in records:
            if record.attrid == ATTR_LIFT.id:
                if record.status != foundation.Status.SUCCESS:
                    return None
                return _valid_lift(record.value.value)
        return None

    async def read_attributes(self, attributes: Any, *args: Any, **kwargs: Any) -> Any:
        """Read attributes, retrying once when the first attempt is lost."""
        return await self._with_read_retry(
            super().read_attributes, attributes, *args, **kwargs
        )

    async def _with_read_retry(
        self, read: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Run a read, retrying once after READ_RETRY_DELAY when the attempt is lost.

        This retry replaces zigpy's: a caller's ``retries`` is overridden so that each
        attempt is exactly one frame, and each attempt is bounded by READ_TIMEOUT.
        """
        kwargs["retries"] = 0
        try:
            async with asyncio.timeout(READ_TIMEOUT):
                return await read(*args, **kwargs)
        except (DeliveryError, TimeoutError) as exc:
            _LOGGER.debug(
                "%s: read lost (%r), retrying once", self.endpoint.device.ieee, exc
            )
        await asyncio.sleep(READ_RETRY_DELAY)
        async with asyncio.timeout(READ_TIMEOUT):
            return await read(*args, **kwargs)

    @staticmethod
    def _refusal(command_id: Any, manufacturer: Any) -> str | None:
        """Return why a cluster command must not be sent, or None if it may be.

        The radio turns REFUSED_COMMANDS into malformed serial frames, and refuses
        every manufacturer-specific Window Covering frame unforwarded (firmware
        analysis §2, §3), so sending a manufacturer-specific movement is pointless.
        ``manufacturer`` is the code the frame would carry (zigpy treats None and
        UNDEFINED alike: a standard frame). Stop is left to its pass-through.
        """
        if command_id in REFUSED_COMMANDS:
            return "the radio sends the motor a malformed frame"
        if command_id in MOVEMENT_COMMANDS and manufacturer not in (None, UNDEFINED):
            return "the radio refuses manufacturer-specific frames unforwarded"
        return None

    def _refuse(self, command_id: Any, reason: str) -> foundation.DefaultResponse:
        """Answer a refused command, unsent, as a device answers one it does not support.

        That is a Default Response with UNSUP_CLUSTER_COMMAND, which ZHA handles as any
        such refusal.
        """
        _LOGGER.debug(
            "%s: %s refused, not sent: %s",
            self.endpoint.device.ieee,
            self.server_commands[command_id].name,
            reason,
        )
        return _default_response(command_id, foundation.Status.UNSUP_CLUSTER_COMMAND)

    async def request(
        self, general: bool, command_id: Any, schema: Any, *args: Any, **kwargs: Any
    ) -> Any:
        """Send a request, charging it to the radio budget of a command in delivery.

        A command ``_refusal`` names a reason for is never sent, whatever path it came
        by: it is answered here (see ``_refuse``).
        """
        if not general:
            reason = self._refusal(command_id, kwargs.get("manufacturer"))
            if reason is not None:
                return self._refuse(command_id, reason)
        budget = _RADIO_BUDGET.get()
        if budget is not None and not budget.take(read=general):
            raise RadioBudgetSpentError(
                f"{self.endpoint.device.ieee}: radio budget of {budget.limit} "
                "operations spent"
            )
        return await super().request(general, command_id, schema, *args, **kwargs)


(
    QuirkBuilder("Smartwings", "WM25/L-Z")
    # The released quirk's battery handling, kept: the radio copies the motor's byte into
    # BatteryPercentageRemaining unchanged (firmware analysis §6). That byte is inferred
    # to be whole percent (the Office Shade's 168 under this doubling means 84), pending
    # a raw read (POWER-BATTERY-UNITS). ZCL counts the attribute in half percent and
    # ZHA's battery sensor halves it, so doubled, 84 is cached as 168 and shown as 84 %.
    .replaces(DoublingPowerConfigurationCluster)
    .replaces(WM25LZWindowCovering)
    .exposes_feature(QUIRK_ID)
    .add_to_registry()
)
