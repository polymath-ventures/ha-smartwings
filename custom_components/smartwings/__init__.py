"""SmartWings WM25/L-Z shades under ZHA: add the quirk to ZHA, and say when it is not used.

ZHA's libraries (zha, zhaquirks, zigpy) are installed with ZHA itself, and the manifest
does not depend on ZHA. So everything that needs them is in ``runtime``; without them
the integration still loads, and its flow asks for ZHA first.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

try:
    from . import runtime
except ModuleNotFoundError as err:
    if (err.name or "").startswith(__name__):
        raise
    runtime = None  # ZHA's libraries are missing: ZHA has never been set up here

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The integration's Repairs issues, by id.
ISSUES = ("quirk_not_loaded", "quirk_now_upstream")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the quirk as early as Home Assistant allows: before ZHA starts."""
    if runtime is not None:
        await runtime.async_register_quirk(hass, config)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Track the shades in ZHA, following ZHA's reloads and device changes."""
    if runtime is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="zha_not_ready"
        )
    return await runtime.async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entry; its listeners are removed by async_on_unload."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Leave no Repairs issue behind."""
    for issue_id in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
