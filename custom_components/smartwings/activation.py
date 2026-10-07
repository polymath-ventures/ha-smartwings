"""Get ZHA to apply the registered quirk: reload ZHA once if it built a shade without it.

ZHA picks each device's quirk when its gateway starts. The quirk is usually registered
before ZHA starts, so ZHA finds it then. When ZHA was already running (the integration was
just added) or picked another quirk first, ZHA's entry is reloaded, at most once per Home
Assistant run, so it cannot loop.
"""

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .shades import ShadeDirectory
from .zha_gateway import QuirkRegistryEntry, put_first

_LOGGER = logging.getLogger(__name__)

# Set once ZHA has been reloaded in this Home Assistant run.
ZHA_RELOADED: HassKey[bool] = HassKey(f"{DOMAIN}_zha_reloaded")


class QuirkActivation:
    """Keep the quirk first in ZHA's registry, and reload ZHA once if a shade lacks it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        zha_entry: ConfigEntry,
        shades: ShadeDirectory,
        quirk: QuirkRegistryEntry | None,
    ) -> None:
        """Serve ``entry``, following ZHA's ``zha_entry`` and its ``shades``.

        ``quirk`` is the quirk's registry entry; None if there is none to apply.
        """
        self.hass = hass
        self.entry = entry
        self.zha_entry = zha_entry
        self.shades = shades
        self.quirk = quirk
        self._reloading = False
        self._unloaded = False

    @callback
    def async_setup(self) -> None:
        """Put the quirk first in ZHA's quirk registry."""
        if self.quirk is not None:
            put_first(self.quirk)

    @callback
    def async_unload(self) -> None:
        """Stop acting (the entry is unloading)."""
        self._unloaded = True

    @callback
    def waiting(self) -> bool:
        """Return whether a shade's missing quirk may yet be fixed by ZHA itself.

        That is while ZHA is still starting or a reload of it is under way.
        """
        return self._reloading or self.zha_entry.state is not ConfigEntryState.LOADED

    @callback
    def async_check(self) -> None:
        """Reload ZHA if it built a shade without the quirk and has not been reloaded."""
        if (
            self.quirk is None
            or self._unloaded
            or self.waiting()
            or not self.shades.gateway_available
        ):
            return
        missing = [
            shade.name
            for shade in self.shades.shades.values()
            if not shade.quirk_active
        ]
        if not missing or self.hass.data.get(ZHA_RELOADED):
            return
        self.hass.data[ZHA_RELOADED] = True
        put_first(self.quirk)
        _LOGGER.info(
            "Reloading ZHA so that it applies the SmartWings quirk to %s",
            ", ".join(sorted(missing)),
        )
        self._reloading = True
        self.entry.async_create_task(
            self.hass, self._async_reload_zha(), "smartwings reload zha"
        )

    async def _async_reload_zha(self) -> None:
        try:
            await self.hass.config_entries.async_reload(self.zha_entry.entry_id)
        finally:
            self._reloading = False
            if not self._unloaded:
                # Tell the listeners: what ZHA built is now final for this run.
                self.shades.async_zha_state_changed(self.zha_entry)
