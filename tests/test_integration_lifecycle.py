"""Unloading and reloading the integration."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import DATA_DISPATCHER, async_dispatcher_send

from custom_components.smartwings.zha_gateway import SIGNAL_ADD_ENTITIES
from tests.smartwings_helpers import (
    ENTRY_ID,
    directory,
    domain_issues,
    install,
    issue,
    zha_reloads,
)
from tests.zha_harness import SHADE_IEEE, ZhaHarness
from tests.zha_harness.harness import ZHA_ENTRY_ID

SHADE = str(SHADE_IEEE)


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
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """Unloaded: listeners gone, no discovery, ZHA's cover untouched."""
    zha_harness = zha_harness_shadowed
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
    """Reloaded: rebuilt from ZHA, with no duplicate listener, Repairs issue or reload."""
    hass = zha_harness.hass
    await install(zha_harness)
    installed = listener_counts(zha_harness)
    reloads = zha_reloads(zha_harness)

    assert await hass.config_entries.async_reload(ENTRY_ID)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(ENTRY_ID)
    assert entry.state is ConfigEntryState.LOADED
    assert listener_counts(zha_harness) == installed
    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert zha_reloads(zha_harness) == reloads
    assert domain_issues(zha_harness) == []
