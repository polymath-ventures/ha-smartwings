"""Offline check of docs/evidence/bench_user.py, the issue #42 test bench.

As in the discovery test, a real bellows ControllerApplication and a real zigpy device
carry every frame until bellows logs "Sending packet"; the radio call right after that
is cut off, so nothing leaves the process. A simulated Office Shade then answers through
the application's real packet_received(), as the radio would.
"""

import asyncio
import importlib.util
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from bellows.zigbee.application import ControllerApplication
import pytest
import zigpy.endpoint
import zigpy.types as t
from zigpy.zcl import Cluster, foundation
import zigpy.zdo.types as zdo_t

SCRIPT = Path(__file__).parents[1] / "docs" / "evidence" / "bench_user.py"
OFFICE_SHADE = "60:83:da:ff:fe:a0:00:02"
OFFICE_NWK = 0x1234
COORDINATOR = "00:12:4b:00:2a:3b:4c:5d"
MFR = 0x1002
SERVER = (0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102)
CLIENT = (0x0003, 0x0019)
MOVE = {"remote_ready": True, "may_go_down": True}
LOW = MOVE
READY = {"remote_ready": True}  # without may_go_down


class RadioCutOffError(Exception):
    """Raised where bellows would hand the frame to the radio."""


def load_script():
    """Import the script fresh, as ZHA Toolkit re-imports local/user.py per call."""
    spec = importlib.util.spec_from_file_location("bench_user", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(command_id: int):
    return foundation.GENERAL_COMMANDS[command_id].schema


class Shade:
    """The simulated Office Shade: its attributes and binding table."""

    def __init__(self) -> None:
        """Start from the values the box's zigbee.db holds."""
        # (cluster, attribute) -> (ZCL type, value); None answers UNSUPPORTED_ATTRIBUTE.
        self.attributes = {
            (0x0000, 0x0001): None,
            (0x0000, 0x0002): None,
            (0x0001, 0x0021): (0x20, 200),
            (0x0003, 0x0000): (0x21, 0),
            (0x0102, 0x0007): (0x18, 0x03),
            (0x0102, 0x0008): (0x20, 50),
            (0x0102, 0x0010): (0x21, 0x0000),
            (0x0102, 0x0011): (0x21, 0xFFFF),
            (0x0102, 0x0017): (0x18, 0x14),
        }
        self.read_only = {(0x0102, 0x0010), (0x0102, 0x0011)}
        self.bindings: list[zdo_t.Binding] = [
            zdo_t.Binding(
                SrcAddress=t.EUI64.convert(OFFICE_SHADE),
                SrcEndpoint=1,
                ClusterId=0x0001,
                DstAddress=zdo_t.MultiAddress(
                    addrmode=3, ieee=t.EUI64.convert(COORDINATOR), endpoint=1
                ),
            )
        ]

    def zcl(self, packet: t.ZigbeePacket) -> list[bytes]:
        """Answer one ZCL frame with its replies, in order (none, one or two)."""
        return [r for r in self._zcl(packet) if r is not None]

    def _zcl(self, packet: t.ZigbeePacket) -> list[bytes | None]:
        data = packet.data.serialize()
        hdr, rest = foundation.ZCLHeader.deserialize(data)
        cluster = packet.cluster_id

        def header(command_id, *, general=True, manufacturer=hdr.manufacturer):
            return foundation.ZCLHeader(
                frame_control=foundation.FrameControl(
                    frame_type=(
                        foundation.FrameType.GLOBAL_COMMAND
                        if general
                        else foundation.FrameType.CLUSTER_COMMAND
                    ),
                    is_manufacturer_specific=manufacturer is not None,
                    direction=foundation.Direction.Server_to_Client,
                    disable_default_response=1,
                    reserved=0,
                ),
                manufacturer=manufacturer,
                tsn=hdr.tsn,
                command_id=command_id,
            ).serialize()

        def default_response(status):
            return header(0x0B) + _schema(0x0B)(hdr.command_id, status).serialize()

        if hdr.frame_control.frame_type == foundation.FrameType.CLUSTER_COMMAND:
            if cluster == 0x0102:
                # As the firmware does (firmware-analysis.md §3): a manufacturer-
                # specific frame gets 0x81 only; otherwise SUCCESS (unless Disable
                # Default Response is set), then 0x81 with the same TSN.
                refused = default_response(foundation.Status.UNSUP_CLUSTER_COMMAND)
                if hdr.manufacturer is not None:
                    return [refused]
                if hdr.frame_control.disable_default_response:
                    return [refused]
                return [default_response(foundation.Status.SUCCESS), refused]
            if cluster == 0x0003 and hdr.command_id == 0x01:
                return [header(0x00, general=False) + t.uint16_t(4).serialize()]
            if cluster == 0x0004 and hdr.command_id == 0x02:
                return [header(0x02, general=False) + bytes([8, 0])]
            if cluster == 0x0005 and hdr.command_id == 0x06:
                return [header(0x06, general=False) + bytes([0x00, 16, 0, 0, 0])]
            if hdr.frame_control.disable_default_response:
                return []
            return [default_response(foundation.Status.SUCCESS)]

        request, _ = _schema(hdr.command_id).deserialize(rest)
        if hdr.command_id == 0x00:
            records = []
            for attrid in request.attribute_ids:
                entry = self.attributes.get((cluster, attrid))
                if entry is None:
                    records.append(
                        foundation.ReadAttributeRecord(
                            attrid, foundation.Status.UNSUPPORTED_ATTRIBUTE
                        )
                    )
                    continue
                python_type = foundation.DataType.from_type_id(entry[0]).python_type
                records.append(
                    foundation.ReadAttributeRecord(
                        attrid,
                        foundation.Status.SUCCESS,
                        foundation.TypeValue(
                            type=entry[0], value=python_type(entry[1])
                        ),
                    )
                )
            return [header(0x01) + _schema(0x01)(records).serialize()]
        if hdr.command_id == 0x02:
            (record,) = request.attributes
            key = (cluster, record.attrid)
            if key in self.read_only:
                status = foundation.WriteAttributesStatusRecord(
                    foundation.Status.READ_ONLY, record.attrid
                )
            else:
                self.attributes[key] = (record.value.type, record.value.value)
                status = foundation.WriteAttributesStatusRecord(
                    foundation.Status.SUCCESS
                )
            return [header(0x04) + _schema(0x04)([status]).serialize()]
        if hdr.command_id == 0x08:
            # No reporting engine: refused, as on the live shade (session A, 2026-10-06).
            return [default_response(foundation.Status.UNSUP_CLUSTER_COMMAND)]
        if hdr.command_id in (0x11, 0x13):
            ids = (
                [0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08]
                if hdr.command_id == 0x11
                else []
            )
            # The wildcard is answered without a manufacturer code: no extensions.
            manufacturer = None if hdr.manufacturer == 0xFFFF else hdr.manufacturer
            payload = _schema(hdr.command_id + 1)(True, ids).serialize()
            return [header(hdr.command_id + 1, manufacturer=manufacturer) + payload]
        if hdr.command_id == 0x15:
            records = [
                foundation.DiscoverAttributesExtendedResponseRecord(
                    attrid=attrid,
                    datatype=0x20,
                    acl=foundation.AttributeAccessControl.READ,
                )
                for (c, attrid) in sorted(self.attributes)
                if c == cluster
            ]
            return [header(0x16) + _schema(0x16)(True, records).serialize()]
        raise AssertionError(f"unexpected general command 0x{hdr.command_id:02X}")

    def zdo(self, packet: t.ZigbeePacket) -> bytes:
        """Answer one ZDO request."""
        data = packet.data.serialize()
        command = zdo_t.ZDOCmd(packet.cluster_id)
        args, _ = t.deserialize(data[1:], zdo_t.CLUSTERS[command][1])
        if command == zdo_t.ZDOCmd.Node_Desc_req:
            body = (
                bytes([0x00])
                + t.NWK(OFFICE_NWK).serialize()
                + bytes.fromhex("02 40 80 02 10 52 52 00 00 2c 52 00 00")
            )
        elif command == zdo_t.ZDOCmd.Power_Desc_req:
            body = bytes([0x00]) + t.NWK(OFFICE_NWK).serialize() + bytes([0x40, 0xC4])
        elif command == zdo_t.ZDOCmd.Mgmt_Bind_req:
            # One entry per page, so the bench must page through the table.
            (start,) = args
            page = self.bindings[start : start + 1]
            body = (
                bytes([0x00, len(self.bindings), start])
                + t.LVList[zdo_t.Binding, t.uint8_t](page).serialize()
            )
        else:
            raise AssertionError(f"unexpected ZDO request {command!r}")
        return data[:1] + body


@pytest.fixture
def app():
    """Build a bellows application holding the Office Shade, cut off at the radio."""
    app = ControllerApplication({"device": {"path": "/dev/null"}})
    app._ezsp = SimpleNamespace(is_ezsp_running=True)
    app.controller_event.set()
    app.state.node_info.ieee = t.EUI64.convert(COORDINATOR)

    device = app.add_device(t.EUI64.convert(OFFICE_SHADE), OFFICE_NWK)
    device.node_desc = zdo_t.NodeDescriptor(
        logical_type=zdo_t.LogicalType.EndDevice,
        complex_descriptor_available=0,
        user_descriptor_available=0,
        reserved=0,
        aps_flags=0,
        frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
        mac_capability_flags=zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress,
        manufacturer_code=MFR,
        maximum_buffer_size=82,
        maximum_incoming_transfer_size=82,
        server_mask=11264,
        maximum_outgoing_transfer_size=82,
        descriptor_capability_field=0,
    )
    endpoint = device.add_endpoint(1)
    endpoint.profile_id = 260
    for cluster_id in SERVER:
        endpoint.add_input_cluster(cluster_id)
    for cluster_id in CLIENT:
        endpoint.add_output_cluster(cluster_id)
    endpoint.status = zigpy.endpoint.Status.ZDO_INIT
    endpoint.in_clusters[0x0102].update_attribute(0x0008, 84)
    return app


@pytest.fixture
def radio(app, monkeypatch):
    """Cut every frame off at bellows' radio call; let the simulated shade answer."""
    real_lookup = app.get_device_with_address
    real_send = app.send_packet
    # inject: cluster -> frames (TSN shown as "tt") the shade sends just before its
    # reply to the next frame on that cluster, as an unsolicited frame would be.
    state = SimpleNamespace(
        sending=False,
        silent=False,
        sent=[],
        inject={},
        shade=Shade(),
        on_send=None,
        burst=False,
    )

    def lookup(address):
        if state.sending:
            raise RadioCutOffError
        return real_lookup(address)

    async def send_packet(packet):
        if state.on_send is not None:
            state.on_send(packet)
        state.sending = True
        try:
            await real_send(packet)
        except RadioCutOffError:
            pass
        finally:
            state.sending = False
        state.sent.append(packet)
        if state.silent:
            return
        zdo = packet.dst_ep == 0
        data = packet.data.serialize()
        if zdo:
            replies = [state.shade.zdo(packet)]
        else:
            tsn = data[3 if data[0] & 0x04 else 1]
            replies = [
                bytes.fromhex(f.replace("tt", f"{tsn:02x}"))
                for f in state.inject.pop(packet.cluster_id, [])
            ]
            replies += state.shade.zcl(packet)
        loop = asyncio.get_running_loop()
        for n, reply_data in enumerate(replies):
            reply = t.ZigbeePacket(
                src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=OFFICE_NWK),
                src_ep=0 if zdo else 1,
                dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=0x0000),
                dst_ep=0 if zdo else 1,
                tsn=packet.tsn,
                profile_id=0 if zdo else 260,
                cluster_id=packet.cluster_id | 0x8000 if zdo else packet.cluster_id,
                data=t.SerializableBytes(reply_data),
                lqi=200,
                rssi=-60,
            )
            # Each frame a moment after the one before, so the handler sees any
            # injected frames first, on their own.
            if state.burst:
                # Back to back, before the bench's coroutine can resume, as on the box.
                loop.call_soon(app.packet_received, reply)
            else:
                loop.call_later(0.005 * n, app.packet_received, reply)

    monkeypatch.setattr(app, "get_device_with_address", lookup)
    monkeypatch.setattr(app, "send_packet", send_packet)
    return state


