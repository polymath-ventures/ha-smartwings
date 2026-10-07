"""Device handler for SmartWings WM25/L-Z roller shades.

The released quirk swaps Open and Close; these units need no swap, so commands go out as
ZHA sends them. The motor stops every movement at the limits set with its remote, and
lift 100 is the lower limit.

The motor sometimes ignores the first frame after idling, and its radio answers reads
from a copy of the lift that changes only when travel ends. So a lost frame is re-sent
once, and after each movement the quirk waits for the shade's position report (or reads
the lift when travel should be over) and re-sends the frame once if no travel shows.

The radio answers each command twice, SUCCESS then UNSUP_CLUSTER_COMMAND; the second is
reported as SUCCESS. Commands the radio mangles (go_to_lift_value and the tilt go-tos)
or refuses (manufacturer-specific movements) are answered unsent with
UNSUP_CLUSTER_COMMAND. See docs/device-behavior.md.
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
from zigpy.exceptions import DeliveryError
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

_LOGGER = logging.getLogger(__name__)

# ZCL lift percentage: 0 = fully open, 100 = fully closed (the remote's lower limit).
ATTR_LIFT: Final = WindowCovering.AttributeDefs.current_position_lift_percentage
CMD_UP_OPEN: Final = WindowCovering.ServerCommandDefs.up_open.id
CMD_DOWN_CLOSE: Final = WindowCovering.ServerCommandDefs.down_close.id
CMD_GO_TO_LIFT: Final = WindowCovering.ServerCommandDefs.go_to_lift_percentage.id
CMD_STOP: Final = WindowCovering.ServerCommandDefs.stop.id
MOVEMENT_COMMANDS: Final = frozenset({CMD_UP_OPEN, CMD_DOWN_CLOSE, CMD_GO_TO_LIFT})
# The radio turns these into malformed serial frames: refused, never sent.
REFUSED_COMMANDS: Final = frozenset(
    {
        WindowCovering.ServerCommandDefs.go_to_lift_value.id,
        WindowCovering.ServerCommandDefs.go_to_tilt_value.id,
        WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id,
    }
)
LIFT_OPEN: Final = 0
LIFT_CLOSED: Final = 100

# Exposed as a ZHA feature so an integration can tell this quirk is loaded.
QUIRK_ID: Final = "smartwings.wm25lz"

# Timing, in seconds.
SEND_TIMEOUT: Final = 5.0
SEND_ATTEMPTS: Final = 2
SEND_RETRY_DELAY: Final = 2.5
READ_TIMEOUT: Final = 2.5
READ_RETRY_DELAY: Final = 1.5
READ_ATTEMPTS: Final = 2

# Lift points.
MOVED_TOLERANCE: Final = 2  # change from the baseline that counts as travel
AT_TARGET_TOLERANCE: Final = 3  # distance from the target that counts as there

# Worst case for one movement command, and for one read with its retry.
T_EXEC: Final = SEND_ATTEMPTS * SEND_TIMEOUT + (SEND_ATTEMPTS - 1) * SEND_RETRY_DELAY
LOCK_WAIT: Final = T_EXEC
T_READ: Final = READ_ATTEMPTS * READ_TIMEOUT + (READ_ATTEMPTS - 1) * READ_RETRY_DELAY

# Following travel after a movement. Reads cost battery, so the lift is read only when
# travel should be over.
FULL_TRAVEL_S: Final = 70.0  # slowest measured full travel
ARRIVAL_MARGIN_S: Final = 3.0
TRACK_MIN_FIRST_READ_S: Final = 5.0
CONFIRM_GAP_S: Final = 5.0
TRACK_MAX_READINGS: Final = 3  # per attempt: before and again after the re-send
TRACK_MAX_DURATION: Final = 120.0  # per attempt
STOP_SETTLE_S: Final = 3.0  # wait for the report of where a Stop halted the shade
DEFERRED_REREAD_DELAY: Final = 300.0  # one more read after tracking gave up


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
    """One WindowCovering command as sent, and the lift it should reach (None: none)."""

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


# What _acquire_command_lock returns for a movement a later Stop superseded.
_STOPPED: Final = -1
# Set while zigpy handles a Report Attributes the shade pushed.
_IN_REPORT: ContextVar[bool] = ContextVar("smartwings_in_report", default=False)


def _busy() -> str:
    """Return why a movement that never got the shade's lock was not sent."""
    return f"busy with another command for {LOCK_WAIT:g} s; not sent"


