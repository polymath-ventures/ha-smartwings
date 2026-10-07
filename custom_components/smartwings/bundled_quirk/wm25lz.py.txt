"""Device handler for SmartWings WM25/L-Z roller shades.

Unlike the released quirk, open and close are not swapped. The radio answers each
command twice (SUCCESS, then UNSUP_CLUSTER_COMMAND), mangles go_to_lift_value and the
tilt go-tos, and the motor sometimes ignores the first command after idling. It reports
its position only when travel ends, so a read during travel shows where it started.
"""

import asyncio
from collections.abc import Coroutine
import contextlib
import functools
import logging
from typing import Any, Final

from zhaquirks import DoublingPowerConfigurationCluster
from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zigpy.exceptions import DeliveryError, ZigbeeException
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

_LOGGER = logging.getLogger(__name__)

QUIRK_ID: Final = "smartwings.wm25lz"

LIFT: Final = WindowCovering.AttributeDefs.current_position_lift_percentage
COMMANDS: Final = WindowCovering.ServerCommandDefs
STOP: Final = COMMANDS.stop.id
GO_TO_LIFT: Final = COMMANDS.go_to_lift_percentage.id
# The lift each movement heads for (ZCL: 0 = open, 100 = closed); a go-to's is its arg.
MOVES: Final = {COMMANDS.up_open.id: 0, COMMANDS.down_close.id: 100, GO_TO_LIFT: None}
# The radio turns these into malformed motor frames.
REFUSED: Final = {
    COMMANDS.go_to_lift_value.id,
    COMMANDS.go_to_tilt_value.id,
    COMMANDS.go_to_tilt_percentage.id,
}

SEND_TIMEOUT: Final = 5.0
RESEND_DELAY: Final = 2.5
FULL_TRAVEL: Final = 70.0
ARRIVAL_MARGIN: Final = 3.0
MIN_WAIT: Final = 5.0
STOP_WAIT: Final = 3.0
AT_TARGET: Final = 3
MOVED: Final = 2


def _response(command_id: int, status: foundation.Status) -> Any:
    """Return a Default Response to ``command_id``."""
    return foundation.GENERAL_COMMANDS[
        foundation.GeneralCommand.Default_Response
    ].schema(command_id=command_id, status=status)


def _lift(value: Any) -> int | None:
    """Return ``value`` as a lift percentage, or None if unknown (0xFF) or invalid."""
    return value if isinstance(value, int) and 0 <= value <= 100 else None


def _arrival(origin: int | None, target: int) -> float:
    """Return how long travel from ``origin`` to ``target`` may take, in seconds."""
    distance = 100 if origin is None else abs(target - origin)
    return max(MIN_WAIT, distance / 100 * FULL_TRAVEL + ARRIVAL_MARGIN)


def _moved(origin: int | None, lift: int, target: int) -> bool:
    """Return whether ``lift`` is at ``target`` or shows travel toward it."""
    if abs(lift - target) <= AT_TARGET:
        return True
    return origin is not None and abs(target - lift) <= abs(target - origin) - MOVED


