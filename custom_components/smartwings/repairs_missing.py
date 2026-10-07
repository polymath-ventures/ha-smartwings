"""The Repairs issue naming the shades for which ZHA did not load the quirk.

Without it, ZHA uses the quirk that comes with Home Assistant, which swaps Open and Close
for these shades. One issue lists every such shade; it changes only when that list does,
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

# The issue's id and its translation key under "issues" in strings.json.
ISSUE_ID = "quirk_not_loaded"


class MissingQuirkIssue:
    """Keep the Repairs issue in step with the shades whose quirk is not loaded."""

    def __init__(
        self,
        hass: HomeAssistant,
        shades: ShadeDirectory,
        waiting: Callable[[], bool],
    ) -> None:
        """Follow ``shades``; the first update raises or deletes the issue.

        ``waiting`` says whether ZHA may still apply the quirk, so nothing is reported.
        """
        self.hass = hass
        self.shades = shades
        self._waiting = waiting
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
            "ZHA did not apply the SmartWings quirk to %s, even after a reload, so"
            " their Open and Close commands go out swapped. Another quirk for these"
            " shades probably takes precedence",
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
            translation_key=ISSUE_ID,
            translation_placeholders={
                "shades": "\n".join(f"- {name} ({ieee})" for name, ieee in missing)
            },
        )

    @callback
    def async_delete(self) -> None:
        """Withdraw the issue (the integration is unloading)."""
        self._reported = None
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID)