@pytest.fixture
def bench(tmp_path):
    """Load the bench module fresh, writing to tmp_path, with short timeouts."""
    module = load_script()
    module.OUTPUT_DIR = tmp_path
    module.FRAME_TIMEOUT = 0.05
    module.LINGER_S = 0.05
    return module


async def call(bench, app, action, fields=None, *, ieee=OFFICE_SHADE, session="T"):
    """Run one bench action as ZHA Toolkit would; return its response."""
    data = {
        "command": f"user_bench_{action}",
        "ieee": ieee,
        "session": session,
        "test_id": "BENCH-TEST",
        "step": "S1",
        **(fields or {}),
    }
    event_data = {}
    await getattr(bench, f"user_bench_{action}")(
        app,
        None,
        t.EUI64.convert(ieee),
        data["command"],
        None,
        SimpleNamespace(data=data),
        {},
        event_data,
    )
    return event_data["bench"]


def session_file(tmp_path, session="T"):
    """Return the session JSON as written."""
    return json.loads((tmp_path / f"smartwings_bench_{session}.json").read_text())


def _frame(packet: t.ZigbeePacket) -> tuple[int, str]:
    """(cluster, frame bytes with the TSN shown as `tt`)."""
    data = packet.data.serialize()
    shown = data.hex(" ").split(" ")
    if packet.dst_ep != 0:
        shown[3 if data[0] & 0x04 else 1] = "tt"
    else:
        shown[0] = "tt"
    return packet.cluster_id, " ".join(shown)


