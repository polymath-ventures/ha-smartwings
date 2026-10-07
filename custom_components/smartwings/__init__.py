"""SmartWings WM25/L-Z shades under ZHA: install the quirk, and say when it is not loaded."""

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .installer import ALL_ISSUES as INSTALLER_ISSUES, QuirkInstaller
from .repairs_missing import ISSUE_ID, MissingQuirkIssue
from .shades import ShadeDirectory, is_removal_or_rename
from .zha_gateway import SIGNAL_ADD_ENTITIES, async_gateway

__all__ = ["DOMAIN"]

type SmartWingsConfigEntry = ConfigEntry[ShadeDirectory]


async def async_setup_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> bool:
    """Track the shades in ZHA's gateway, following ZHA's reloads and device changes."""
    if (gateway := async_gateway(hass)) is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="zha_not_ready"
        )
    shades = entry.runtime_data = ShadeDirectory(hass)
    installer = QuirkInstaller(hass, entry, shades)
    entry.async_on_unload(installer.async_unload)
    missing_quirk = MissingQuirkIssue(hass, shades, installer.async_restart_pending)
    entry.async_on_unload(shades.async_stop)
    entry.async_on_unload(missing_quirk.async_delete)
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_ADD_ENTITIES, shades.async_discover)
    )
    zha_entry = gateway.config_entry

    @callback
    def async_zha_state_changed() -> None:
        shades.async_zha_state_changed(zha_entry)
        if zha_entry.state is ConfigEntryState.LOADED:
            installer.async_zha_loaded()

    entry.async_on_unload(zha_entry.async_on_state_change(async_zha_state_changed))
    entry.async_on_unload(
        hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            shades.async_device_registry_updated,
            event_filter=is_removal_or_rename,
        )
    )
    shades.async_discover()
    await installer.async_reconcile()
    # Only now, so a quirk just installed is reported as a restart request instead.
    shades.add_listener(missing_quirk.async_update)
    installer.add_listener(missing_quirk.async_update)
    missing_quirk.async_update()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> bool:
    """Unload the entry; its listeners are removed by async_on_unload."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: SmartWingsConfigEntry) -> None:
    """Leave no Repairs issue behind; the installed quirk file stays for ZHA."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    for issue_id in INSTALLER_ISSUES:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
