"""Unload, reload and independence from the old install (issue #11)."""

import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import DATA_DISPATCHER, async_dispatcher_send

from custom_components.smartwings.zha_gateway import SIGNAL_ADD_ENTITIES
from tests.smartwings_helpers import ENTRY_ID, directory, domain_issues, install, issue
from tests.zha_harness import SHADE_IEEE, ZhaHarness
from tests.zha_harness.harness import ZHA_ENTRY_ID

SHADE = str(SHADE_IEEE)
INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "smartwings"
OLD_HELPER = "input_number.smartwings_office_closed_position"
OLD_CALIBRATION = "smartwings_calibration.json"


def listener_counts(harness: ZhaHarness) -> tuple[int, int, int]:
    """Count the listeners the integration registers on ZHA, the bus and ZHA's entry."""
    hass = harness.hass
    zha_entry = hass.config_entries.async_get_entry(ZHA_ENTRY_ID)
    return (
        len(hass.data[DATA_DISPATCHER].get(SIGNAL_ADD_ENTITIES, {})),
        hass.bus.async_listeners().get(dr.EVENT_DEVICE_REGISTRY_UPDATED, 0),
        len(zha_entry._on_state_change or []),
    )


async def test_after_unload_zha_signals_trigger_nothing(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """Unloaded: listeners gone, no discovery, ZHA's cover untouched."""
    zha_harness = zha_harness_without_quirks_path
    hass = zha_harness.hass
    before = listener_counts(zha_harness)
    shades = await install(zha_harness)
    assert listener_counts(zha_harness) == tuple(count + 1 for count in before)
    assert issue(zha_harness) is not None
    cover = zha_harness.cover_entity_id
    cover_entry = er.async_get(hass).async_get(cover)

    assert await hass.config_entries.async_unload(ENTRY_ID)
    async_dispatcher_send(hass, SIGNAL_ADD_ENTITIES)
    await hass.async_block_till_done()

    assert listener_counts(zha_harness) == before
    assert shades.shades == {}
    assert domain_issues(zha_harness) == []
    assert er.async_get(hass).async_get(cover) == cover_entry
    state = hass.states.get(cover)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE


async def test_reloading_the_entry_leaves_one_set_of_listeners(
    zha_harness: ZhaHarness,
) -> None:
    """Reloaded: rebuilt from ZHA, with no duplicate listener or Repairs issue."""
    hass = zha_harness.hass
    await install(zha_harness)
    installed = listener_counts(zha_harness)

    assert await hass.config_entries.async_reload(ENTRY_ID)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(ENTRY_ID)
    assert entry.state is ConfigEntryState.LOADED
    assert listener_counts(zha_harness) == installed
    assert directory(zha_harness).shades[SHADE].quirk_active is False
    # The quirk the setup installed still waits for ZHA to load it, and the restart
    # request stands in for the missing-quirk issue (#18).
    assert domain_issues(zha_harness) == ["restart_required"]


async def test_the_old_install_changes_nothing(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """The old helpers and calibration file are neither used nor touched (§3i)."""
    zha_harness = zha_harness_without_quirks_path
    hass = zha_harness.hass
    calibration = zha_harness.config_dir / OLD_CALIBRATION
    calibration.write_text(json.dumps({SHADE: {"closed_position": 14}}))
    calibration_stat = calibration.stat()
    hass.states.async_set(OLD_HELPER, "14")
    helper_state = hass.states.get(OLD_HELPER)

    shades = await install(zha_harness)

    assert shades.shades[SHADE].quirk_active is False
    assert issue(zha_harness) is not None
    assert "14" not in issue(zha_harness).translation_placeholders["shades"]
    assert hass.states.get(OLD_HELPER) == helper_state
    assert calibration.read_text() == json.dumps({SHADE: {"closed_position": 14}})
    assert calibration.stat().st_mtime_ns == calibration_stat.st_mtime_ns


def test_the_integration_carries_none_of_the_old_codes_couplings() -> None:
    """D7's drop list: class-name detection, quirk registration, entity-id rewriting."""
    source = "\n".join(path.read_text() for path in INTEGRATION_DIR.rglob("*.py"))

    for dropped in (
        "SmartWingsWM25LZCover",
        "ReadbackWindowCoveringCluster",
        "PENDING_LEGACY_QUIRKS",
        "_handler_already_supplied",
        "_LEGACY_ENTITY_ID_RE",
        "reconcile_entity_id",
        "input_number",
        OLD_CALIBRATION,
    ):
        assert dropped not in source, dropped
