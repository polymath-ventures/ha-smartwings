"""Tests for the real-ZHA test harness itself (issue #5)."""

from pathlib import Path

import zha.quirks
import zhaquirks
from zhaquirks.smartwings.wm25lz import WM25LBlinds
import zigpy.types as t
from zigpy.zcl.clusters.closures import WindowCovering
import zigpy.zdo.types as zdo_t

from tests.zha_harness import (
    SHADE_IEEE,
    SHADE_NWK,
    HarnessApp,
    decode_frame,
    seed_database,
)

LIFT = WindowCovering.AttributeDefs.current_position_lift_percentage


async def test_seeded_database_reloads_as_the_vendor_quirk(tmp_path: Path) -> None:
    """A seeded zigpy database reloads the shade, and ZHA's resolver applies the stock quirk."""
    db = tmp_path / "zigbee.db"
    await seed_database(db, initial_lift=37)

    zhaquirks.setup()
    app = await HarnessApp.new(
        HarnessApp.config_for(db),
        start_radio=False,
        device_resolver=zha.quirks.DEVICE_REGISTRY.resolve,
    )
    try:
        device = app.get_device(SHADE_IEEE)

        assert isinstance(device, WM25LBlinds)
        assert (device.manufacturer, device.model) == ("Smartwings", "WM25/L-Z")
        assert device.node_desc.logical_type == zdo_t.LogicalType.EndDevice
        assert device.endpoints[1].window_covering.get(LIFT.id) == 37
    finally:
        await app.shutdown()


async def test_frames_are_captured_as_sent_on_the_wire(tmp_path: Path) -> None:
    """The stock quirk's up_open leaves zigpy as down_close (0x01): its swap, decoded."""
    db = tmp_path / "zigbee.db"
    await seed_database(db, initial_lift=37)

    zhaquirks.setup()
    app = await HarnessApp.new(
        HarnessApp.config_for(db),
        start_radio=False,
        device_resolver=zha.quirks.DEVICE_REGISTRY.resolve,
    )
    try:
        cover = app.get_device(SHADE_IEEE).endpoints[1].window_covering
        await cover.up_open(expect_reply=False)

        [frame] = app.frames
        assert (frame.cluster_id, frame.general, frame.command_id) == (
            0x0102,
            False,
            0x01,
        )
    finally:
        await app.shutdown()


def test_undecodable_frames_are_still_captured() -> None:
    """A frame for a cluster zigpy does not know is kept with its header, not lost."""
    packet = t.ZigbeePacket(
        src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=t.NWK(0)),
        src_ep=1,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=SHADE_NWK),
        dst_ep=1,
        tsn=1,
        profile_id=0x0104,
        cluster_id=0xFC99,
        data=t.SerializableBytes(b"\x05\x34\x12\x07\x42"),
    )

    frame = decode_frame(packet)

    # Header: manufacturer-specific cluster command 0x42, TSN 7; no schema, so no args.
    assert (
        frame.cluster_id,
        frame.dst_nwk,
        frame.tsn,
        frame.command_id,
        frame.args,
    ) == (
        0xFC99,
        SHADE_NWK,
        0x07,
        0x42,
        {},
    )
