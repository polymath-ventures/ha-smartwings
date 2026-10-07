"""The Repairs issue naming the shades for which ZHA did not load the quirk.

Without it, ZHA uses the quirk that comes with Home Assistant, which swaps Open and Close
for these shades. One issue lists every such shade; it changes only when that list does,
and is deleted when the list empties or the integration unloads. While ZHA is not loaded
the list is unknown, so the issue is left as it is. While a restart request is pending,
that is shown instead and nothing is logged at WARNING.
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
        restart_pending: Callable[[], bool],
    ) -> None:
        """Follow ``shades``; the first update raises or deletes the issue.

        ``restart_pending`` says whether a restart request stands in for this issue.
        """
        self.hass = hass
        self.shades = shades
        self._restart_pending = restart_pending
        # None until the first update, so that one also deletes an issue recorded
        # before a restart (Home Assistant keeps an inactive record of it).
        self._reported: tuple[tuple[str, str], ...] | None = None

    @callback
    def async_update(self) -> None:
        """Raise, change or delete the issue if the affected shades changed."""
        if not self.shades.gateway_available:
            return
        missing = tuple(
            sorted(
                (shade.name, shade.ieee)
                for shade in self.shades.shades.values()
                if not shade.quirk_active
            )
        )
        waiting = bool(missing) and self._restart_pending()
        if waiting:
            # The restart request says what to do; the shades are not reported yet.
            missing = ()
        if missing == self._reported:
            return
        self._reported = missing
        if not missing:
            if not waiting:
                _LOGGER.info("The SmartWings quirk is loaded for every shade")
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_ID)
            return
        _LOGGER.warning(
            "ZHA did not load the SmartWings quirk for %s, so their Open and Close"
            " commands go out swapped. Install the quirk in ZHA's custom_quirks_path"
            " and restart",
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
