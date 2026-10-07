"""A zigpy radio stub for the SmartWings harness: a real zigpy stack with no hardware.

Every outgoing frame leaves zigpy through ``send_packet``, so that is the one place frames
are captured. Replies (from the motor model, later) re-enter through zigpy's real
``packet_received`` path, so request/response matching, retries and TSNs are zigpy's own.
So do the lift reports the radio pushes whenever the motor sends a position (#51).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

import zigpy.application
import zigpy.config
import zigpy.exceptions
from zigpy.profiles import zha as zha_profile
import zigpy.types as t
import zigpy.zcl
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import Basic, Groups
import zigpy.zdo.types as zdo_t

if TYPE_CHECKING:
    from .motor import MotorSim

# Seconds between the replies to one frame (the firmware's double reply, see MotorSim).
DOUBLE_REPLY_GAP = 0.05

SHADE_IEEE = t.EUI64.convert("60:83:da:ff:fe:a0:00:02")
SHADE_NWK = t.NWK(0x5A1F)
COORDINATOR_IEEE = t.EUI64.convert("00:15:8d:00:02:32:4f:32")

# The WM25/L-Z as it identifies itself (docs Part 1 §2, "Identity").
SHADE_MANUFACTURER = "Smartwings"
SHADE_MODEL = "WM25/L-Z"
SHADE_INPUT_CLUSTERS = (0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102)
SHADE_OUTPUT_CLUSTERS = (0x0003, 0x0019)
SHADE_NODE_DESCRIPTOR = zdo_t.NodeDescriptor(
    logical_type=zdo_t.LogicalType.EndDevice,
    complex_descriptor_available=0,
    user_descriptor_available=0,
    reserved=0,
    aps_flags=0,
    frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
    mac_capability_flags=zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress,
    manufacturer_code=0x1002,
    maximum_buffer_size=82,
    maximum_incoming_transfer_size=82,
    server_mask=0,
    maximum_outgoing_transfer_size=82,
    descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
)
# WindowCovering attributes as measured on the real shades (docs Part 1 §2).
SHADE_COVERING_ATTRIBUTES = {
    WindowCovering.AttributeDefs.window_covering_type.id: 0,
    WindowCovering.AttributeDefs.config_status.id: 0x03,
    WindowCovering.AttributeDefs.installed_open_limit_lift.id: 0,
    WindowCovering.AttributeDefs.installed_closed_limit_lift.id: 0xFFFF,
}


@dataclass(frozen=True)
class Frame:
    """One ZCL frame as sent on the wire, decoded with the plain (unquirked) cluster."""

    packet: t.ZigbeePacket
    dst_nwk: int | None
    cluster_id: int
    tsn: int | None
    general: bool
    command_id: int | None
    args: dict[str, Any] = field(default_factory=dict)
    dropped: bool = False
    # The loop time the frame left at (virtual under the harness clock); None if unsent.
    sent_at: float | None = None
    # The manufacturer code of a manufacturer-specific frame; None for a standard one.
    manufacturer: int | None = None

    @property
    def attribute_ids(self) -> list[int]:
        """Attribute ids of a general Read Attributes frame."""
        return [int(a) for a in self.args.get("attribute_ids", [])]


def decode_frame(packet: t.ZigbeePacket) -> Frame:
    """Decode a ZCL packet into a Frame; ZDO and undecodable payloads keep only addressing."""
    dst_nwk = packet.dst.address if packet.dst.addr_mode == t.AddrMode.NWK else None
    if packet.dst_ep == 0:
        return Frame(packet, dst_nwk, packet.cluster_id, None, False, None)

    try:
        hdr, rest = foundation.ZCLHeader.deserialize(packet.data.serialize())
    except KeyError, ValueError:
        # Capture must never fail: a frame without a readable header keeps its addressing.
        return Frame(packet, dst_nwk, packet.cluster_id, None, False, None)
    general = hdr.frame_control.frame_type == foundation.FrameType.GLOBAL_COMMAND
    try:
        if general:
            schema = foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand(hdr.command_id)
            ].schema
        else:
            cluster = zigpy.zcl.Cluster._registry[packet.cluster_id]
            commands = (
                cluster.server_commands
                if hdr.direction == foundation.Direction.Client_to_Server
                else cluster.client_commands
            )
            schema = commands[hdr.command_id].schema
    except KeyError, ValueError:
        # No schema for this command: keep the header so a reply can still be built.
        schema = None
    args: dict[str, Any] = {}
    if schema is not None:
        try:
            args = schema.deserialize(rest)[0].as_dict()
        except KeyError, ValueError:
            # A known command with a malformed payload: nothing on the shade would act on
            # it, so keep only its addressing.
            return Frame(packet, dst_nwk, packet.cluster_id, None, False, None)
    return Frame(
        packet,
        dst_nwk,
        packet.cluster_id,
        hdr.tsn,
        general,
        hdr.command_id,
        args,
        manufacturer=hdr.manufacturer,
    )


class HarnessApp(zigpy.application.ControllerApplication):
    """A ControllerApplication whose radio is a no-op; it records every packet it sends."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Create the app, its capture list and (until a test attaches one) no motor."""
        super().__init__(config)
        self.frames: list[Frame] = []
        # One motor per shade, keyed by the shade's NWK address.
        self.motors: dict[int, MotorSim] = {}
        # The lift report each shade's motor will send next, keyed by NWK address, with
        # when it sends it; and the reports it has sent that are still on their way.
        self._report_timers: dict[int, tuple[asyncio.TimerHandle, float]] = {}
        self._reports_in_flight: dict[tuple[int, float], asyncio.TimerHandle] = {}

    @property
    def motor(self) -> MotorSim | None:
        """The motor answering for the seeded shade at SHADE_NWK."""
        return self.motors.get(SHADE_NWK)

    @motor.setter
    def motor(self, motor: MotorSim | None) -> None:
        if motor is None:
            self.motors.pop(SHADE_NWK, None)
        else:
            self.motors[SHADE_NWK] = motor

    @staticmethod
    def config_for(database: Path) -> dict[str, Any]:
        """Minimal zigpy config for a standalone app over the given database."""
        return {
            zigpy.config.CONF_DATABASE: str(database),
            zigpy.config.CONF_DEVICE: {zigpy.config.CONF_DEVICE_PATH: "/dev/null"},
            zigpy.config.CONF_STARTUP_ENERGY_SCAN: False,
            zigpy.config.CONF_NWK_BACKUP_ENABLED: False,
            zigpy.config.CONF_TOPO_SCAN_ENABLED: False,
            zigpy.config.CONF_WATCHDOG_ENABLED: False,
            zigpy.config.CONF_OTA: {zigpy.config.CONF_OTA_ENABLED: False},
        }

    async def send_packet(self, packet: t.ZigbeePacket) -> None:
        """Record the frame and, for a shade, let its motor act and schedule its reply."""
        loop = asyncio.get_running_loop()
        frame = replace(decode_frame(packet), sent_at=loop.time())
        motor = self.motors.get(frame.dst_nwk) if frame.dst_nwk is not None else None
        if motor is None:
            self.frames.append(frame)
            return
        if motor.take_drop():
            self.frames.append(replace(frame, dropped=True))
            return
        failure = motor.take_send_failure(frame)
        if failure is not None:
            # The radio reports a failed send; a delivered frame still moves the motor,
            # but its reply is lost with the acknowledgement.
            self.frames.append(replace(frame, dropped=not failure))
            if failure:
                now = loop.time()
                motor.handle(frame, now)
                self._schedule_report(frame, motor, now)
            raise zigpy.exceptions.DeliveryError("simulated send failure")
        self.frames.append(frame)
        now = loop.time()
        for index, reply in enumerate(motor.replies(frame, now)):
            loop.call_later(
                motor.reply_latency + index * DOUBLE_REPLY_GAP,
                self.packet_received,
                _reply_packet(packet, reply),
            )
        self._schedule_report(frame, motor, now)

    def _schedule_report(self, frame: Frame, motor: MotorSim, now: float) -> None:
        """After a command handled at ``now``, schedule the motor's next position report."""
        if frame.general or frame.dst_nwk is None:
            return
        # A position sent at ``now`` itself (a Stop just handled) counts.
        self._next_report(frame.dst_nwk, motor, now - 1e-9)

    def _next_report(self, nwk: int, motor: MotorSim, after: float) -> None:
        """Schedule the report of the first position the motor sends after ``after``.

        A report the motor has already sent is on its way and still arrives; one it has
        not sent yet is replaced, since the command just handled changed its travel.
        """
        loop = asyncio.get_running_loop()
        pending = self._report_timers.pop(nwk, None)
        if pending is not None:
            timer, sent_at = pending
            if sent_at <= loop.time():
                self._reports_in_flight[nwk, sent_at] = timer
            else:
                timer.cancel()
        sent_at = motor.next_report_at(after)
        if sent_at is not None:
            latency = (
                motor.reply_latency
                if motor.report_latency is None
                else motor.report_latency
            )
            lift = round(motor.position_at(sent_at))
            timer = loop.call_at(
                sent_at + latency, self._push_report, nwk, motor, sent_at, lift
            )
            self._report_timers[nwk] = (timer, sent_at)

    def _push_report(
        self, nwk: int, motor: MotorSim, sent_at: float, lift: int
    ) -> None:
        """Push the lift the motor sent at ``sent_at``, as the radio does.

        If it is the motor's latest report, schedule the next one.
        """
        pending = self._report_timers.get(nwk)
        latest = pending is not None and pending[1] == sent_at
        if latest:
            del self._report_timers[nwk]
        else:
            self._reports_in_flight.pop((nwk, sent_at), None)
        if self.motors.get(nwk) is not motor:
            return
        self.packet_received(
            report_packet(
                WindowCovering.cluster_id,
                WindowCovering.AttributeDefs.current_position_lift_percentage.id,
                lift,
                nwk=t.NWK(nwk),
            )
        )
        if latest:
            self._next_report(nwk, motor, sent_at)

    async def shutdown(self, *args: Any, **kwargs: Any) -> None:
        """Drop pending reports, then shut zigpy down."""
        for timer, _ in self._report_timers.values():
            timer.cancel()
        for timer in self._reports_in_flight.values():
            timer.cancel()
        self._report_timers.clear()
        self._reports_in_flight.clear()
        await super().shutdown(*args, **kwargs)

    async def load_network_info(self, *, load_devices: bool = False) -> None:
        """Report a fixed coordinator and network."""
        self.state.node_info.nwk = t.NWK(0x0000)
        self.state.node_info.ieee = COORDINATOR_IEEE
        self.state.node_info.logical_type = zdo_t.LogicalType.Coordinator
        self.state.network_info.pan_id = t.PanId(0x1234)
        self.state.network_info.extended_pan_id = t.ExtendedPanId(COORDINATOR_IEEE)
        self.state.network_info.channel = 15
        self.state.network_info.network_key.key = t.KeyData(range(16))

    async def start_network(self) -> None:
        """Make sure the coordinator device exists, as a real radio's startup does."""
        await self.load_network_info()
        if COORDINATOR_IEEE not in self.devices:
            coordinator = self.add_device(COORDINATOR_IEEE, t.NWK(0x0000))
            coordinator.node_desc = zdo_t.NodeDescriptor(
                logical_type=zdo_t.LogicalType.Coordinator
            )
            endpoint = coordinator.add_endpoint(1)
            endpoint.profile_id = zha_profile.PROFILE_ID
            endpoint.add_input_cluster(Basic.cluster_id)
            endpoint.add_input_cluster(Groups.cluster_id)

    async def connect(self) -> None:
        """No hardware to open."""

    async def disconnect(self) -> None:
        """No hardware to close."""

    async def force_remove(self, dev: zigpy.device.Device) -> None:
        """No hardware to update."""

    async def add_endpoint(self, descriptor: zdo_t.SimpleDescriptor) -> None:
        """No hardware to update."""

    async def permit_ncp(self, time_s: int = 60) -> None:
        """No hardware to update."""

    async def permit_with_link_key(
        self, node: t.EUI64, link_key: t.KeyData, time_s: int = 60
    ) -> None:
        """No hardware to update."""

    async def write_network_info(
        self, *, network_info: zigpy.state.NetworkInfo, node_info: zigpy.state.NodeInfo
    ) -> None:
        """No hardware to update."""

    async def reset_network_info(self) -> None:
        """No hardware to update."""

    def _persist_coordinator_model_strings_in_db(self) -> None:
        """No radio model strings to persist."""


