"""The Repairs issue naming the shades for which ZHA did not load the quirk.

One issue lists every such shade; it changes only when that list does,
and is deleted when the list empties or the integration unloads. While ZHA is not loaded
the list is unknown, so the issue is left as it is. While ZHA may still apply the quirk
(it is starting, or the integration is reloading it), nothing is reported yet.
"""

from collections.abc import Callable
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .shades import ShadeDirectory

_LOGGER = logging.getLogger(__name__)

# The issue's id and its translation key under "issues" in strings.json; the second key
# explains the issue when ZHA's quirks are turned off.
ISSUE_ID = "quirk_not_loaded"
QUIRKS_OFF_KEY = "quirk_not_loaded_quirks_off"


class MissingQuirkIssue:
    """Keep the Repairs issue in step with the shades whose quirk is not loaded."""

    def __init__(
        self,
        hass: HomeAssistant,
        shades: ShadeDirectory,
        waiting: Callable[[], bool],
        *,
        quirks_enabled: bool,
    ) -> None:
        """Follow ``shades``; the first update raises or deletes the issue.

        ``waiting`` says whether ZHA may still apply the quirk, so nothing is reported;
        ``quirks_enabled`` whether ZHA applies quirks at all.
        """
        self.hass = hass
        self.shades = shades
        self._waiting = waiting
        self._translation_key = ISSUE_ID if quirks_enabled else QUIRKS_OFF_KEY
        # None until the first update, so that one also deletes an issue recorded
        # before a restart (Home Assistant keeps an inactive record of it).
        self._reported: tuple[tuple[str, str], ...] | None = None

    @callback
    def async_update(self) -> None:
        """Raise, change or delete the issue if the affected shades changed."""
        if not self.shades.gateway_available or self._waiting():
            return
        missing = tuple(
            sorted(
                (shade.name, shade.ieee)
                for shade in self.shades.shades.values()
                if not shade.quirk_active
            )
        )
        if missing == self._reported:
            return
        self._reported = missing
        if not missing:
            _LOGGER.info("The SmartWings quirk is loaded for every shade")
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID)
            return
        _LOGGER.warning(
            "ZHA is not using the SmartWings quirk for %s",
            ", ".join(f"{name} ({ieee})" for name, ieee in missing),
        )
        # ERROR: the shades misbehave now (Home Assistant's WARNING is for
        # something that will break later).
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_ID,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=self._translation_key,
            translation_placeholders={
                "shades": "\n".join(f"- {name} ({ieee})" for name, ieee in missing)
            },
        )

    @callback
    def async_delete(self) -> None:
        """Withdraw the issue (the integration is unloading)."""
        self._reported = None
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID)