def _cache_state(app):
    endpoint = app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE)).endpoints[1]
    return {
        (cluster.cluster_id, cluster.is_server): (
            dict(cluster._attr_cache._cache),
            set(cluster._attr_cache._unsupported),
        )
        for cluster in [*endpoint.in_clusters.values(), *endpoint.out_clusters.values()]
    }


OK = "Default Response SUCCESS (0x00)"
REFUSED = "Default Response UNSUP_CLUSTER_COMMAND (0x81)"
# (action, fields, [(cluster, bytes)], the answers in the response, in order)
CASES = [
    ("up_open", LOW, [(0x0102, "01 tt 00")], [OK]),
    ("down_close", LOW, [(0x0102, "01 tt 01")], [OK]),
    ("stop", {}, [(0x0102, "01 tt 02")], [OK]),
    ("stop", {"disable_default_response": True}, [(0x0102, "11 tt 02")], [REFUSED]),
    ("stop", {"manufacturer": MFR}, [(0x0102, "05 02 10 tt 02")], [REFUSED]),
    ("goto", {**MOVE, "value": 30}, [(0x0102, "01 tt 05 1e")], [OK]),
    ("goto", {**LOW, "value": 101}, [(0x0102, "01 tt 05 65")], [OK]),
    (
        "goto",
        {**MOVE, "value": 40, "idle_s": 0.01, "read_before_s": 0.01},
        [(0x0102, "00 tt 00 08 00"), (0x0102, "01 tt 05 28")],
        ["0x0008 = 50", OK],
    ),
    (
        "goto_then_stop",
        {**MOVE, "value": 30, "stop_after_s": 0.01},
        [(0x0102, "01 tt 05 1e"), (0x0102, "01 tt 02")],
        [OK, OK],
    ),
    (
        "goto_twice",
        {**MOVE, "value": 30, "gap_s": 0.01},
        [(0x0102, "01 tt 05 1e"), (0x0102, "01 tt 05 1e")],
        [OK, OK],
    ),
    (
        "goto_then_goto",
        {**MOVE, "value": 20, "then_value": 50, "after_s": 0.01},
        [(0x0102, "01 tt 05 14"), (0x0102, "01 tt 05 32")],
        [OK, OK],
    ),
    (
        "identify",
        {**MOVE, "identify_time": 5, "query_after_s": 0},
        [(0x0003, "01 tt 00 05 00"), (0x0003, "01 tt 01"), (0x0003, "00 tt 00 00 00")],
        [OK, 'identify_query_response: {"timeout": 4}', "0x0000 = 0"],
    ),
    (
        "read",
        {"cluster": 0x0000, "attributes": [0x0001, 0x0002]},
        [(0x0000, "00 tt 00 01 00"), (0x0000, "00 tt 00 02 00")],
        ["0x0001 UNSUPPORTED_ATTRIBUTE", "0x0002 UNSUPPORTED_ATTRIBUTE"],
    ),
    (
        "read",
        {"cluster": "0x0102", "attributes": 8, "trials": 2, "idle_s": 0.01},
        [(0x0102, "00 tt 00 08 00")] * 2,
        ["0x0008 = 50"] * 2,
    ),
    (
        "read",
        {"cluster": 0x0001, "attributes": [0x0021], "manufacturer": MFR},
        [(0x0001, "04 02 10 tt 00 21 00")],
        None,
    ),
    (
        "write",
        {
            "cluster": 0x0102,
            "attribute": 0x0017,
            "value": 0x14,
            "expect_before": 0x14,
            "confirm": True,
        },
        [(0x0102, "00 tt 00 17 00"), (0x0102, "00 tt 02 17 00 18 14")]
        + [(0x0102, "00 tt 00 17 00")],
        ["0x0017 = 20", "all SUCCESS", "0x0017 = 20"],
    ),
    (
        "write",
        {"cluster": 0x0102, "attribute": 0x0011, "value": 0xFFFF, "confirm": True},
        [(0x0102, "00 tt 00 11 00"), (0x0102, "00 tt 02 11 00 21 ff ff")]
        + [(0x0102, "00 tt 00 11 00")],
        ["0x0011 = 65535", "0x0011 READ_ONLY", "0x0011 = 65535"],
    ),
    (
        "read_reporting",
        {"cluster": 0x0102, "attributes": [0x0008]},
        [(0x0102, "00 tt 08 00 08 00")],
        [REFUSED],
    ),
    (
        "read_reporting",
        {"cluster": 0x0001, "attributes": [0x0021]},
        [(0x0001, "00 tt 08 00 21 00")],
        [REFUSED],
    ),
    (
        "discover",
        {"cluster": 0x0102, "kind": "commands_received", "manufacturer": 0xFFFF},
        [(0x0102, "04 ff ff tt 11 00 20")],
        ["0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08 (complete)"],
    ),
    (
        "discover",
        {"cluster": 0x0000, "kind": "commands_generated", "manufacturer": 0xFFFF},
        [(0x0000, "04 ff ff tt 13 00 20")],
        ["none (complete)"],
    ),
    (
        "discover",
        {"cluster": 0x0102, "kind": "attributes"},
        [(0x0102, "00 tt 15 00 00 10")],
        None,
    ),
    (
        "group_membership",
        {},
        [(0x0004, "01 tt 02 00")],
        ['get_membership_response: {"capacity": 8, "groups": []}'],
    ),
    ("scene_membership", {}, [(0x0005, "01 tt 06 00 00")], None),
    ("zdo", {"request": "power_descriptor"}, [(0x0003, "tt 34 12")], None),
    ("zdo", {"request": "node_descriptor"}, [(0x0002, "tt 34 12")], None),
    ("zdo", {"request": "binding_table"}, [(0x0033, "tt 00")], None),
    ("watch", {"for_s": 1}, [], []),
]


