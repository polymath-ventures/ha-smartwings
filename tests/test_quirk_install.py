"""The integration installs its quirk into ZHA's custom_quirks_path: real HA, real ZHA (#18).

ZHA loads quirks only when its entry sets up, so the file the integration writes takes
effect at the next restart or ZHA reload, and the integration asks for one through a
Repairs issue, shown instead of the missing-quirk issue while it is pending. It touches
only a regular file whose first line is its marker. Once the zha-quirks package Home
Assistant pins provides the quirk, it stops updating its file and says the user may
delete it; it never deletes it.
"""

import json
import logging
from pathlib import Path
import string
import sys
import threading
from typing import Any

from homeassistant.components.zha.helpers import get_zha_gateway
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
import pytest
import zha.quirks
import zhaquirks

from custom_components.smartwings import bundle
from custom_components.smartwings.const import DOMAIN
from tests.quirk.conftest import QUIRK_FILE
from tests.smartwings_helpers import (
    ENTRY_ID,
    directory,
    domain_issues,
    install,
    quirk_loaded,
    supply_quirk,
)
from tests.zha_harness import SHADE_IEEE, ZhaHarness

SHADE = str(SHADE_IEEE)
BUNDLED = QUIRK_FILE.read_bytes()
# The quirk as a user copied it by hand before the marker existed: it works, unmarked.
UNMARKED_QUIRK = BUNDLED.split(b"\n", 1)[1]
# An older version of the integration's own file: marked, working, different bytes.
OUTDATED_QUIRK = BUNDLED + b"# An older version.\n"
INTEGRATION_LOGGER = "custom_components.smartwings"
STRINGS = json.loads(
    (
        Path(__file__).parents[1] / "custom_components" / "smartwings" / "strings.json"
    ).read_text()
)

MISSING = "quirk_not_loaded"
PATH_MISSING = "custom_quirks_path_missing"
RESTART = "restart_required"
CONFLICT = "quirk_file_conflict"
UPSTREAM = "quirk_now_upstream"
NOT_WRITTEN = "quirk_file_not_written"
# The released quirk, restricted by a filter: ZHA applies it only to some units.
RESTRICTED_QUIRK = QUIRK_FILE.read_text().replace(
    'QuirkBuilder("Smartwings", "WM25/L-Z")',
    'QuirkBuilder("Smartwings", "WM25/L-Z").filter(lambda device: True)',
)


@pytest.fixture
def unconfigured_harness(zha_harness_without_quirks_path: ZhaHarness) -> ZhaHarness:
    """Real HA and ZHA whose YAML has no custom_quirks_path."""
    return zha_harness_without_quirks_path


def target(harness: ZhaHarness) -> Path:
    """Return the file the integration installs."""
    return harness.custom_quirks_path / "wm25lz.py"


def raised(harness: ZhaHarness, issue_id: str) -> ir.IssueEntry:
    """Return an active Repairs issue of the integration; fail if it is not raised."""
    issue = ir.async_get(harness.hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.active, issue_id
    return issue


def shown(harness: ZhaHarness, issue_id: str) -> str:
    """Return an issue's description as the Repairs dialog renders it."""
    issue = raised(harness, issue_id)
    return STRINGS["issues"][issue_id]["description"].format(
        **(issue.translation_placeholders or {})
    )


def stamp(path: Path) -> tuple[bytes, int]:
    """Return a file's bytes and modification time, to prove it was not written."""
    return path.read_bytes(), path.stat().st_mtime_ns


def integration_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return every record of the integration's loggers at WARNING or above."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(INTEGRATION_LOGGER)
        and record.levelno >= logging.WARNING
    ]


async def restart_with_file(harness: ZhaHarness, content: bytes) -> None:
    """Put ``content`` at the target as the user would, then restart so ZHA loads it."""
    target(harness).write_bytes(content)
    await harness.restart()


# --- Fresh install ---------------------------------------------------------------------


