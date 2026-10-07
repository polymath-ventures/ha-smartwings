"""Offline check of docs/evidence/discovery_user.py, the issue #36 discovery script.

A real bellows ControllerApplication and a real zigpy device carry every frame until
bellows logs "Sending packet"; the radio call right after that is cut off, so nothing
leaves the process. A simulated Office Shade then answers through the application's
real packet_received(), as the radio would.
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

SCRIPT = Path(__file__).parents[1] / "docs" / "evidence" / "discovery_user.py"
OFFICE_SHADE = "60:83:da:ff:fe:a0:00:02"
OFFICE_NWK = 0x1234
MFR = 0x1002
SERVER = (0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102)
CLIENT = (0x0003, 0x0019)
DISCOVERY_IDS = {0x15, 0x11, 0x13}
ALLOWED_IDS = DISCOVERY_IDS | {0x00}
ATTRIBUTE_PAGE = 2  # the simulated shade returns at most this many per page
COMMAND_PAGE = 3

# (cluster, side, manufacturer) -> (attributes {id: (zcl type, value) or None when a
# read answers UNSUPPORTED_ATTRIBUTE}, commands received, commands generated).
# Any other server/client combination answers with empty lists, except that a
# manufacturer-specific frame gets UNSUP_MANUF_GENERAL_COMMAND.
SHADE = {
    (0x0000, "server", None): (
        {0x0000: (0x20, 8), 0x0004: (0x42, "Smartwings")},
        [],
        [],
    ),
    (0x0102, "server", None): (
        {
            0x0000: (0x30, 0),
            0x0007: (0x18, 3),
            0x0008: (0x20, 84),
            0x0009: None,
            0x0011: (0x21, 0xFFFF),
        },
        [0x00, 0x01, 0x02, 0x05],
        [],
    ),
    (0x0102, "server", MFR): ({0xF000: (0x20, 14)}, [0x40], [0x41]),
    (0x0019, "client", None): (
        {0x0000: (0x23, 0x1234), 0x0002: (0x23, 2)},
        [0x02, 0x05],
        [0x01, 0x03],
    ),
}


class RadioCutOffError(Exception):
    """Raised where bellows would hand the frame to the radio."""


def load_script():
    """Import the script fresh, as ZHA Toolkit re-imports local/user.py per call."""
    spec = importlib.util.spec_from_file_location("discovery_user", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _header(request: foundation.ZCLHeader, command_id: int) -> bytes:
    return foundation.ZCLHeader(
        frame_control=foundation.FrameControl(
            frame_type=foundation.FrameType.GLOBAL_COMMAND,
            is_manufacturer_specific=request.manufacturer is not None,
            direction=request.frame_control.direction.flip(),
            disable_default_response=1,
            reserved=0,
        ),
        manufacturer=request.manufacturer,
        tsn=request.tsn,
        command_id=command_id,
    ).serialize()


def _schema(command_id: int):
    return foundation.GENERAL_COMMANDS[command_id].schema


def shade_reply(packet: t.ZigbeePacket) -> bytes:
    """Answer one general frame as the simulated Office Shade."""
    hdr, rest = foundation.ZCLHeader.deserialize(packet.data.serialize())
    request, _ = _schema(hdr.command_id).deserialize(rest)
    side = (
        "server"
        if hdr.frame_control.direction == foundation.Direction.Client_to_Server
        else "client"
    )
    key = (packet.cluster_id, side, hdr.manufacturer)

    def default_response(status):
        return _header(hdr, 0x0B) + _schema(0x0B)(hdr.command_id, status).serialize()

    if packet.cluster_id in (0xFC01, 0xEF00):
        return default_response(foundation.Status.UNSUPPORTED_CLUSTER)
    if key not in SHADE and hdr.manufacturer is not None:
        return default_response(foundation.Status.UNSUP_MANUF_GENERAL_COMMAND)
    attributes, received, generated = SHADE.get(key, ({}, [], []))

    if hdr.command_id == 0x15:
        remaining = sorted(a for a in attributes if a >= request.start_attribute_id)
        page = remaining[: min(request.max_attribute_ids, ATTRIBUTE_PAGE)]
        records = [
            foundation.DiscoverAttributesExtendedResponseRecord(
                attrid=a,
                datatype=0x20 if attributes[a] is None else attributes[a][0],
                acl=foundation.AttributeAccessControl.READ,
            )
            for a in page
        ]
        payload = _schema(0x16)(len(remaining) == len(page), records)
        return _header(hdr, 0x16) + payload.serialize()
    if hdr.command_id in (0x11, 0x13):
        ids = received if hdr.command_id == 0x11 else generated
        remaining = sorted(c for c in ids if c >= request.start_command_id)
        page = remaining[: min(request.max_command_ids, COMMAND_PAGE)]
        payload = _schema(hdr.command_id + 1)(len(remaining) == len(page), page)
        return _header(hdr, hdr.command_id + 1) + payload.serialize()
    if hdr.command_id == 0x00:
        records = []
        for attrid in request.attribute_ids:
            if attributes.get(attrid) is None:
                records.append(
                    foundation.ReadAttributeRecord(
                        attrid, foundation.Status.UNSUPPORTED_ATTRIBUTE
                    )
                )
                continue
            zcl_type, value = attributes[attrid]
            python_type = foundation.DataType.from_type_id(zcl_type).python_type
            records.append(
                foundation.ReadAttributeRecord(
                    attrid,
                    foundation.Status.SUCCESS,
                    foundation.TypeValue(type=zcl_type, value=python_type(value)),
                )
            )
        return _header(hdr, 0x01) + _schema(0x01)(records).serialize()
    raise AssertionError(f"unexpected general command 0x{hdr.command_id:02X}")


@pytest.fixture
def app(monkeypatch):
    """Build a bellows application holding the Office Shade, cut off at the radio."""
    app = ControllerApplication({"device": {"path": "/dev/null"}})
    app._ezsp = SimpleNamespace(is_ezsp_running=True)
    app.controller_event.set()

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

    # What zigpy already knows: these must not be read again.
    endpoint.in_clusters[0x0000].update_attribute(0x0004, "Smartwings")
    endpoint.in_clusters[0x0102].update_attribute(0x0008, 84)
    endpoint.out_clusters[0x0019].update_attribute(0x0002, 2)
    return app


@pytest.fixture
def radio(app, monkeypatch):
    """Cut every frame off at bellows' radio call; let the simulated shade answer."""
    real_lookup = app.get_device_with_address
    real_send = app.send_packet
    # inject: cluster -> ZCL frames (with the TSN as "tt") delivered just before the
    # reply to the first frame sent on that cluster, as an unsolicited frame would be.
    state = SimpleNamespace(sending=False, drop=set(), silent=False, sent=[], inject={})

    def lookup(address):
        if state.sending:
            raise RadioCutOffError
        return real_lookup(address)

    async def send_packet(packet):
        state.sending = True
        try:
            await real_send(packet)
        except RadioCutOffError:
            pass
        finally:
            state.sending = False
        state.sent.append(packet)
        if state.silent or len(state.sent) in state.drop:
            return
        tsn = packet.data.serialize()[3 if packet.data.serialize()[0] & 0x04 else 1]
        frames = [
            bytes.fromhex(f.replace("tt", f"{tsn:02x}"))
            for f in state.inject.pop(packet.cluster_id, [])
        ]
        loop = asyncio.get_running_loop()
        for n, data in enumerate([*frames, shade_reply(packet)]):
            reply = t.ZigbeePacket(
                src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=OFFICE_NWK),
                src_ep=1,
                dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=0x0000),
                dst_ep=1,
                tsn=packet.tsn,
                profile_id=260,
                cluster_id=packet.cluster_id,
                data=t.SerializableBytes(data),
                lqi=200,
                rssi=-60,
            )
            if frames and n == len(frames):
                # The real reply comes a moment after any injected frames, so the
                # handler sees them first, on their own.
                loop.call_later(0.01, app.packet_received, reply)
            else:
                loop.call_soon(app.packet_received, reply)

    monkeypatch.setattr(app, "get_device_with_address", lookup)
    monkeypatch.setattr(app, "send_packet", send_packet)
    return state