@pytest.mark.parametrize(("action", "fields", "frames", "answers"), CASES)
async def test_each_action_sends_exactly_its_frames(
    *, bench, app, radio, caplog, tmp_path, action, fields, frames, answers
):
    """Each action sends exactly the listed frames, once, and logs them all."""
    caplog.set_level(logging.DEBUG)
    cache_before = _cache_state(app)

    response = await call(bench, app, action, fields)

    sent = [r.args[0] for r in caplog.records if r.msg == "Sending packet %r"]
    assert sent == radio.sent  # every frame reached bellows' radio call
    assert [_frame(p) for p in sent] == frames
    for packet in sent:
        assert packet.dst == t.AddrModeAddress(
            addr_mode=t.AddrMode.NWK, address=OFFICE_NWK
        )
        assert packet.dst_ep == (0 if packet.profile_id == 0 else 1)

    doc = session_file(tmp_path)
    (logged,) = doc["calls"]
    assert logged["action"] == action
    assert logged["outcome"] == "done"
    assert [f["bytes_sent"] for f in logged["frames"]] == [
        p.data.serialize().hex(" ") for p in sent
    ]
    assert all(f["outcome"] == "reply" and f["time_reply"] for f in logged["frames"])
    # The only frames the shade sent unasked are second replies to bench frames.
    assert all("second_reply_to_frame" in u for u in logged["unmatched_frames"])
    if answers is not None:
        assert [f["answer"] for f in response["frames"]] == answers
    assert response["outcome"] == "done"
    assert response["log"] == str(tmp_path / "smartwings_bench_T.json")

    # Nothing marked unsupported or written to zigpy's cache; listener removed.
    assert _cache_state(app) == cache_before
    assert not any(
        type(listener).__name__ == "Bench" for listener, _ in app._listeners.values()
    )