class WM25LZWindowCovering(CustomCluster, WindowCovering):
    """WindowCovering for the WM25/L-Z."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the cluster."""
        super().__init__(*args, **kwargs)
        self._task: asyncio.Task | None = None  # what follows the latest command
        self._report: asyncio.Future[int] | None = None

    async def command(self, command_id: Any, *args: Any, **kwargs: Any) -> Any:
        """Send a command, compensating for the radio and the motor."""
        standard = kwargs.get("manufacturer") in (None, UNDEFINED)
        if command_id in REFUSED or (command_id in MOVES and not standard):
            _LOGGER.debug("Refusing command 0x%02x, not sent", command_id)
            return _response(command_id, foundation.Status.UNSUP_CLUSTER_COMMAND)
        if command_id == STOP and standard:
            self._start(self._wait_for_lift(STOP_WAIT))
            return await self._send(command_id, *args, **kwargs)
        if command_id in MOVES:
            return await self._move(command_id, *args, **kwargs)
        return await super().command(command_id, *args, **kwargs)

    async def _move(self, command_id: int, *args: Any, **kwargs: Any) -> Any:
        """Send a movement and follow its travel in the background."""
        target = MOVES[command_id]
        if command_id == GO_TO_LIFT:
            target = _lift(args[0] if args else kwargs.get("percentage_lift_value"))
        send = functools.partial(self._send, command_id, *args, **kwargs)
        sent = asyncio.get_running_loop().create_future()
        task = self._start(self._follow(sent, _lift(self.get(LIFT.id)), target, send))
        try:
            reply = await self._deliver(command_id, send, task)
            if not sent.done():
                sent.set_result(reply)
        finally:
            sent.cancel()
        return reply

    async def _deliver(self, command_id: int, send: Any, task: asyncio.Task) -> Any:
        """Send a movement frame; if it is lost, send it once more unless superseded."""
        try:
            return await send()
        except (DeliveryError, TimeoutError) as exc:
            _LOGGER.debug("Command 0x%02x lost (%r), sending again", command_id, exc)
        await asyncio.sleep(RESEND_DELAY)
        if self._task is task:
            with contextlib.suppress(DeliveryError, TimeoutError):
                return await send()
        return _response(command_id, foundation.Status.FAILURE)

    async def _send(self, command_id: int, *args: Any, **kwargs: Any) -> Any:
        """Send one frame; report the radio's second reply, 0x81, as SUCCESS."""
        async with asyncio.timeout(SEND_TIMEOUT):
            reply = await super().command(command_id, *args, **{"retries": 0, **kwargs})
        if getattr(reply, "status", None) == foundation.Status.UNSUP_CLUSTER_COMMAND:
            return _response(command_id, foundation.Status.SUCCESS)
        return reply

    def _start(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        """Cancel this shade's pending work and run ``coro`` in its place."""
        if self._task is not None:
            self._task.cancel()
        app = self.endpoint.device.application
        self._task = app.create_task(coro, name=f"{self.endpoint.device.ieee} lift")
        return self._task

    async def _follow(
        self, sent: asyncio.Future, origin: int | None, target: int | None, send: Any
    ) -> None:
        """Show where travel ends; send the movement again once if it never started."""
        accepted = getattr(await sent, "status", None) == foundation.Status.SUCCESS
        if target is None:
            return
        lift = await self._wait_for_lift(_arrival(origin, target))
        if lift is None or not accepted or _moved(origin, lift, target):
            return
        _LOGGER.debug("No travel toward lift %s seen (at %s); re-sending", target, lift)
        with contextlib.suppress(ZigbeeException, TimeoutError):
            await send()
        await self._wait_for_lift(_arrival(lift, target))

    async def _wait_for_lift(self, delay: float) -> int | None:
        """Return the lift the shade reports within ``delay`` s, or else read it once."""
        self._report = asyncio.get_running_loop().create_future()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(delay):
                return await self._report
        try:
            success, _ = await self.read_attributes([LIFT.id], allow_cache=False)
        except ZigbeeException, TimeoutError:
            return None
        return _lift(success.get(LIFT.id))

    def handle_cluster_general_request(
        self, hdr: foundation.ZCLHeader, args: Any, **kwargs: Any
    ) -> None:
        """Handle a general request, noting the lift the shade reports."""
        super().handle_cluster_general_request(hdr, args, **kwargs)
        if hdr.command_id != foundation.GeneralCommand.Report_Attributes:
            return
        for report in args.attribute_reports:
            lift = _lift(report.value.value) if report.attrid == LIFT.id else None
            if (
                lift is not None
                and self._report is not None
                and not self._report.done()
            ):
                self._report.set_result(lift)

    def _legacy_apply_quirk_attribute_update(
        self, attr_def: foundation.ZCLAttributeDef, value: Any
    ) -> Any:
        """Drop an unknown lift (0xFF) from a read or report, leaving the cache as is."""
        if attr_def.id == LIFT.id and _lift(value) is None:
            return None
        return super()._legacy_apply_quirk_attribute_update(attr_def, value)


(
    QuirkBuilder("Smartwings", "WM25/L-Z")
    .replaces(DoublingPowerConfigurationCluster)
    .replaces(WM25LZWindowCovering)
    .exposes_feature(QUIRK_ID)
    .add_to_registry()
)
