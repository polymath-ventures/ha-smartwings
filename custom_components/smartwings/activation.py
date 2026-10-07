"""Get ZHA to apply the registered quirk: reload ZHA once if it built a shade without it.

ZHA picks each device's quirk when its gateway starts. The quirk is usually registered
before ZHA starts, so ZHA finds it then. When ZHA was already running (the integration was
just added) or picked another quirk first, ZHA's entry is reloaded, at most once per Home
Assistant run, so it cannot loop.

When zha-quirks itself provides the quirk, the integration's own is left out. The
integration says it is no longer needed once ZHA uses zha-quirks' quirk for every shade;
a shade that lacks the quirk gets the integration's after all, through the one reload.
"""

import logging
from typing import Final

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .shades import ShadeDirectory
from .zha_gateway import QuirkRegistryEntry, put_first, zha_quirks_provide_quirk

_LOGGER = logging.getLogger(__name__)

# The issue's id and its translation key under "issues" in strings.json.
ISSUE_UPSTREAM: Final = "quirk_now_upstream"
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
        """Put the quirk first, unless zha-quirks provides it."""
        if self.quirk is not None and not zha_quirks_provide_quirk():
            put_first(self.quirk)

    @callback
    def async_unload(self) -> None:
        """Stop acting (the entry is unloading) and withdraw the issue it keeps."""
        self._unloaded = True
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_UPSTREAM)

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
        shades = self.shades.shades.values()
        missing = [shade.name for shade in shades if not shade.quirk_active]
        self._async_note_upstream(
            bool(shades)
            and all(shade.quirk_active and shade.from_zha_quirks for shade in shades)
        )
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

    @callback
    def _async_note_upstream(self, upstream: bool) -> None:
        """Say, or stop saying, that ZHA uses zha-quirks' quirk for every shade."""
        if not upstream:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_UPSTREAM)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_UPSTREAM,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UPSTREAM,
        )

    async def _async_reload_zha(self) -> None:
        try:
            await self.hass.config_entries.async_reload(self.zha_entry.entry_id)
        finally:
            self._reloading = False
            if not self._unloaded:
                # Tell the listeners: what ZHA built is now final for this run.
                self.shades.async_zha_state_changed(self.zha_entry)