async def test_second_reply_is_logged_and_tagged(bench, app, radio, tmp_path):
    """The shade's SUCCESS-then-0x81 pair: the first is the reply, the second is kept.

    The session A run of 2026-10-06 logged only the SUCCESS, because the call ended as
    soon as it matched. The call now listens for LINGER_S after its last frame.
    """
    response = await call(
        bench, app, "goto_then_stop", {**MOVE, "value": 30, "stop_after_s": 0}
    )

    assert [f["answer"] for f in response["frames"]] == [OK, OK]
    assert response["second_replies"] == [f"frame 1: {REFUSED}", f"frame 2: {REFUSED}"]
    unmatched = session_file(tmp_path)["calls"][0]["unmatched_frames"]
    assert [(u["second_reply_to_frame"], u["for_command"]) for u in unmatched] == [
        (1, "0x05"),
        (2, "0x02"),
    ]


@pytest.mark.parametrize(
    ("action", "command_id"),
    [("goto_lift_value", 0x04), ("tilt_value", 0x07), ("tilt_percentage", 0x08)],
)
async def test_never_sends_lift_value_or_tilt(
    *, bench, app, radio, tmp_path, action, command_id
):
    """0x04, 0x07 and 0x08 are refused, from the action and from the bench's core."""
    with pytest.raises(ValueError, match="never sent"):
        await call(bench, app, action, {**LOW, "value": 0})
    assert radio.sent == []
    assert not (tmp_path / "smartwings_bench_T.json").exists()

    # Even a direct call into the bench's frame builder refuses, before any frame.
    device = app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE))
    core = bench.Bench(
        app,
        device,
        "T",
        {"action": "direct", "test_id": "BENCH-TEST", "step": None, "fields": {}},
    )
    async with core:
        with pytest.raises(ValueError, match="never sent"):
            await core.command(0x0102, command_id, t.uint16_t(0))
    assert radio.sent == []
    assert (0x0102, command_id) not in bench.CLUSTER_COMMANDS


async def test_moot_actions_are_gone(bench):
    """Configure Reporting and binding are moot (firmware analysis §4): no actions."""
    for action in ("configure_reporting", "bind", "unbind"):
        assert not hasattr(bench, f"user_bench_{action}")
    assert bench.foundation.GeneralCommand.Configure_Reporting not in bench.RESPONSE_FOR
    assert bench.zdo_t.ZDOCmd.Bind_req not in bench.ZDO_ALLOWED
    assert bench.zdo_t.ZDOCmd.Unbind_req not in bench.ZDO_ALLOWED


async def test_stop_ask_for_ack_is_passed_to_the_radio(bench, app, radio):
    """`ask_for_ack` sets or clears the APS ACK option; the ZCL bytes do not change."""
    await call(bench, app, "stop", {"ask_for_ack": True})
    await call(bench, app, "stop", {"ask_for_ack": False})
    await call(bench, app, "stop")

    acked = [t.TransmitOptions.ACK in p.tx_options for p in radio.sent]
    assert acked == [True, False, False]
    assert {_frame(p) for p in radio.sent} == {(0x0102, "01 tt 02")}


async def test_write_records_the_undo(bench, app, radio, tmp_path):
    """A write records the value before, the value after and the exact undo."""
    response = await call(
        bench,
        app,
        "write",
        {"cluster": 0x0102, "attribute": 0x0017, "value": 0x15, "confirm": True},
    )

    result = response["result"]
    assert (result["before"], result["written"], result["after"]) == (0x14, 0x15, 0x15)
    assert result["undo_needed"] is True
    assert result["undo"] == "\n".join(
        [
            "action: zha_toolkit.execute",
            "data:",
            "  command: user_bench_write",
            f'  ieee: "{OFFICE_SHADE}"',
            '  session: "T"',
            '  test_id: "BENCH-TEST"',
            '  step: "S1-undo"',
            "  cluster: 0x0102",
            "  attribute: 0x0017",
            "  value: 0x14",
            "  confirm: true",
        ]
    )
    assert session_file(tmp_path)["calls"][0]["result"] == result

    # The undo, run as written, puts the value back.
    await call(
        bench,
        app,
        "write",
        {"cluster": 0x0102, "attribute": 0x0017, "value": 0x14, "confirm": True},
    )
    assert radio.shade.attributes[0x0102, 0x0017] == (0x18, 0x14)


async def test_read_only_write_needs_no_undo(bench, app, radio):
    """A refused write leaves the value as it was, and says no undo is needed."""
    response = await call(
        bench,
        app,
        "write",
        {"cluster": 0x0102, "attribute": 0x0010, "value": 0, "confirm": True},
    )
    assert response["result"]["write_answer"] == "0x0010 READ_ONLY"
    assert response["result"]["undo_needed"] is False


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"cluster": 0x0102, "attribute": 0x0017, "value": 0x15}, "confirm: true"),
        (
            {"cluster": 0x0102, "attribute": 0x0017, "value": 0x15, "confirm": "yes"},
            "true or false",
        ),
        (
            {"cluster": 0x0102, "attribute": 0x0008, "value": 0, "confirm": True},
            "not writable",
        ),
        (
            {"cluster": 0x0000, "attribute": 0x0010, "value": 1, "confirm": True},
            "not writable",
        ),
        (
            {"cluster": 0x0102, "attribute": 0x0017, "value": 0x100, "confirm": True},
            "from 0 to 255",
        ),
    ],
)
async def test_write_guard_refuses_before_sending(
    *, bench, app, radio, tmp_path, fields, message
):
    """Without `confirm: true`, or outside the writable list, nothing is sent."""
    with pytest.raises(ValueError, match=message):
        await call(bench, app, "write", fields)
    assert radio.sent == []
    assert not (tmp_path / "smartwings_bench_T.json").exists()