def _reply_packet(request: t.ZigbeePacket, payload: bytes) -> t.ZigbeePacket:
    """Build the packet the shade sends back to the coordinator to answer ``request``."""
    return t.ZigbeePacket(
        src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=request.dst.address),
        src_ep=request.dst_ep,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0x0000)),
        dst_ep=request.src_ep,
        tsn=request.tsn,
        profile_id=request.profile_id,
        cluster_id=request.cluster_id,
        data=t.SerializableBytes(payload),
        lqi=255,
        rssi=-40,
    )


def add_shade(
    app: zigpy.application.ControllerApplication,
    *,
    initial_lift: int,
    ieee: t.EUI64 = SHADE_IEEE,
    nwk: t.NWK = SHADE_NWK,
) -> zigpy.device.Device:
    """Add an interviewed WM25/L-Z at the given lift (ZCL space) to ``app``.

    The device is not announced; ``app.device_initialized`` does that, as a join does.
    """
    device = app.add_device(ieee, nwk)
    device.node_desc = SHADE_NODE_DESCRIPTOR
    endpoint = device.add_endpoint(1)
    endpoint.profile_id = zha_profile.PROFILE_ID
    endpoint.device_type = zha_profile.DeviceType.WINDOW_COVERING_DEVICE
    endpoint.status = zigpy.endpoint.Status.ZDO_INIT
    for cluster_id in SHADE_INPUT_CLUSTERS:
        endpoint.add_input_cluster(cluster_id)
    for cluster_id in SHADE_OUTPUT_CLUSTERS:
        endpoint.add_output_cluster(cluster_id)

    # An interview sets these on the device; zigpy restores them from Basic's cache.
    device.manufacturer = SHADE_MANUFACTURER
    device.model = SHADE_MODEL
    endpoint.basic.update_attribute(
        Basic.AttributeDefs.manufacturer.id, SHADE_MANUFACTURER
    )
    endpoint.basic.update_attribute(Basic.AttributeDefs.model.id, SHADE_MODEL)
    covering = endpoint.window_covering
    for attribute_id, value in SHADE_COVERING_ATTRIBUTES.items():
        covering.update_attribute(attribute_id, value)
    covering.update_attribute(
        WindowCovering.AttributeDefs.current_position_lift_percentage.id,
        initial_lift,
    )

    device.last_seen = time.time()
    device.status = zigpy.device.Status.ENDPOINTS_INIT
    return device