def _arrival_delay(lift: int | None, target: int) -> float:
    """Return the seconds until a shade at ``lift`` should have reached ``target``.

    An unknown lift counts as full travel.
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

    It does at the target, or on two equal readings once the shade has moved or stands
    within AT_TARGET_TOLERANCE of the target. Equal readings elsewhere may be a shade
    that has yet to start.
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

    It does unless it is within AT_TARGET_TOLERANCE of ``target`` or shows travel
    toward it from a known ``origin``.
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
        # Moves on with each movement that takes the lock and with each Stop; pending
        # retries, re-sends and finish hooks of an older generation do nothing.
        self._generation = 0
        # The lift last received from the shade since startup. It is the baseline for
        # the next movement only while _raw_lift_is_baseline.
        self._raw_lift: int | None = None
        self._raw_lift_is_baseline = False
        # False from sending a movement until a lift received shows its travel ended.
        self._shade_settled = True
        # The target of a movement whose end was not seen: a later lift equal to it
        # restores the baseline.
        self._unseen_end: int | None = None
        self._tracking: asyncio.Task[None] | None = None
        self._reread: asyncio.Task[None] | None = None
        # The latest movement's single re-send, until the readback uses or drops it.
        self._resend: Callable[[], Awaitable[None]] | None = None
        self._report_waiters: set[asyncio.Future[int]] = set()
        # Counts Stops: a movement issued before a Stop is dropped, unsent.
        self._stops = 0
        self._stop_read: asyncio.Task[None] | None = None
        # The baseline before the newest movement sent, if there was one.
        self._command_origin: int | None = None
        self._device_gone = False
        # zigpy announces a removal before it lets go of the device.
        device = self.endpoint.device
        self._removal_watch: _RemovalWatch | None = _RemovalWatch(
            device, self._on_device_gone
        )
        device.application.add_listener(self._removal_watch)
        # Called on shutdown and when a re-interview replaces the device.
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
        """Send a command: movements under the shade's lock, anything else at once."""
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
            # Nothing may move the shade after a Stop: drop the pending re-send, stop
            # any lost frame's retry, and drop movements still waiting for the lock.
            self._resend = None
            self._generation += 1
            self._stops += 1
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
                # A go-to without a valid lift: sent once, nothing to follow.
                self._take_baseline()
                return await self._send_movement_frame(wire, **send_kwargs, **kwargs)
            release = False
        finally:
            if release:
                self._command_lock.release()
        return await self._deliver_holding_lock(
            wire, generation, {**send_kwargs, **kwargs}
        )

    def _translate(
        self, command_id: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[WireCommand, dict[str, Any]]:
        """Return the frame to send, as ZHA sent it, and the lift it should reach.

        Open targets lift 0, close lift 100 and a go-to its lift; a go-to without a
        valid lift, Stop and anything else have no target. Also return the keyword
        arguments left for zigpy.
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
        """Cancel the tracker, the deferred re-read, the Stop read and the re-send."""
        for task in (self._tracking, self._reread, self._stop_read):
            if task is not None:
                task.cancel()
        self._tracking = self._reread = self._stop_read = None
        self._resend = None

    def _on_movement_finished(
        self,
        target_lift: int,
        resend: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Start following travel toward ``target_lift`` after a movement.

        Called once the lock is released, whether delivery succeeded or not. ``resend``
        sends the frame once more; None after a command that did not get a SUCCESS.
        """
        self._cancel_tracking()
        device = self.endpoint.device
        if (
            self._device_gone
            or device.application.devices.get(device.ieee) is not device
        ):
            _LOGGER.debug("%s: device gone; not following travel", device.ieee)
            return
        self._resend = resend
        self._tracking = self._create_task(
            self._track(target_lift, self._command_origin), "position readback"
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

        Not the device's own tasks: ``Device.on_remove()`` empties that set before the
        cancelled tasks finish.
        """
        device = self.endpoint.device
        return device.application.create_task(coro, name=f"{device.ieee} {name}")

    async def _track(self, target: int, origin: int | None) -> None:
        """Follow travel toward ``target`` until its end is seen; re-send once if none is.

        ``origin`` is the baseline before the command, or None. The first lift seen
        decides the re-send; after it, travel is confirmed by a second equal reading.
        Each attempt takes at most TRACK_MAX_READINGS reads within TRACK_MAX_DURATION.
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
                        lift = await self._read_lift_live()
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
                        await resend()
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
                    # Confirm the first moving lift CONFIRM_GAP_S later; after two
                    # differing ones, read next at the new arrival.
                    delay = (
                        CONFIRM_GAP_S
                        if reason != "still moving"
                        else max(CONFIRM_GAP_S, _arrival_delay(lift, target))
                    )
                    reason = "still moving"
        except TimeoutError:
            reason = f"no end after {TRACK_MAX_DURATION:g} s"
        if self._device_gone:
            return
        # No baseline until a lift received later is the target itself.
        self._unseen_end = target
        _LOGGER.warning(
            "%s: final position toward lift %s not seen (%s); last lift read: %s,"
            " reading again in %g s",
            ieee,
            target,
            reason,
            previous,
            DEFERRED_REREAD_DELAY,
        )
        self._reread = self._create_task(
            self._reread_later(), "position readback re-read"
        )

    async def _reported_lift(self, wait: float) -> int | None:
        """Wait up to ``wait`` seconds for the shade to report its lift; return it.

        Only a pushed report counts: a read during travel answers the lift from before
        the move.
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

    async def _reread_later(self) -> None:
        """Read the lift once, DEFERRED_REREAD_DELAY after tracking gave up."""
        await asyncio.sleep(DEFERRED_REREAD_DELAY)
        if self._device_gone:
            return
        lift = await self._read_lift_live()
        _LOGGER.debug("%s: deferred lift read: %s", self.endpoint.device.ieee, lift)
        if lift is not None:
            self.update_attribute(ATTR_LIFT.id, lift)

    def _finish_if_newest(
        self,
        generation: int,
        target_lift: int,
        resend: Callable[[], Awaitable[None]] | None,
    ) -> None:
        """Call _on_movement_finished unless a newer command has taken the lock since."""
        if generation == self._generation:
            self._on_movement_finished(target_lift, resend)

    @staticmethod
    def _run_hook(hook: Callable[..., None], *args: Any) -> None:
        """Run a hook as an event-loop callback, so it cannot change a command's result."""
        asyncio.get_running_loop().call_soon(hook, *args)

    # ---------------------------------------------------------------- delivery

    async def _deliver(
        self,
        wire: WireCommand,
        *,
        manufacturer: Any = None,
        expect_reply: bool = True,
        tsn: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Send a command without a target lift once and return its reply.

        A standard Stop's reply is reported as ``_forwarded_reply`` reports it; any
        other reply or exception is returned unchanged.
        """
        reply = await self._send_frame(
            wire,
            manufacturer=manufacturer,
            expect_reply=expect_reply,
            tsn=tsn,
            **kwargs,
        )
        if wire.command_id == CMD_STOP and manufacturer in (None, UNDEFINED):
            return self._forwarded_reply(wire, reply)
        return reply

    async def _acquire_command_lock(self) -> int | None:
        """Cancel earlier tracking, then wait up to LOCK_WAIT for the shade's lock.

        Return the command's generation once the lock is taken, None if it was not, or
        _STOPPED (lock released) if a Stop came since the command was issued. The
        caller releases the lock.
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
        """Cancel tracking unless a Stop came since: keep the read of where it halted."""
        if self._stops == issued:
            self._cancel_tracking()

    def _dropped(self, wire: WireCommand) -> foundation.DefaultResponse:
        """Answer SUCCESS, unsent, for a movement a later Stop superseded."""
        _LOGGER.debug(
            "%s: %s dropped, unsent: a Stop came after it",
            self.endpoint.device.ieee,
            self.server_commands[wire.command_id].name,
        )
        return _default_response(wire.command_id, foundation.Status.SUCCESS)

    def _after_stop(self) -> None:
        """Show where a Stop halts the shade: wait for its report, else read it once."""
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
        lift = await self._read_lift_live()
        _LOGGER.debug("%s: lift after Stop: %s", self.endpoint.device.ieee, lift)
        if lift is not None:
            self.update_attribute(ATTR_LIFT.id, lift)

    async def _deliver_holding_lock(
        self, wire: WireCommand, generation: int, send_kwargs: dict[str, Any]
    ) -> Any:
        """Send a movement while holding the shade's lock, then release it.

        A command the radio answered with SUCCESS hands the readback its re-send.
        """
        assert wire.target_lift is not None
        resend = None
        try:
            self._command_origin = self._take_baseline()
            reply = await self._send_movement(wire, send_kwargs, generation)
            if getattr(reply, "status", None) is foundation.Status.SUCCESS:
                resend = functools.partial(
                    self._resend_frame, wire, send_kwargs, generation
                )
            return reply
        finally:
            self._command_lock.release()
            self._run_hook(self._finish_if_newest, generation, wire.target_lift, resend)

    async def _send_frame(self, wire: WireCommand, **kwargs: Any) -> Any:
        """Send one frame, bounded by SEND_TIMEOUT, with zigpy's own retries off."""
        kwargs["retries"] = 0
        async with asyncio.timeout(SEND_TIMEOUT):
            return await super().command(wire.command_id, *wire.args, **kwargs)

    async def _send_movement(
        self, wire: WireCommand, send_kwargs: dict[str, Any], generation: int
    ) -> Any:
        """Send a movement frame, once more SEND_RETRY_DELAY later if it was lost.

        Return FAILURE if both frames were lost or a Stop came before the second.
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
        self, wire: WireCommand, send_kwargs: dict[str, Any], generation: int
    ) -> None:
        """Send a movement's frame once more, unless a Stop or newer movement came.

        One frame, never retried; the command has returned, so the outcome is logged.
        """
        ieee = self.endpoint.device.ieee
        if generation != self._generation:
            _LOGGER.debug("%s: stopped; %s not re-sent", ieee, self._describe(wire))
            return
        try:
            reply = await self._send_movement_frame(wire, **send_kwargs)
        except (DeliveryError, TimeoutError) as exc:
            reply = exc
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
        """Report the firmware's second reply to a forwarded frame as SUCCESS.

        The radio answers each command it forwards with SUCCESS, then
        UNSUP_CLUSTER_COMMAND, and zigpy returns whichever arrives first. ZHA's cover
        raises on anything but SUCCESS. Any other reply is returned unchanged.
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
        """Fail a movement command with a Default Response of FAILURE."""
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

    def _take_baseline(self) -> int | None:
        """Return the baseline for a movement about to be sent, and retire it."""
        baseline = self._raw_lift if self._raw_lift_is_baseline else None
        self._raw_lift_is_baseline = self._shade_settled = False
        self._unseen_end = None
        return baseline

    # ------------------------------------------------------- displayed position

    def _position(self, value: Any) -> int | None:
        """Return ``value`` as a lift, or None (logged) if it is not a position."""
        lift = _valid_lift(value)
        if lift is None:
            _LOGGER.debug(
                "%s: lift %r is not a position; ignored",
                self.endpoint.device.ieee,
                value,
            )
        return lift

    def _update_attribute(self, attrid: Any, value: Any) -> None:
        """Cache a lift from the shade, keep it as the baseline, and wake waiters.

        A lift outside 0-100 (255 is "unknown") is ignored.
        """
        if attrid not in (ATTR_LIFT.id, ATTR_LIFT.name, ATTR_LIFT):
            super()._update_attribute(attrid, value)
            return
        if value is None:
            self._raw_lift, self._raw_lift_is_baseline = None, False
            super()._update_attribute(attrid, None)
            return
        raw_lift = self._position(value)
        if raw_lift is None:
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

        Otherwise zigpy would announce the old cached value as an update.
        """
        if attr_def.id == ATTR_LIFT.id and self._position(value) is None:
            return None
        return super()._legacy_apply_quirk_attribute_update(attr_def, value)

    async def _read_lift_live(self) -> int | None:
        """Read the lift, leaving the cache alone; None if the read fails or is no lift."""
        try:
            result = await self._with_read_retry(
                self.read_attributes_raw, [ATTR_LIFT.id]
            )
        except (DeliveryError, TimeoutError) as exc:
            _LOGGER.debug("%s: lift read failed: %r", self.endpoint.device.ieee, exc)
            return None
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
        """Run a read bounded by READ_TIMEOUT, retrying once after READ_RETRY_DELAY.

        zigpy's own retries are off, so each attempt is one frame.
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

        Stop is left to its pass-through, manufacturer-specific or not.
        """
        if command_id in REFUSED_COMMANDS:
            return "the radio sends the motor a malformed frame"
        if command_id in MOVEMENT_COMMANDS and manufacturer not in (None, UNDEFINED):
            return "the radio refuses manufacturer-specific frames unforwarded"
        return None

    def _refuse(self, command_id: Any, reason: str) -> foundation.DefaultResponse:
        """Answer a refused command, unsent, with UNSUP_CLUSTER_COMMAND."""
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
        """Send a request, refusing a command ``_refusal`` names, whatever its path."""
        if not general:
            reason = self._refusal(command_id, kwargs.get("manufacturer"))
            if reason is not None:
                return self._refuse(command_id, reason)
        return await super().request(general, command_id, schema, *args, **kwargs)


(
    QuirkBuilder("Smartwings", "WM25/L-Z")
    # As in the released quirk: the radio passes on the motor's battery byte, which
    # appears to be whole percent, while ZCL counts half percent, so it is doubled.
    .replaces(DoublingPowerConfigurationCluster)
    .replaces(WM25LZWindowCovering)
    .exposes_feature(QUIRK_ID)
    .add_to_registry()
)
