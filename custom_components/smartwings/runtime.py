"""Everything that needs ZHA's libraries: registering the quirk, and following the shades.

Home Assistant sets the integration up without waiting for ZHA (the manifest does not
depend on it), so ``async_register_quirk`` normally runs before ZHA builds its devices.
"""

from dataclasses import dataclass
import logging

from homeassistant.components.zha.const import CONF_ENABLE_QUIRKS
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey
import voluptuous as vol

from .activation import QuirkActivation
from .const import DOMAIN, ZHA_DOMAIN
from .repairs_missing import MissingQuirkIssue
from .shades import ShadeDirectory, is_removal_or_rename
from .zha_gateway import SIGNAL_ADD_ENTITIES, QuirkRegistryEntry, load_quirk

_LOGGER = logging.getLogger(__name__)

type SmartWingsConfigEntry = ConfigEntry[ShadeDirectory]


@dataclass(frozen=True, slots=True)
class QuirkRegistration:
    """Whether ZHA applies quirks, and the quirk's registry entry if there is one."""

    quirks_enabled: bool
    # None when quirks are off or the registration failed.
    entry: QuirkRegistryEntry | None


REGISTRATION: HassKey[QuirkRegistration] = HassKey(f"{DOMAIN}_registration")


async def async_register_quirk(hass: HomeAssistant, config: ConfigType) -> None:
    """Register the quirk in ZHA's quirk registry, unless ZHA's quirks are turned off.

    ZHA reads ``enable_quirks`` from its YAML, which Home Assistant hands to every
    integration's setup.
    """
    try:
        enabled = cv.boolean(
            (config.get(ZHA_DOMAIN) or {}).get(CONF_ENABLE_QUIRKS, True)
        )
    except vol.Invalid:
        enabled = True  # ZHA itself refuses such a configuration
    entry = None
    if not enabled:
        _LOGGER.warning(
            "ZHA's quirks are turned off (enable_quirks: false), so the SmartWings"
            " quirk is not added"
        )
    else:
        try:
            entry = await hass.async_add_executor_job(load_quirk)
        except Exception:
            _LOGGER.exception("Could not add the SmartWings quirk to ZHA")
    hass.data[REGISTRATION] = QuirkRegistration(enabled, entry)


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
    registration = hass.data[REGISTRATION]
    shades = entry.runtime_data = ShadeDirectory(hass)
    activation = QuirkActivation(hass, entry, zha_entry, shades, registration.entry)
    missing_quirk = MissingQuirkIssue(
        hass, shades, activation.waiting, quirks_enabled=registration.quirks_enabled
    )
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