@pytest.fixture
def command_calls(monkeypatch):
    """Make every Cluster.command() call fail, and record it."""
    calls = []

    def refuse(self, *args, **kwargs):
        calls.append((self, args, kwargs))
        raise AssertionError("command() must not be reached")

    monkeypatch.setattr(Cluster, "command", refuse)
    return calls


def _all_clusters(app):
    endpoint = app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE)).endpoints[1]
    return [*endpoint.in_clusters.values(), *endpoint.out_clusters.values()]


def _cache_state(app):
    return {
        (cluster.cluster_id, cluster.is_server): (
            dict(cluster._attr_cache._cache),
            set(cluster._attr_cache._unsupported),
        )
        for cluster in _all_clusters(app)
    }


def _frame(packet: t.ZigbeePacket) -> tuple[int, str]:
    """(cluster, ZCL bytes with the TSN shown as `tt`)."""
    data = packet.data.serialize()
    tsn_index = 3 if data[0] & 0x04 else 1
    shown = data.hex(" ").split(" ")
    shown[tsn_index] = "tt"
    return packet.cluster_id, " ".join(shown)


async def run_discovery(module, app, tmp_path):
    """Run the handler with a short timeout; return its event data and JSON."""
    module.OUTPUT_PATH = tmp_path / "discovery.json"
    module.FRAME_TIMEOUT = 0.05
    event_data = {}
    await module.user_discovery_run(
        app,
        None,
        t.EUI64.convert(OFFICE_SHADE),
        "user_discovery_run",
        None,
        None,
        {},
        event_data,
    )
    return event_data, json.loads(module.OUTPUT_PATH.read_text())


