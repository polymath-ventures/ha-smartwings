"""SmartWings WM25/L-Z shades under ZHA: register the quirk, and say when it is not loaded.

Importing the integration registers the quirk in ZHA's quirk registry. The manifest does
not depend on ZHA, so Home Assistant imports the integration without waiting for ZHA,
normally before ZHA builds its devices.
"""

from homeassistant.components.zha import DOMAIN as ZHA_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .activation import ISSUE_UPSTREAM, QuirkActivation
from .const import DOMAIN
from .repairs_missing import ISSUE_ID, MissingQuirkIssue
from .shades import ShadeDirectory, is_removal_or_rename
from .zha_gateway import SIGNAL_ADD_ENTITIES, register_quirk

type SmartWingsConfigEntry = ConfigEntry[ShadeDirectory]

# The quirk's entries in ZHA's quirk registry; none if zha-quirks provides the quirk.
QUIRK_ENTRIES = register_quirk()


async def async_setup_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> bool:
    """Track the shades in ZHA, following ZHA's reloads and device changes."""
    if not (
        zha_entries := hass.config_entries.async_entries(
            ZHA_DOMAIN, include_ignore=False
        )
    ):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="zha_not_ready"
        )
    zha_entry = zha_entries[0]
    shades = entry.runtime_data = ShadeDirectory(hass)
    activation = QuirkActivation(hass, entry, zha_entry, shades, QUIRK_ENTRIES)
    missing_quirk = MissingQuirkIssue(hass, shades, activation.waiting)
    entry.async_on_unload(shades.async_stop)
    entry.async_on_unload(activation.async_unload)
    entry.async_on_unload(missing_quirk.async_delete)
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ADD_ENTITIES, shades.async_discover)
    )

    @callback
    def async_zha_state_changed() -> None:
        shades.async_zha_state_changed(zha_entry)

    entry.async_on_unload(zha_entry.async_on_state_change(async_zha_state_changed))
    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            shades.async_device_registry_updated,
            event_filter=is_removal_or_rename,
        )
    )
    activation.async_setup()
    # The reload decision first, so the issue waits for a reload it starts.
    shades.add_listener(activation.async_check)
    shades.add_listener(missing_quirk.async_update)
    shades.async_zha_state_changed(zha_entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> bool:
    """Unload the entry; its listeners are removed by async_on_unload."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> None:
    """Leave no Repairs issue behind."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    ir.async_delete_issue(hass, DOMAIN, ISSUE_UPSTREAM)