async def test_write_refused_when_the_value_before_is_unexpected(
    bench, app, radio, tmp_path
):
    """With `expect_before` and a different value on the shade, only the read is sent."""
    with pytest.raises(ValueError, match="not the expected 21; nothing was written"):
        await call(
            bench,
            app,
            "write",
            {
                "cluster": 0x0102,
                "attribute": 0x0017,
                "value": 0x14,
                "expect_before": 0x15,
                "confirm": True,
            },
        )
    assert [_frame(p) for p in radio.sent] == [(0x0102, "00 tt 00 17 00")]
    (logged,) = session_file(tmp_path)["calls"]
    assert logged["outcome"] == "refused"
    assert "nothing was written" in logged["message"]


async def test_write_refused_when_the_value_before_is_unread(bench, app, radio):
    """No value before means no undo, so nothing is written."""
    radio.silent = True
    with pytest.raises(ValueError, match="no undo; nothing was written"):
        await call(
            bench,
            app,
            "write",
            {"cluster": 0x0102, "attribute": 0x0017, "value": 0x15, "confirm": True},
        )
    assert [_frame(p) for p in radio.sent] == [(0x0102, "00 tt 00 17 00")]


@pytest.mark.parametrize(
    ("action", "fields", "message"),
    [
        ("up_open", {}, "remote_ready: true"),
        ("up_open", READY, "may_go_down: true"),
        ("down_close", READY, "may_go_down: true"),
        ("goto", {"value": 30}, "remote_ready: true"),
        ("goto", {**READY, "value": 30}, "may_go_down: true"),
        ("goto", {**READY, "value": 1}, "may_go_down: true"),
        ("goto_then_stop", {**READY, "value": 30, "stop_after_s": 1}, "may_go_down"),
        ("goto_twice", {**READY, "value": 30}, "may_go_down"),
        (
            "goto_then_goto",
            {**READY, "value": 0, "then_value": 0, "after_s": 1},
            "may_go_down",
        ),
        ("identify", READY, "may_go_down"),
        (
            "goto_then_stop",
            {**MOVE, "value": 30, "stop_after_s": 1, "stop_manufacturer": MFR},
            "unknown field",
        ),
        ("identify", {}, "remote_ready: true"),
        ("goto", {**MOVE, "value": 30, "remote_redy": True}, "unknown field"),
        (
            "read",
            {"cluster": 0x0019, "attributes": [0]},
            "not one the bench may address",
        ),
        (
            "read",
            {"cluster": 0x0006, "attributes": [0]},
            "not one the bench may address",
        ),
        ("zdo", {"request": "leave"}, "must be one of"),
    ],
)
async def test_move_guard_and_allow_lists_refuse_before_sending(
    *, bench, app, radio, tmp_path, action, fields, message
):
    """Moving commands need the owner's flags; unknown clusters and fields are refused."""
    with pytest.raises(ValueError, match=message):
        await call(bench, app, action, fields)
    assert radio.sent == []
    assert not (tmp_path / "smartwings_bench_T.json").exists()


async def test_refuses_any_other_device(bench, app, radio, tmp_path):
    """The bench will not address any shade but the Office Shade."""
    other = "00:11:22:33:44:55:66:77"
    app.add_device(t.EUI64.convert(other), 0x4321)
    with pytest.raises(ValueError, match="Office Shade"):
        await call(bench, app, "stop", ieee=other)
    assert radio.sent == []
    assert list(tmp_path.iterdir()) == []


async def test_binding_table_is_read_page_by_page(bench, app, radio):
    """Mgmt_Bind_req is a read: one page per call, from `start_index`."""
    first = await call(bench, app, "zdo", {"request": "binding_table"})
    second = await call(
        bench, app, "zdo", {"request": "binding_table", "start_index": 1}
    )

    assert [_frame(p) for p in radio.sent] == [(0x0033, "tt 00"), (0x0033, "tt 01")]
    assert "BindingTableEntries" in first["frames"][0]["answer"]
    assert second["outcome"] == "done"