async def test_discovery_sends_only_discovery_and_read_frames(
    app, radio, command_calls, caplog, tmp_path
):
    """Every frame is a general 0x15/0x11/0x13/0x00; paging and reads are exact."""
    caplog.set_level(logging.DEBUG)
    cache_before = _cache_state(app)

    event_data, result = await run_discovery(load_script(), app, tmp_path)

    sent = [r.args[0] for r in caplog.records if r.msg == "Sending packet %r"]
    assert sent == radio.sent  # every frame reached bellows' radio call
    for packet in sent:
        hdr, _ = foundation.ZCLHeader.deserialize(packet.data.serialize())
        assert hdr.frame_control.frame_type == foundation.FrameType.GLOBAL_COMMAND
        assert hdr.command_id in ALLOWED_IDS
        assert hdr.manufacturer in (None, MFR)
        assert bool(hdr.frame_control.is_manufacturer_specific) == (
            hdr.manufacturer is not None
        )
        assert packet.dst == t.AddrModeAddress(
            addr_mode=t.AddrMode.NWK, address=OFFICE_NWK
        )
        assert packet.dst_ep == 1
    assert command_calls == []

    # The JSON names each frame with the bytes that went out.
    assert [f["zcl_sent"] for f in result["frames"]] == [
        p.data.serialize().hex(" ") for p in sent
    ]
    assert all(f["outcome"] == "reply" and f["attempt"] == 1 for f in result["frames"])

    frames = [_frame(p) for p in sent]
    # 10 clusters x 2 manufacturer modes x 3 discoveries, 3 extra pages, 7 reads.
    assert len(frames) == 70

    # Window Covering, server side: pages continue while discovery_complete is 0.
    assert [f for f in frames if f[0] == 0x0102] == [
        (0x0102, "00 tt 15 00 00 10"),
        (0x0102, "00 tt 15 08 00 10"),
        (0x0102, "00 tt 15 0a 00 10"),
        (0x0102, "00 tt 11 00 20"),
        (0x0102, "00 tt 11 03 20"),
        (0x0102, "00 tt 13 00 20"),
        (0x0102, "04 02 10 tt 15 00 00 10"),
        (0x0102, "04 02 10 tt 11 00 20"),
        (0x0102, "04 02 10 tt 13 00 20"),
        # Reads: 0x0008 is cached and skipped; 0xF000 was found only with 0x1002.
        (0x0102, "00 tt 00 00 00"),
        (0x0102, "00 tt 00 07 00"),
        (0x0102, "00 tt 00 09 00"),
        (0x0102, "00 tt 00 11 00"),
        (0x0102, "04 02 10 tt 00 00 f0"),
    ]
    assert frames[-1] == (0x0019, "18 tt 00 00 00")

    # The OTA client cluster is asked as a client: direction bit and no default rsp.
    assert [f for f in frames if f[0] == 0x0019] == [
        (0x0019, "18 tt 15 00 00 10"),
        (0x0019, "18 tt 11 00 20"),
        (0x0019, "18 tt 13 00 20"),
        (0x0019, "1c 02 10 tt 15 00 00 10"),
        (0x0019, "1c 02 10 tt 11 00 20"),
        (0x0019, "1c 02 10 tt 13 00 20"),
        (0x0019, "18 tt 00 00 00"),
    ]

    # Probes on clusters the shade does not advertise still get their reply recorded.
    probe = next(c for c in result["clusters"] if c["cluster"] == "0xFC01")
    assert probe["on_endpoint"] is False
    assert probe["discovery"]["no_manufacturer"]["attributes"]["reply"]["status"] == (
        "UNSUPPORTED_CLUSTER"
    )
    assert [f for f in frames if f[0] in (0xFC01, 0xEF00)] == [
        (cluster, frame)
        for cluster in (0xFC01, 0xEF00)
        for frame in (
            "00 tt 15 00 00 10",
            "00 tt 11 00 20",
            "00 tt 13 00 20",
            "04 02 10 tt 15 00 00 10",
            "04 02 10 tt 11 00 20",
            "04 02 10 tt 13 00 20",
        )
    ]

    # Results: what was found, and what each read returned.
    wc = next(c for c in result["clusters"] if c["cluster"] == "0x0102")
    assert [
        a["id"] for a in wc["discovery"]["manufacturer_0x1002"]["attributes"]["found"]
    ] == ["0xF000"]
    assert wc["discovery"]["no_manufacturer"]["commands_received"]["found"] == [
        "0x00",
        "0x01",
        "0x02",
        "0x05",
    ]
    reads = {
        (r["cluster"], r["attribute"], r["manufacturer"]): r for r in result["reads"]
    }
    assert reads["0x0102", "0x0008", None]["skipped"]
    assert reads["0x0102", "0x0009", None]["reply"]["records"] == [
        {"id": "0x0009", "status": "UNSUPPORTED_ATTRIBUTE", "status_code": "0x86"}
    ]
    assert reads["0x0102", "0xF000", "0x1002"]["reply"]["records"] == [
        {
            "id": "0xF000",
            "status": "SUCCESS",
            "status_code": "0x00",
            "datatype": "0x20",
            "value": 14,
        }
    ]
    assert result["summary"]["frames_sent"] == 70
    assert result["summary"]["reads_sent"] == 7
    assert result["summary"]["reads_skipped_cached"] == 3
    assert probe["discovery"]["no_manufacturer"]["attributes"]["outcome"] == (
        "Default_Response UNSUPPORTED_CLUSTER"
    )
    assert result["summary"]["stopped_early"] is None
    assert result["finished"] is not None
    assert event_data["discovery"] == result["summary"]

    # Nothing marked unsupported, nothing written to zigpy's cache, listener removed.
    assert _cache_state(app) == cache_before
    assert all(not cluster._attr_cache._unsupported for cluster in _all_clusters(app))
    assert not any(
        type(listener).__name__ == "Discovery"
        for listener, _ in app._listeners.values()
    )