async def test_a_fresh_install_writes_the_file_and_asks_for_a_restart(
    zha_harness: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """No file, U absent: the bundled file is installed; ZHA is not reloaded."""
    gateway = get_zha_gateway(zha_harness.hass)

    await install(zha_harness)

    assert target(zha_harness).read_bytes() == BUNDLED
    # The restart request stands in for the missing-quirk issue: nothing went wrong.
    assert domain_issues(zha_harness) == [RESTART]
    issue = raised(zha_harness, RESTART)
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == RESTART
    assert issue.translation_placeholders == {"file": str(target(zha_harness))}
    assert "restart" in shown(zha_harness, RESTART).lower()
    assert "reload" in shown(zha_harness, RESTART).lower()
    # ZHA was not reloaded: the same gateway, the same unquirked shade.
    assert get_zha_gateway(zha_harness.hass) is gateway
    assert directory(zha_harness).shades[SHADE].quirk_active is False
    assert integration_warnings(caplog) == []


async def test_a_restart_after_the_install_loads_the_quirk(
    zha_harness: ZhaHarness,
) -> None:
    """Restart: U is active, nothing is rewritten or raised."""
    await install(zha_harness)
    before = stamp(target(zha_harness))

    await zha_harness.restart()

    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert quirk_loaded(zha_harness)
    assert stamp(target(zha_harness)) == before
    assert domain_issues(zha_harness) == []


async def test_a_zha_reload_loads_the_installed_quirk(zha_harness: ZhaHarness) -> None:
    """Reloading ZHA, as the restart issue offers, loads U and clears the issue."""
    await install(zha_harness)
    assert RESTART in domain_issues(zha_harness)

    await zha_harness.reload_zha()

    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert quirk_loaded(zha_harness)
    assert domain_issues(zha_harness) == []


async def test_reloading_the_entry_keeps_the_restart_request(
    zha_harness: ZhaHarness,
) -> None:
    """ZHA has not loaded the file yet: the request stays; nothing is rewritten."""
    await install(zha_harness)
    before = stamp(target(zha_harness))

    assert await zha_harness.hass.config_entries.async_reload(ENTRY_ID)
    await zha_harness.hass.async_block_till_done()

    assert domain_issues(zha_harness) == [RESTART]
    assert stamp(target(zha_harness)) == before


async def test_a_zha_reload_that_misses_the_file_keeps_the_request(
    zha_harness: ZhaHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ZHA reloads without loading the file (a race): the request is not withdrawn."""
    await install(zha_harness)
    load_quirks = zhaquirks.setup
    monkeypatch.setattr(
        zhaquirks, "setup", lambda custom_quirks_path=None: load_quirks(None)
    )

    await zha_harness.reload_zha()

    assert directory(zha_harness).shades[SHADE].quirk_active is False
    assert domain_issues(zha_harness) == [RESTART]
    assert integration_warnings(caplog) == []


async def test_a_restart_that_does_not_load_the_quirk_reports_it_missing(
    zha_harness: ZhaHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Once the request is gone and the quirk is still not active, it is reported."""
    await install(zha_harness)
    load_quirks = zhaquirks.setup
    monkeypatch.setattr(
        zhaquirks, "setup", lambda custom_quirks_path=None: load_quirks(None)
    )

    await zha_harness.restart()

    assert directory(zha_harness).shades[SHADE].quirk_active is False
    assert domain_issues(zha_harness) == [MISSING]
    [warning] = integration_warnings(caplog)
    assert "did not load the SmartWings quirk" in warning


@pytest.fixture
def relative_path_harness(
    zha_harness: ZhaHarness, monkeypatch: pytest.MonkeyPatch
) -> ZhaHarness:
    """ZHA configured with ``custom_quirks_path: custom_zha_quirks``, run from /config.

    ZHA resolves a relative value against the working directory (Home Assistant OS
    runs from the config folder), and records each quirk's absolute source file.
    """
    monkeypatch.chdir(zha_harness.config_dir)
    zha_harness.custom_quirks_path_setting = "custom_zha_quirks"
    return zha_harness


async def test_a_relative_path_still_finds_the_own_file(
    relative_path_harness: ZhaHarness,
) -> None:
    """Our loaded file is ours, not upstream: it is updated, and no note says delete."""
    harness = relative_path_harness
    await restart_with_file(harness, OUTDATED_QUIRK)
    # ZHA loaded it through the relative path.
    assert quirk_loaded(harness)

    await install(harness)

    assert target(harness).read_bytes() == BUNDLED
    assert domain_issues(harness) == [RESTART]
    assert raised(harness, RESTART).translation_placeholders == {
        "file": str(target(harness))
    }


async def test_a_relative_path_with_the_current_file_raises_nothing(
    relative_path_harness: ZhaHarness,
) -> None:
    """The bundled file loaded through a relative path: no note, nothing written."""
    harness = relative_path_harness
    await supply_quirk(harness)
    await harness.restart()
    before = stamp(target(harness))

    await install(harness)

    assert directory(harness).shades[SHADE].quirk_active is True
    assert stamp(target(harness)) == before
    assert domain_issues(harness) == []


# --- custom_quirks_path not configured -------------------------------------------------


async def test_without_custom_quirks_path_the_issue_gives_the_line(
    unconfigured_harness: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """No YAML line: the issue gives it exactly; the file waits in that folder."""
    harness = unconfigured_harness
    harness.custom_quirks_path.rmdir()
    folder = f"{harness.config_dir / 'custom_zha_quirks'}/"

    await install(harness)

    assert target(harness).read_bytes() == BUNDLED
    assert sorted(domain_issues(harness)) == [PATH_MISSING, MISSING]
    issue = raised(harness, PATH_MISSING)
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"path": folder}
    text = shown(harness, PATH_MISSING)
    assert f"zha:\n  custom_quirks_path: {folder}\n" in text
    assert "restart" in text.lower()
    # The quirk could not be put where ZHA loads it: the missing-quirk warning stands.
    [warning] = integration_warnings(caplog)
    assert "did not load the SmartWings quirk" in warning


async def test_adding_the_line_and_restarting_clears_the_issues(
    unconfigured_harness: ZhaHarness,
) -> None:
    """The user adds the line and restarts: U is active, no issue is left."""
    harness = unconfigured_harness
    await install(harness)

    harness.custom_quirks_path_configured = True
    await harness.restart()

    assert directory(harness).shades[SHADE].quirk_active is True
    assert domain_issues(harness) == []


# --- The integration's own file --------------------------------------------------------


async def test_an_outdated_own_file_is_updated(
    zha_harness: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """An older marked copy is replaced, even while it is the active quirk."""
    await restart_with_file(zha_harness, OUTDATED_QUIRK)

    await install(zha_harness)

    assert target(zha_harness).read_bytes() == BUNDLED
    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert domain_issues(zha_harness) == [RESTART]
    assert integration_warnings(caplog) == []

    await zha_harness.restart()

    assert domain_issues(zha_harness) == []


async def test_a_current_own_file_is_not_rewritten(zha_harness: ZhaHarness) -> None:
    """The bundled file already in place and loaded: nothing to do."""
    await supply_quirk(zha_harness)
    await zha_harness.restart()
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert stamp(target(zha_harness)) == before
    assert domain_issues(zha_harness) == []


# --- A file the integration did not write ----------------------------------------------


async def test_an_unmarked_file_is_left_alone_and_explained(
    zha_harness: ZhaHarness,
) -> None:
    """Same name, no marker, U not loaded: untouched, and an issue says why."""
    await restart_with_file(zha_harness, b"# A quirk of the user's own.\n")
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert stamp(target(zha_harness)) == before
    assert sorted(domain_issues(zha_harness)) == [CONFLICT, MISSING]
    issue = raised(zha_harness, CONFLICT)
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {
        "file": str(target(zha_harness)),
        "marker": bundle.MARKER,
    }


async def test_an_unmarked_working_copy_is_left_alone_quietly(
    zha_harness: ZhaHarness,
) -> None:
    """A hand copy of the quirk that ZHA loaded: untouched, nothing to report."""
    await restart_with_file(zha_harness, UNMARKED_QUIRK)
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert stamp(target(zha_harness)) == before
    assert domain_issues(zha_harness) == []


# --- zha-quirks provides the quirk -----------------------------------------------------


async def test_upstream_quirk_keeps_the_own_file_and_notes_it(
    zha_harness: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """zha-quirks has U: the integration's file stays; a note says it may go."""
    await supply_quirk(zha_harness)
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await zha_harness.restart()
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert stamp(target(zha_harness)) == before
    assert domain_issues(zha_harness) == [UPSTREAM]
    issue = raised(zha_harness, UPSTREAM)
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders == {"file": str(target(zha_harness))}
    text = shown(zha_harness, UPSTREAM)
    assert str(target(zha_harness)) in text
    assert "custom_quirks_path" in text
    assert integration_warnings(caplog) == []


async def test_upstream_quirk_stops_updates(zha_harness: ZhaHarness) -> None:
    """While zha-quirks has U, an outdated own file is not updated."""
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await restart_with_file(zha_harness, OUTDATED_QUIRK)
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert stamp(target(zha_harness)) == before
    assert domain_issues(zha_harness) == [UPSTREAM]


async def test_the_note_goes_once_the_user_deletes_the_file(
    zha_harness: ZhaHarness,
) -> None:
    """The user deletes the file and restarts: zha-quirks' U is loaded, no issue."""
    await supply_quirk(zha_harness)
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await zha_harness.restart()
    await install(zha_harness)
    assert domain_issues(zha_harness) == [UPSTREAM]

    target(zha_harness).unlink()
    await zha_harness.restart()

    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert quirk_loaded(zha_harness)
    assert not target(zha_harness).exists()
    assert domain_issues(zha_harness) == []


async def test_a_restricted_upstream_entry_changes_nothing(
    zha_harness: ZhaHarness,
) -> None:
    """A filtered zha-quirks entry is not taken as upstream: updates go on, no note."""
    zha_harness.ship_upstream(RESTRICTED_QUIRK)
    await restart_with_file(zha_harness, OUTDATED_QUIRK)

    await install(zha_harness)

    assert target(zha_harness).read_bytes() == BUNDLED
    assert domain_issues(zha_harness) == [RESTART]


async def test_upstream_quirk_leaves_an_unmarked_file_alone(
    zha_harness: ZhaHarness,
) -> None:
    """zha-quirks has U and the file is not the integration's: untouched, no issue."""
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await restart_with_file(zha_harness, b"# A quirk of the user's own.\n")
    before = stamp(target(zha_harness))

    await install(zha_harness)

    assert stamp(target(zha_harness)) == before
    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert domain_issues(zha_harness) == []


# --- File work off the event loop, and its failures ------------------------------------


async def test_file_work_runs_in_the_executor(
    zha_harness: ZhaHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every read and write of the file runs off the event loop."""
    loop_thread = threading.get_ident()
    calls: list[tuple[str, bool]] = []

    def spy(name: str) -> Any:
        original = getattr(bundle, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, threading.get_ident() != loop_thread))
            return original(*args, **kwargs)

        return wrapper

    for name in ("bundled_bytes", "inspect", "sync"):
        monkeypatch.setattr(bundle, name, spy(name))

    await install(zha_harness)
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    assert await zha_harness.hass.config_entries.async_reload(ENTRY_ID)
    await zha_harness.hass.async_block_till_done()

    assert {name for name, _ in calls} == {"bundled_bytes", "inspect", "sync"}
    assert all(off_loop for _, off_loop in calls), calls


def fail_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every write of the quirk file fail as a read-only folder does."""

    def fail(path: Path, data: bytes, *, install_if_absent: bool) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(bundle, "sync", fail)


async def test_an_unwritable_folder_is_reported(
    zha_harness: ZhaHarness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The write fails: an ERROR and an issue say why; no restart request."""
    fail_writes(monkeypatch)

    await install(zha_harness)

    entry = zha_harness.hass.config_entries.async_get_entry(ENTRY_ID)
    assert entry.state is ConfigEntryState.LOADED
    errors = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(INTEGRATION_LOGGER)
        and record.levelno == logging.ERROR
    ]
    assert len(errors) == 1
    assert str(target(zha_harness)) in errors[0]
    assert sorted(domain_issues(zha_harness)) == [NOT_WRITTEN, MISSING]
    issue = raised(zha_harness, NOT_WRITTEN)
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_placeholders["file"] == str(target(zha_harness))
    assert "Permission denied" in issue.translation_placeholders["error"]
    assert not target(zha_harness).exists()


async def test_an_unwritable_folder_still_gets_the_yaml_line(
    unconfigured_harness: ZhaHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The missing-line guidance does not depend on the write."""
    fail_writes(monkeypatch)

    await install(unconfigured_harness)

    assert sorted(domain_issues(unconfigured_harness)) == [
        PATH_MISSING,
        NOT_WRITTEN,
        MISSING,
    ]


async def test_a_symlink_in_the_way_is_left_alone(zha_harness: ZhaHarness) -> None:
    """A (broken) link where the file goes: untouched, and explained."""
    target(zha_harness).symlink_to(zha_harness.config_dir / "missing.py")

    await install(zha_harness)

    assert target(zha_harness).is_symlink()
    assert not target(zha_harness).exists()
    assert sorted(domain_issues(zha_harness)) == [CONFLICT, MISSING]


# --- Lifecycle, and no quirk code ------------------------------------------------------


async def test_unloading_keeps_the_restart_request_and_the_file(
    zha_harness: ZhaHarness,
) -> None:
    """ZHA still has to load the file after an unload: the request and file stay."""
    await install(zha_harness)
    assert RESTART in domain_issues(zha_harness)

    assert await zha_harness.hass.config_entries.async_unload(ENTRY_ID)

    assert domain_issues(zha_harness) == [RESTART]
    assert target(zha_harness).read_bytes() == BUNDLED


async def test_unloading_withdraws_what_only_the_entry_keeps_current(
    unconfigured_harness: ZhaHarness,
) -> None:
    """The missing-line and conflict issues go with the entry."""
    harness = unconfigured_harness
    target(harness).write_bytes(b"# A quirk of the user's own.\n")
    await install(harness)
    assert sorted(domain_issues(harness)) == [PATH_MISSING, CONFLICT, MISSING]

    assert await harness.hass.config_entries.async_unload(ENTRY_ID)

    assert domain_issues(harness) == []


async def test_removing_the_entry_deletes_every_issue(zha_harness: ZhaHarness) -> None:
    """Removal leaves no issue of the integration, the upstream note included."""
    await supply_quirk(zha_harness)
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await zha_harness.restart()
    await install(zha_harness)
    assert domain_issues(zha_harness) == [UPSTREAM]

    await zha_harness.hass.config_entries.async_remove(ENTRY_ID)
    await zha_harness.hass.async_block_till_done()

    assert domain_issues(zha_harness) == []


async def test_installing_imports_and_registers_no_quirk_code(
    zha_harness: ZhaHarness,
) -> None:
    """The bundled file is only copied: no module from it, no registry entry added."""
    entries = list(zha.quirks.DEVICE_REGISTRY)

    await install(zha_harness)

    assert list(zha.quirks.DEVICE_REGISTRY) == entries
    assert [
        name
        for name, module in list(sys.modules.items())
        if getattr(module, "__file__", None) is not None
        and Path(module.__file__).resolve() == bundle.BUNDLED_FILE.resolve()
    ] == []


@pytest.mark.parametrize(
    ("issue_id", "placeholders"),
    [
        (PATH_MISSING, {"path"}),
        (RESTART, {"file"}),
        (CONFLICT, {"file", "marker"}),
        (UPSTREAM, {"file"}),
        (NOT_WRITTEN, {"file", "error"}),
    ],
)
def test_each_issue_is_translated_with_its_placeholders(
    issue_id: str, placeholders: set[str]
) -> None:
    """Every issue has a title and a description using exactly its placeholders."""
    text = STRINGS["issues"][issue_id]

    assert text["title"]
    assert {
        name for _, name, _, _ in string.Formatter().parse(text["description"]) if name
    } == placeholders