def report_packet(
    cluster_id: int,
    attribute_id: int,
    value: Any,
    *,
    nwk: t.NWK = SHADE_NWK,
    tsn: int = 0x42,
) -> t.ZigbeePacket:
    """Build a Report Attributes frame a shade sends for one attribute of a cluster.

    The value is encoded with the attribute's type in the cluster's own definition.
    Hand it to the app's ``packet_received`` so zigpy's real report path handles it.
    """
    definition = zigpy.zcl.Cluster._registry[cluster_id].attributes[attribute_id]
    command = foundation.GeneralCommand.Report_Attributes
    header = foundation.ZCLHeader.general(
        tsn, command, direction=foundation.Direction.Server_to_Client
    )
    body = foundation.GENERAL_COMMANDS[command].schema(
        attribute_reports=[
            foundation.Attribute(
                attribute_id,
                foundation.TypeValue(
                    type=foundation.DataType.from_python_type(definition.type).type_id,
                    value=definition.type(value),
                ),
            )
        ]
    )
    return t.ZigbeePacket(
        src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=nwk),
        src_ep=1,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0x0000)),
        dst_ep=1,
        tsn=tsn,
        profile_id=zha_profile.PROFILE_ID,
        cluster_id=cluster_id,
        data=t.SerializableBytes(header.serialize() + body.serialize()),
        lqi=255,
        rssi=-40,
    )


async def seed_database(
    database: Path,
    *,
    initial_lift: int,
    ieee: t.EUI64 = SHADE_IEEE,
    nwk: t.NWK = SHADE_NWK,
) -> None:
    """Write an interviewed WM25/L-Z at the given lift (ZCL space) into a zigpy database.

    Call it again with another ``ieee`` and ``nwk`` to add a second shade.
    """
    app = await HarnessApp.new(HarnessApp.config_for(database), start_radio=False)
    try:
        app.device_initialized(
            add_shade(app, initial_lift=initial_lift, ieee=ieee, nwk=nwk)
        )
    finally:
        await app.shutdown()