async def test_colliding_frames_are_not_taken_as_the_reply(bench, app, radio, tmp_path):
    """Frames on the same cluster and TSN that are not Stop's reply are kept apart.

    Before the reply, the shade sends four frames with the same TSN: a cluster-specific
    command zigpy cannot parse, an attribute report, a Default Response naming another
    command, and a Default Response with a manufacturer code Stop did not carry.
    """
    unparsable = "09 tt 05 00"
    report = "18 tt 0a 08 00 20 32"
    other_command = "18 tt 0b 05 00"
    wrong_manufacturer = "1c 02 10 tt 0b 02 81"
    radio.inject = {0x0102: [unparsable, report, other_command, wrong_manufacturer]}

    response = await call(bench, app, "stop")

    (frame,) = session_file(tmp_path)["calls"][0]["frames"]
    assert frame["outcome"] == "reply"
    assert frame["reply"]["command"] == "Default_Response"
    assert frame["reply"]["for_command"] == "0x02"
    assert frame["reply"]["status"] == "SUCCESS"
    assert frame["reply"]["manufacturer"] is None
    assert "zigpy_error" in frame or "zigpy_matched" in frame
    unmatched = session_file(tmp_path)["calls"][0]["unmatched_frames"]
    tsn = f"{frame['tsn']:02x}"
    expected = [unparsable, report, other_command, wrong_manufacturer]
    # The four colliding frames, then the shade's second reply (0x81) to Stop.
    assert [u["raw"] for u in unmatched[:4]] == [f.replace("tt", tsn) for f in expected]
    assert all("second_reply_to_frame" not in u for u in unmatched[:4])
    assert unmatched[4]["second_reply_to_frame"] == 1
    assert all(u["time"] for u in unmatched)
    assert response["reports"] == [
        {
            "t_s": unmatched[1]["t_s"],
            "cluster": "0x0102",
            "reports": [{"id": "0x0008", "datatype": "0x20", "value": 50}],
        }
    ]
    assert response["frames_from_shade_unasked"] == 5
    assert len(radio.sent) == 1


async def test_watch_reads_and_logs_reports(bench, app, radio):
    """A watch reads 0x0008 on its schedule and lists the reports it heard."""
    radio.inject = {0x0102: ["18 tt 0a 08 00 20 32"]}

    response = await call(bench, app, "watch", {"for_s": 1, "every_s": 1})

    assert [_frame(p) for p in radio.sent] == [(0x0102, "00 tt 00 08 00")]
    assert response["result"]["positions"][0]["lift"] == 50
    assert [r["reports"][0]["value"] for r in response["reports"]] == [50]


async def test_no_resend_and_stop_after_three_unanswered(bench, app, radio):
    """retries=0: one packet per frame; three unanswered frames end the call."""
    radio.silent = True

    response = await call(bench, app, "stop")
    assert response["frames"][0]["outcome"] == "timeout"
    assert response["frames"][0]["answer"] == "no reply within 0.05 s"
    assert len(radio.sent) == 1

    response = await call(
        bench, app, "read", {"cluster": 0x0102, "attributes": [7, 8, 0x10, 0x11]}
    )
    assert len(radio.sent) == 4  # 1 + 3: the fourth read was never sent
    assert response["outcome"] == "stopped early"
    assert "3 frames in a row" in response["message"]


async def test_calls_append_to_one_session_file(bench, app, radio, tmp_path):
    """Calls append to the session file; frames are numbered across the session."""
    await call(bench, app, "stop")
    await call(bench, app, "read", {"cluster": 0x0102, "attributes": [8]})
    await call(bench, app, "stop", session="other")

    doc = session_file(tmp_path)
    assert doc["ieee"] == OFFICE_SHADE
    assert doc["bench_version"] == bench.BENCH_VERSION == "2"
    assert [c["n"] for c in doc["calls"]] == [1, 2]
    assert [f["n"] for c in doc["calls"] for f in c["frames"]] == [1, 2]
    assert doc["calls"][0]["frames"][0]["idle_before_s"] is None
    assert doc["calls"][1]["frames"][0]["idle_before_s"] >= 0
    assert doc["calls"][0]["fields"] == {}
    assert doc["calls"][1]["fields"] == {"cluster": 0x0102, "attributes": [8]}
    assert doc["zigpy_cache_at_start"]["0x0102"]["values"] == {"0x0008/None": 84}
    assert len(session_file(tmp_path, "other")["calls"]) == 1


async def test_refuses_a_damaged_session_file_and_a_busy_bench(
    bench, app, radio, tmp_path
):
    """A session file that is not the bench's is never overwritten; one call at a time."""
    (tmp_path / "smartwings_bench_T.json").write_text("not json")
    with pytest.raises(ValueError, match="not a bench session file"):
        await call(bench, app, "stop")
    assert (tmp_path / "smartwings_bench_T.json").read_text() == "not json"

    app._smartwings_bench_busy = True
    with pytest.raises(ValueError, match="still running"):
        await call(bench, app, "stop", session="U")
    assert radio.sent == []


async def test_reads_never_mark_attributes_unsupported(bench, app, radio):
    """UNSUPPORTED_ATTRIBUTE is recorded as the answer; zigpy's cache is untouched.

    tests/test_discovery_user_script.py holds the control: zigpy's own read_attributes
    marks the attribute unsupported for the same answer.
    """
    basic = (
        app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE)).endpoints[1].in_clusters[0]
    )

    response = await call(bench, app, "read", {"cluster": 0, "attributes": [1]})

    assert response["frames"][0]["answer"] == "0x0001 UNSUPPORTED_ATTRIBUTE"
    assert not basic.is_attribute_unsupported(0x0001)
    assert isinstance(basic, Cluster)


async def test_only_a_goto_to_lift_0_moves_without_may_go_down(bench, app, radio):
    """A go-to to fully open is the one move that cannot go down by design."""
    response = await call(bench, app, "goto", {**READY, "value": 0})
    assert response["outcome"] == "done"
    assert [_frame(p) for p in radio.sent] == [(0x0102, "01 tt 05 00")]


