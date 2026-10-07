"""Tests for the harness with real Home Assistant and real ZHA (issue #5, phase 3)."""

from homeassistant.const import STATE_UNAVAILABLE

from tests.zha_harness import ZhaHarness

# A custom quirk for the same signature with the stock up/down swap removed. Supplied
# through ZHA's custom_quirks_path, it must replace the vendor quirk at startup.
UNSWAPPED_QUIRK = '''
"""Test-only quirk: the vendor signature with a plain WindowCovering."""

from zhaquirks.smartwings.wm25lz import WM25LBlinds
from zigpy.zcl.clusters.closures import WindowCovering


class UnswappedBlinds(WM25LBlinds):
    """Same device, no up/down swap."""

    replacement = {
        **WM25LBlinds.replacement,
        "endpoints": {
            1: {
                **WM25LBlinds.replacement["endpoints"][1],
                "input_clusters": [
                    *WM25LBlinds.replacement["endpoints"][1]["input_clusters"][:-1],
                    WindowCovering.cluster_id,
                ],
            }
        },
    }
'''


async def test_real_zha_creates_the_cover_from_the_seeded_database(
    zha_harness: ZhaHarness,
) -> None:
    """ZHA builds an available cover showing the seeded lift in HA's position space."""
    state = zha_harness.hass.states.get(zha_harness.cover_entity_id)

    assert state is not None
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["current_position"] == 100 - 40


async def test_open_cover_sends_the_vendor_quirk_frame(zha_harness: ZhaHarness) -> None:
    """cover.open_cover on the stock quirk puts down_close (0x01) on the wire: its swap."""
    zha_harness.frames.clear()

    await zha_harness.call(
        "cover", "open_cover", {"entity_id": zha_harness.cover_entity_id}
    )

    [frame] = zha_harness.shade_frames()
    assert (frame.cluster_id, frame.general, frame.command_id) == (0x0102, False, 0x01)


async def test_custom_quirks_path_is_applied_at_startup(
    zha_harness: ZhaHarness,
) -> None:
    """A quirk dropped into custom_quirks_path takes over after a restart."""
    (zha_harness.custom_quirks_path / "unswapped.py").write_text(UNSWAPPED_QUIRK)
    await zha_harness.restart()
    zha_harness.frames.clear()

    await zha_harness.call(
        "cover", "open_cover", {"entity_id": zha_harness.cover_entity_id}
    )

    [frame] = zha_harness.shade_frames()
    assert (frame.cluster_id, frame.general, frame.command_id) == (0x0102, False, 0x00)