async def test_zigpy_read_attributes_would_mark_unsupported(app, radio):
    """Control: zigpy's own read_attributes marks 0x0009 for the same answer."""
    wc = (
        app.get_device(ieee=t.EUI64.convert(OFFICE_SHADE))
        .endpoints[1]
        .in_clusters[0x0102]
    )
    assert not wc.is_attribute_unsupported(0x0009)

    await wc.read_attributes([0x0009])

    assert wc.is_attribute_unsupported(0x0009)


async def test_one_resend_after_a_timeout(app, radio, tmp_path):
    """An unanswered frame is re-sent once, unchanged but for a new TSN."""
    radio.drop = {1}

    _, result = await run_discovery(load_script(), app, tmp_path)

    first, second = result["frames"][:2]
    assert (first["outcome"], first["attempt"]) == ("timeout", 1)
    assert (second["outcome"], second["attempt"]) == ("reply", 2)
    assert first["tsn"] != second["tsn"]
    assert (
        _frame(radio.sent[0]) == _frame(radio.sent[1]) == (0x0000, "00 tt 15 00 00 10")
    )
    assert result["summary"]["stopped_early"] is None
    assert len(radio.sent) == 71


async def test_colliding_unsolicited_frames_are_not_taken_as_the_reply(
    app, radio, tmp_path
):
    """Frames on the same cluster and TSN that are not the expected reply are kept apart.

    Before the reply to the first OTA (0x0019, client side) frame, the shade sends
    three frames carrying the same TSN: an OTA Query Next Image Request (cluster-
    specific), a Read Attributes Response (wrong command) and a Discover Attributes
    Extended Response with a manufacturer code the request did not carry. zigpy itself
    matches the first of them to its pending request (same cluster, direction, TSN).
    """
    ota_query = "01 tt 01 00 02 10 00 00 02 00 00 00"
    read_rsp = "00 tt 01"
    wrong_manufacturer = "04 02 10 tt 16 01"
    radio.inject = {0x0019: [ota_query, read_rsp, wrong_manufacturer]}

    _, result = await run_discovery(load_script(), app, tmp_path)

    ota = next(f for f in result["frames"] if f["cluster"] == "0x0019")
    assert (ota["command_id"], ota["attempt"], ota["outcome"]) == ("0x15", 1, "reply")
    assert ota["reply"]["command"] == "Discover_Attribute_Extended_rsp"
    assert ota["reply"]["manufacturer"] is None
    assert [a["id"] for a in ota["reply"]["attributes"]] == ["0x0000", "0x0002"]
    # zigpy did take the OTA query as its reply; the handler kept waiting.
    assert "QueryNextImage" in ota["zigpy_matched"]
    unmatched = [(u["cluster"], u["raw"]) for u in result["unmatched_frames"]]
    tsn = f"{ota['tsn']:02x}"
    assert unmatched == [
        ("0x0019", f.replace("tt", tsn))
        for f in (ota_query, read_rsp, wrong_manufacturer)
    ]
    assert result["summary"]["frames_without_reply"] == 0
    assert len(radio.sent) == 70


async def test_stops_after_three_unanswered_frames(app, radio, tmp_path, caplog):
    """A silent shade gets three frames, then the run stops and says so."""
    radio.silent = True
    caplog.set_level(logging.INFO)

    event_data, result = await run_discovery(load_script(), app, tmp_path)

    assert [_frame(p) for p in radio.sent] == [(0x0000, "00 tt 15 00 00 10")] * 2 + [
        (0x0000, "00 tt 11 00 20")
    ]
    assert [f["outcome"] for f in result["frames"]] == ["timeout"] * 3
    assert "3 frames in a row" in result["summary"]["stopped_early"]
    assert event_data["discovery"]["frames_sent"] == 3
    assert any("discovery: summary" in r.getMessage() for r in caplog.records)
    assert all(not cluster._attr_cache._unsupported for cluster in _all_clusters(app))


async def test_refuses_any_other_device(app, radio):
    """The script will not address any shade but the Office Shade."""
    with pytest.raises(ValueError, match="Office Shade"):
        await load_script().user_discovery_run(
            app, None, "00:11:22:33:44:55:66:77", "x", None, None, {}, {}
        )
    assert radio.sent == []
