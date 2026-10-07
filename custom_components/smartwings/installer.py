"""Install and update the integration's quirk file in ZHA's custom_quirks_path.

ZHA loads quirks only when its entry sets up, so until the quirk ships in the
zha-quirks package Home Assistant pins, the integration copies its bundled file into
ZHA's ``custom_quirks_path`` and asks for a restart through a Repairs issue. It never
imports the file, never reloads ZHA, never touches a file that is not its own, and never
deletes a file. Once zha-quirks provides the quirk, it stops updating its file and says
the user may delete it and the ``custom_quirks_path`` line.

One reconciliation runs at entry setup and each time ZHA's entry becomes loaded again.
Every file operation runs in the executor, a check and its write in one job. The restart
request is itself the record that ZHA has not loaded the file written: Home Assistant's
issue registry keeps it across a reload of this entry; it goes when the quirk is found
active, and a restart ends it.
"""

import asyncio
from collections.abc import Callable
from functools import partial
import logging
from pathlib import Path
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from . import bundle
from .bundle import FileState
from .const import DOMAIN
from .shades import ShadeDirectory
from .zha_gateway import async_custom_quirks_path, zha_quirks_provide_quirk

_LOGGER = logging.getLogger(__name__)

# The folder the custom_quirks_path_missing issue asks the user to configure.
DEFAULT_FOLDER: Final = "custom_zha_quirks"

# Issue ids, equal to their translation keys under "issues" in strings.json.
ISSUE_PATH_MISSING: Final = "custom_quirks_path_missing"
ISSUE_RESTART: Final = "restart_required"
ISSUE_CONFLICT: Final = "quirk_file_conflict"
ISSUE_NOT_WRITTEN: Final = "quirk_file_not_written"
ISSUE_UPSTREAM: Final = "quirk_now_upstream"
# Recomputed by every reconciliation.
ALL_ISSUES: Final = (
    ISSUE_PATH_MISSING,
    ISSUE_RESTART,
    ISSUE_CONFLICT,
    ISSUE_NOT_WRITTEN,
    ISSUE_UPSTREAM,
)
# Withdrawn when the entry unloads. A restart request stays: ZHA still has to load the
# file, whether or not this entry is loaded.
UNLOAD_ISSUES: Final = tuple(issue for issue in ALL_ISSUES if issue != ISSUE_RESTART)


class QuirkInstaller:
    """Keep the quirk file in ZHA's custom_quirks_path, and its Repairs issues, current."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, shades: ShadeDirectory
    ) -> None:
        """Reconcile for ``entry``, judging whether the quirk is active from ``shades``."""
        self.hass = hass
        self.entry = entry
        self.shades = shades
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` after every reconciliation (the restart request may change)."""
        self._listeners.append(listener)

    @callback
    def async_restart_pending(self) -> bool:
        """Return whether a file this integration wrote still waits for ZHA to load it."""
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, ISSUE_RESTART)
        return issue is not None and issue.active

    async def async_reconcile(self) -> None:
        """Install or update the file as needed, and raise the matching issues."""
        async with self._lock:
            await self._async_reconcile()
        for listener in self._listeners:
            listener()

    @callback
    def async_zha_loaded(self) -> None:
        """ZHA's entry became loaded: reconcile against what it loaded."""
        self.entry.async_create_task(
            self.hass, self.async_reconcile(), "smartwings quirk install"
        )

    @callback
    def async_unload(self) -> None:
        """Withdraw the issues only a loaded entry keeps current (it is unloading)."""
        for issue_id in UNLOAD_ISSUES:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _async_reconcile(self) -> None:
        if not self.shades.gateway_available:
            return
        configured = async_custom_quirks_path(self.hass)
        folder = configured or Path(self.hass.config.path(DEFAULT_FOLDER))
        target = folder / bundle.FILE_NAME
        tracked = self.shades.shades.values()
        active = bool(tracked) and all(shade.quirk_active for shade in tracked)
        wanted: dict[str, dict[str, str]] = {}
        installed = await self.hass.async_add_executor_job(bundle.installed_bytes)
        upstream = zha_quirks_provide_quirk(configured)
        if configured is None and not active and not upstream:
            wanted[ISSUE_PATH_MISSING] = {"path": f"{folder}/"}
        try:
            if upstream:
                # Stop updating; the user decides whether to delete the file.
                state = await self.hass.async_add_executor_job(
                    bundle.inspect, target, installed
                )
                if state in (FileState.CURRENT, FileState.OUTDATED):
                    wanted[ISSUE_UPSTREAM] = {"file": str(target)}
                self._async_raise(wanted)
                return
            result = await self.hass.async_add_executor_job(
                partial(bundle.sync, target, installed, install_if_absent=not active)
            )
        except OSError as err:
            _LOGGER.error(
                "Could not update the SmartWings quirk file %s: %s", target, err
            )
            wanted[ISSUE_NOT_WRITTEN] = {"file": str(target), "error": str(err)}
            self._async_raise(wanted)
            return
        if result.written:
            _LOGGER.info("Wrote the current SmartWings quirk to %s", target)
        if configured is not None and (
            result.written or (self.async_restart_pending() and not active)
        ):
            wanted[ISSUE_RESTART] = {"file": str(target)}
        if result.state is FileState.FOREIGN and not active:
            _LOGGER.debug("Left %s alone: it is not this integration's file", target)
            wanted[ISSUE_CONFLICT] = {"file": str(target), "marker": bundle.MARKER}
        self._async_raise(wanted)

    @callback
    def _async_raise(self, wanted: dict[str, dict[str, str]]) -> None:
        """Raise exactly the issues in ``wanted``, with their placeholders."""
        for issue_id in ALL_ISSUES:
            if issue_id not in wanted:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
                translation_placeholders=wanted[issue_id],
            )