async def test_concurrent_calls_second_is_refused(bench, app, radio, tmp_path):
    """The bench is claimed before any await, so two calls cannot both send."""
    load = bench.Bench._load

    async def slow_load(self):
        await asyncio.sleep(0.05)  # the session file read yields to the event loop
        return await load(self)

    bench.Bench._load = slow_load
    results = await asyncio.gather(
        call(bench, app, "stop"),
        call(bench, app, "stop", session="U"),
        return_exceptions=True,
    )

    refused = [r for r in results if isinstance(r, Exception)]
    assert len(refused) == 1
    assert "still running" in str(refused[0])
    assert len(radio.sent) == 1
    assert not getattr(app, "_smartwings_bench_busy", False)


async def test_frame_is_saved_before_it_is_sent(bench, app, radio, tmp_path):
    """An interrupted call leaves the frame it was sending in the session file."""
    seen = []

    def on_send(packet):
        doc = session_file(tmp_path)
        seen.append(doc["calls"][-1]["frames"][-1])

    radio.on_send = on_send
    await call(bench, app, "stop")

    (frame,) = seen
    assert frame["outcome"] == "sending"
    assert frame["bytes_sent"] == radio.sent[0].data.serialize().hex(" ")
    assert session_file(tmp_path)["calls"][0]["frames"][0]["outcome"] == "reply"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"bench_version": "1"}, "bench version 1"),
        ({"session": "Z"}, "session Z"),
        ({"ieee": "00:11:22:33:44:55:66:77"}, "00:11:22:33:44:55:66:77"),
    ],
)
async def test_refuses_a_session_file_of_another_bench_session_or_shade(
    *, bench, app, radio, tmp_path, change, message
):
    """Calls append only to a file this bench version wrote for this session and shade."""
    await call(bench, app, "stop")
    path = tmp_path / "smartwings_bench_T.json"
    doc = json.loads(path.read_text())
    doc.update(change)
    path.write_text(json.dumps(doc))
    radio.sent.clear()

    with pytest.raises(ValueError, match=message):
        await call(bench, app, "stop")
    assert radio.sent == []
    assert json.loads(path.read_text()) == doc


async def test_second_reply_tag_is_limited_to_its_window(bench, app, radio, tmp_path):
    """A frame with an answered frame's TSN is tagged only within the window."""
    bench.SECOND_REPLY_WINDOW_S = 0

    response = await call(bench, app, "stop")

    assert response["second_replies"] == []
    (unmatched,) = session_file(tmp_path)["calls"][0]["unmatched_frames"]
    assert unmatched["for_command"] == "0x02"
    assert "second_reply_to_frame" not in unmatched


async def test_bench_stays_claimed_until_the_final_save(bench, app, radio, tmp_path):
    """A call that enters while the first is writing its final save is refused."""
    save = bench.Bench._save
    second, tried = [], []

    async def save_and_try_another(self):
        if self.call["outcome"] != "running" and not tried:
            tried.append(True)
            try:
                second.append(await call(bench, app, "stop", session="U"))
            except ValueError as err:
                second.append(err)
        return await save(self)

    bench.Bench._save = save_and_try_another
    first = await call(bench, app, "stop")

    assert first["outcome"] == "done"
    (refused,) = second
    assert isinstance(refused, ValueError)
    assert "still running" in str(refused)
    assert len(radio.sent) == 1
    assert not app._smartwings_bench_busy


async def test_bench_is_released_when_the_final_save_fails(bench, app, radio):
    """A failing final save still releases the bench for the next call."""
    save = bench.Bench._save

    async def failing_final_save(self):
        if self.call["outcome"] != "running":
            raise OSError("disk full")
        return await save(self)

    bench.Bench._save = failing_final_save
    with pytest.raises(OSError, match="disk full"):
        await call(bench, app, "stop")
    assert not app._smartwings_bench_busy


async def test_second_reply_back_to_back_is_tagged(bench, app, radio, tmp_path):
    """A 0x81 arriving right after the SUCCESS, before the bench resumes, is tagged.

    On the box (session B, 2026-10-06) the second reply came 7-8 ms after the first,
    and three were left untagged.
    """
    radio.burst = True

    response = await call(
        bench, app, "goto_then_stop", {**MOVE, "value": 30, "stop_after_s": 0}
    )

    assert response["second_replies"] == [f"frame 1: {REFUSED}", f"frame 2: {REFUSED}"]


async def test_bench_stays_claimed_while_a_cancelled_final_save_finishes(
    bench, app, radio
):
    """Cancelling a call during its final save does not free the bench mid-write."""
    save = bench.Bench._save
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_final_save(self):
        if self.session == "T" and self.call["outcome"] != "running":
            started.set()
            await release.wait()  # the executor write is still running
        return await save(self)

    bench.Bench._save = slow_final_save
    first = asyncio.ensure_future(call(bench, app, "stop"))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    try:
        with pytest.raises(ValueError, match="still running"):
            await call(bench, app, "stop", session="U")
        assert len(radio.sent) == 1
    finally:
        release.set()
    for _ in range(100):
        if not app._smartwings_bench_busy:
            break
        await asyncio.sleep(0.01)
    assert not app._smartwings_bench_busy
    bench.Bench._save = save
    assert (await call(bench, app, "stop", session="U"))["outcome"] == "done"
