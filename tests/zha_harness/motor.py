"""A model of one WM25/L-Z motor, as measured on the real shades.

See docs/device-behavior.md and docs/evidence/firmware-analysis.md. Position is in ZCL
lift space (0 = fully open, 100 = fully closed) and is a pure function of the loop's
clock, so it advances with virtual time and needs no ticking task. Modelled behaviour:

* lift 0 and 100 are the limits set with the remote; ``down_close`` and a go-to 100 both
  stop at the lower limit, reported as 100;
* Stop is answered with UNSUP_CLUSTER_COMMAND, and the motor halts;
* the radio answers a lift read from its own copy, which changes only when the motor
  sends a position: at the end of travel, a stall or a Stop. ``report_interval_s`` adds
  positions sent during travel;
* each position sent is pushed as a Report Attributes (``reports``) when it differs from
  the radio's copy, ``report_latency`` (default ``reply_latency``) after the event. A move
  set with ``start_moving`` or ``set_position`` pushes nothing;
* a manufacturer-specific Window Covering command is refused with UNSUP_CLUSTER_COMMAND
  and not acted on;
* with ``double_reply``, each handled command draws SUCCESS and UNSUP_CLUSTER_COMMAND with
  the same TSN, in either order, or only the 0x81; without it the motor answers once.

Tests can also script departures: dropped frames (``drop_next``), acknowledged but ignored
frames (``ignore_commands``, ``ignore_next``), a late start (``start_delay``), scripted
lift reads (``script_lift_reads``), send failures (``fail_next_sends``), travel already
under way (``start_moving``) and a stall (``stall_at``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from typing import Literal

import zigpy.types as t
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

from .radio import SHADE_COVERING_ATTRIBUTES, Frame

_COMMANDS = WindowCovering.ServerCommandDefs
_MOVEMENT_COMMANDS = (
    _COMMANDS.up_open.id,
    _COMMANDS.down_close.id,
    _COMMANDS.go_to_lift_percentage.id,
)
_LIFT_ID = WindowCovering.AttributeDefs.current_position_lift_percentage.id
# The Window Covering commands the radio has a handler for: each
# draws SUCCESS, then UNSUP_CLUSTER_COMMAND. IDs 3 and 6 and any other get only the 0x81.
FIRMWARE_HANDLED_COMMANDS = frozenset({0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08})
DoubleReply = Literal["success-first", "unsup-first", "unsup-only"]


@dataclass(kw_only=True)
class MotorSim:
    """One shade motor: where it is, where it is heading, and how fast."""

    position: float = 50.0
    rate_pct_per_s: float = 5.0
    reply_latency: float = 1.0
    # Acknowledge movement commands with SUCCESS but never move: a stuck shade.
    ignore_commands: bool = False
    # Seconds between an obeyed movement command and the start of travel.
    start_delay: float = 0.0
    # A lift where any travel through it stops short of its target.
    stall_at: float | None = None
    # Answer each handled command with both of the firmware's Default Responses, in
    # this order, or with only the 0x81 ("unsup-only"); None answers once.
    double_reply: DoubleReply | None = None
    # Seconds between positions the motor sends during travel; None sends none.
    report_interval_s: float | None = None
    # Whether the positions the motor sends are pushed to the coordinator as reports.
    reports: bool = True
    # Seconds from the motor sending a position to its report reaching the hub; None is
    # reply_latency.
    report_latency: float | None = None
    target: float = field(init=False)
    moving_since: float = field(init=False, default=0.0)
    # The radio's copy of the lift when the current travel was set.
    _cached: float = field(init=False)
    _drop_remaining: int = field(init=False, default=0)
    _ignore_remaining: int = field(init=False, default=0)
    _lift_reads: deque[int | foundation.Status | None] = field(
        init=False, default_factory=deque
    )
    _send_failures: deque[bool | None] = field(init=False, default_factory=deque)
    _read_send_failures: deque[bool | None] = field(init=False, default_factory=deque)

    def __post_init__(self) -> None:
        """Start at rest."""
        self.target = self._cached = self.position

    def set_position(self, lift: float) -> None:
        """Put the shade at ``lift`` at rest, as if moved by its remote."""
        self.position = self.target = self._cached = lift

    def drop_next(self, count: int) -> None:
        """Ignore the next ``count`` frames entirely: no movement, no reply."""
        self._drop_remaining = count

    def ignore_next(self, count: int) -> None:
        """Answer the next ``count`` movement frames as usual but do not act on them."""
        self._ignore_remaining = count

    def script_lift_reads(self, *answers: int | foundation.Status | None) -> None:
        """Answer the next lift reads with these, in order.

        An int is reported as the raw lift (255 is ZCL's "unknown"), a status is reported
        as the read's failure status, and None leaves the read unanswered. Later reads
        report the real position again.
        """
        self._lift_reads.extend(answers)

    def fail_next_sends(
        self, count: int, *, delivered: bool, reads: bool = False, after: int = 0
    ) -> None:
        """Make the radio raise DeliveryError for ``count`` frames of one kind.

        The kind is cluster commands, or with ``reads``, Read Attributes requests. The
        first ``after`` such frames are sent normally. With ``delivered``, the motor still
        acts on each failing frame (a lost acknowledgement); without, the frame never
        reaches it.
        """
        failures = self._read_send_failures if reads else self._send_failures
        failures.extend([None] * after + [delivered] * count)

    def take_send_failure(self, frame: Frame) -> bool | None:
        """Return None to send ``frame`` normally, else whether the failing frame lands."""
        failures = self._read_send_failures if frame.general else self._send_failures
        return failures.popleft() if failures else None

    def start_moving(self, target: float, now: float) -> None:
        """Set the shade travelling toward ``target`` from where it is, as its remote would."""
        self._cached = self.cached_at(now)
        self.position = self.position_at(now)
        self.target = min(100.0, max(0.0, target))
        self.moving_since = now

    def halt(self, now: float) -> None:
        """Stop where the shade is; the motor sends its position, as on arrival."""
        self._cached = self.cached_at(now)
        self.position = self.target = self.position_at(now)
        self.moving_since = now

    def _stop_lift(self) -> float:
        """Return where the current travel ends: its target, or a stall short of it."""
        target = self.target
        stall = self.stall_at
        if stall is not None and min(self.position, target) < stall < max(
            self.position, target
        ):
            return stall
        return target

    def ends_at(self) -> float:
        """Loop time the current travel ends (its start, for a shade at rest)."""
        return (
            self.moving_since
            + abs(self._stop_lift() - self.position) / self.rate_pct_per_s
        )

    def position_at(self, now: float) -> float:
        """Lift percentage at loop time ``now``."""
        travelled = self.rate_pct_per_s * max(0.0, now - self.moving_since)
        target = self._stop_lift()
        distance = target - self.position
        if abs(distance) <= travelled:
            return target
        return self.position + math.copysign(travelled, distance)

    def _sent_positions(self, after: float, until: float) -> list[float]:
        """Return the loop times in (``after``, ``until``] the radio's copy changes.

        The motor sends a position at each ``report_interval_s`` tick of travel and when
        travel ends; only one that differs from the copy changes it.
        """
        end = self.ends_at()
        sent = []
        interval = self.report_interval_s
        if interval is not None:
            tick = self.moving_since + interval
            while tick < end and tick <= until:
                sent.append(tick)
                tick += interval
        if end <= until:
            sent.append(end)
        times = []
        copy = round(self._cached)
        for at in sent:
            lift = round(self.position_at(at))
            if lift == copy:
                continue
            copy = lift
            if at > after:
                times.append(at)
        return times

    def cached_at(self, now: float) -> float:
        """Return the lift a read answers at loop time ``now``: the radio's copy."""
        sent = self._sent_positions(-math.inf, now)
        if not sent:
            return self._cached
        return self.position_at(sent[-1])

    def next_report_at(self, after: float) -> float | None:
        """Return when the motor next sends a position after ``after``, if it will."""
        if not self.reports:
            return None
        sent = self._sent_positions(after, math.inf)
        return sent[0] if sent else None

    def take_drop(self) -> bool:
        """Whether this frame is one the motor ignores."""
        if self._drop_remaining > 0:
            self._drop_remaining -= 1
            return True
        return False

    def handle(self, frame: Frame, now: float) -> bytes | None:
        """Act on a frame addressed to the shade and return the ZCL reply payload, if any."""
        if frame.cluster_id != WindowCovering.cluster_id or frame.tsn is None:
            return None
        if frame.general:
            if frame.command_id == foundation.GeneralCommand.Read_Attributes:
                return self._read_attributes_response(frame, now)
            return None
        if frame.manufacturer is not None:
            return _default_response(frame, foundation.Status.UNSUP_CLUSTER_COMMAND)
        if frame.command_id in _MOVEMENT_COMMANDS and (
            self.ignore_commands or self._ignore_remaining > 0
        ):
            self._ignore_remaining = max(0, self._ignore_remaining - 1)
            return _default_response(frame, foundation.Status.SUCCESS)
        if frame.command_id in (_COMMANDS.up_open.id, _COMMANDS.down_close.id):
            lowers = frame.command_id == _COMMANDS.down_close.id
            self._move_to(100.0 if lowers else 0.0, now)
        elif frame.command_id == _COMMANDS.go_to_lift_percentage.id:
            self._move_to(float(frame.args["percentage_lift_value"]), now)
        elif frame.command_id == _COMMANDS.stop.id:
            # A shade at rest has nothing to halt and sends nothing.
            if now < self.ends_at():
                self.halt(now)
            return _default_response(frame, foundation.Status.UNSUP_CLUSTER_COMMAND)
        else:
            return _default_response(frame, foundation.Status.UNSUP_CLUSTER_COMMAND)
        return _default_response(frame, foundation.Status.SUCCESS)

    def replies(self, frame: Frame, now: float) -> list[bytes]:
        """Act on a frame as ``handle`` does; return every reply payload, in order.

        With ``double_reply``, a Window Covering command the firmware handles draws
        SUCCESS and UNSUP_CLUSTER_COMMAND with the frame's TSN (or the 0x81 alone),
        whatever ``handle`` answered.
        """
        reply = self.handle(frame, now)
        if reply is None:
            return []
        if (
            self.double_reply is None
            or frame.general
            or frame.manufacturer is not None
            or frame.command_id not in FIRMWARE_HANDLED_COMMANDS
        ):
            return [reply]
        statuses = [
            foundation.Status.SUCCESS,
            foundation.Status.UNSUP_CLUSTER_COMMAND,
        ]
        if self.double_reply == "unsup-first":
            statuses.reverse()
        elif self.double_reply == "unsup-only":
            statuses = [foundation.Status.UNSUP_CLUSTER_COMMAND]
        return [_default_response(frame, status) for status in statuses]

    def _move_to(self, target: float, now: float) -> None:
        target = min(100.0, max(0.0, target))
        if target == self.target and self.moving_since > now:
            # An identical command while a late start is pending does not restart the wait.
            return
        self.start_moving(target, now)
        self.moving_since = now + self.start_delay

    def _read_attributes_response(self, frame: Frame, now: float) -> bytes | None:
        values: dict[int, int | foundation.Status] = dict(SHADE_COVERING_ATTRIBUTES)
        values[_LIFT_ID] = round(self.cached_at(now))
        if _LIFT_ID in frame.attribute_ids and self._lift_reads:
            scripted = self._lift_reads.popleft()
            if scripted is None:
                return None
            values[_LIFT_ID] = scripted
        records = []
        for attribute_id in frame.attribute_ids:
            value = values.get(attribute_id, foundation.Status.UNSUPPORTED_ATTRIBUTE)
            if isinstance(value, foundation.Status):
                records.append(foundation.ReadAttributeRecord(attribute_id, value))
                continue
            definition = WindowCovering.attributes[attribute_id]
            records.append(
                foundation.ReadAttributeRecord(
                    attribute_id,
                    foundation.Status.SUCCESS,
                    foundation.TypeValue(
                        type=foundation.DataType.from_python_type(
                            definition.type
                        ).type_id,
                        value=definition.type(value),
                    ),
                )
            )
        command = foundation.GeneralCommand.Read_Attributes_rsp
        header = foundation.ZCLHeader.general(
            frame.tsn, command, direction=foundation.Direction.Server_to_Client
        )
        body = foundation.GENERAL_COMMANDS[command].schema(status_records=records)
        return header.serialize() + body.serialize()


def _default_response(frame: Frame, status: foundation.Status) -> bytes:
    command = foundation.GeneralCommand.Default_Response
    header = foundation.ZCLHeader.general(
        frame.tsn, command, direction=foundation.Direction.Server_to_Client
    )
    body = foundation.GENERAL_COMMANDS[command].schema(
        command_id=t.uint8_t(frame.command_id), status=status
    )
    return header.serialize() + body.serialize()
