"""The missing-quirk Repairs issue: real Home Assistant, real ZHA (#11, Part 3 §2m).

Includes Part 3 §5b item 1, the setup-order test: ZHA resolves every device before the
integration is set up, so only U in ``custom_quirks_path`` can make it the loaded quirk.
"""

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
import pytest

from custom_components.smartwings.const import DOMAIN
from custom_components.smartwings.zha_gateway import SIGNAL_ADD_ENTITIES
from tests.quirk.conftest import OTHER_IEEE, OTHER_NWK
from tests.smartwings_helpers import (
    ENTRY_ID,
    ISSUE_ID,
    directory,
    domain_issues,
    forget_in_database,
    install,
    issue,
    record_issue_events,
    supply_quirk,
    zha_device,
)
from tests.zha_harness import SHADE_IEEE, ZhaHarness, seed_database
from tests.zha_harness.harness import ZHA_ENTRY_ID

SHADE = str(SHADE_IEEE)
OTHER = str(OTHER_IEEE)
LOGGER = "custom_components.smartwings"
INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "smartwings"


def text() -> dict[str, str]:
    """Return the issue's English title and description from strings.json."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    return strings["issues"][ISSUE_ID]


def shown(harness: ZhaHarness) -> str:
    """Return the issue's description as the Repairs dialog renders it."""
    raised = issue(harness)
    assert raised is not None
    return text()["description"].format(**raised.translation_placeholders)


def number_entities(harness: ZhaHarness, ieee) -> list[str]:
    """Return the number entities on a shade's ZHA device (there are none, #54)."""
    return [
        entry.entity_id
        for entry in er.async_entries_for_device(
            er.async_get(harness.hass), zha_device(harness, ieee).id
        )
        if entry.domain == "number"
    ]


def warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the integration's WARNING records so far."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith(LOGGER) and r.levelno >= logging.WARNING
    ]


async def rename(harness: ZhaHarness, ieee, name: str) -> None:
    """Name a shade's device the way the user does on its device page."""
    dr.async_get(harness.hass).async_update_device(
        zha_device(harness, ieee).id, name_by_user=name
    )
    await harness.hass.async_block_till_done()


async def add_second_shade(harness: ZhaHarness) -> None:
    """Restart with a second WM25/L-Z in zigpy's database."""
    await harness.stop()
    await seed_database(
        harness.config_dir / "zigbee.db",
        initial_lift=40,
        ieee=OTHER_IEEE,
        nwk=OTHER_NWK,
    )
    await harness.start()


def block_the_install(harness: ZhaHarness) -> None:
    """Put a file of the user's where the quirk goes, so the integration cannot install.

    The missing-quirk issue is for a quirk the integration could not get loaded (#18).
    """
    (harness.custom_quirks_path / "wm25lz.py").write_text(
        "# Not the SmartWings quirk.\n"
    )


# --- Part 3 §5b item 1: setup order --------------------------------------------------


async def test_setup_order_with_only_the_integration(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """Integration installed, U absent, restart: the Repairs issue names the shade.

    Without custom_quirks_path the integration cannot supply U (#18), so U stays absent.
    """
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    await rename(zha_harness, SHADE_IEEE, "Office")

    await zha_harness.restart()

    assert sorted(domain_issues(zha_harness)) == [
        "custom_quirks_path_missing",
        ISSUE_ID,
    ]
    assert f"- Office ({SHADE})" in shown(zha_harness)
    assert "custom_quirks_path" in shown(zha_harness)
    assert directory(zha_harness).shades[SHADE].quirk_active is False
    assert number_entities(zha_harness, SHADE_IEEE) == []


async def test_setup_order_with_the_quirk_in_custom_quirks_path(
    zha_harness: ZhaHarness,
) -> None:
    """Integration installed, U in custom_quirks_path, restart: no Repairs issue."""
    await install(zha_harness)
    await supply_quirk(zha_harness)

    await zha_harness.restart()

    assert domain_issues(zha_harness) == []
    # Not even the inactive record Home Assistant keeps of an issue across a restart.
    assert ir.async_get(zha_harness.hass).async_get_issue(DOMAIN, ISSUE_ID) is None
    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert number_entities(zha_harness, SHADE_IEEE) == []


# --- The issue's lifecycle (D5) -------------------------------------------------------


async def test_the_issue_says_what_is_wrong_and_how_to_fix_it(
    zha_harness_without_quirks_path: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """One stock Repairs issue, translated, with the remedy, and one WARNING."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)

    raised = issue(zha_harness)
    assert raised is not None
    assert raised.translation_key == ISSUE_ID
    assert raised.is_fixable is False
    assert raised.is_persistent is False
    assert raised.severity is ir.IssueSeverity.ERROR
    name = zha_device(zha_harness, SHADE_IEEE).name
    assert raised.translation_placeholders == {"shades": f"- {name} ({SHADE})"}
    message = shown(zha_harness)
    for words in (
        "swaps the Open and Close commands",
        "custom_quirks_path",
        "restart",
    ):
        assert words in message
    assert len(warnings(caplog)) == 1
    assert SHADE in warnings(caplog)[0]


async def test_an_unchanged_set_is_not_reported_again(
    zha_harness_without_quirks_path: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """Rediscovery with the same shades changes no issue and logs nothing new."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    events = record_issue_events(zha_harness)

    async_dispatcher_send(zha_harness.hass, SIGNAL_ADD_ENTITIES)
    await zha_harness.reload_zha()

    assert issue(zha_harness) is not None
    assert events == []
    assert len(warnings(caplog)) == 1


async def test_the_set_shrinks_when_a_shade_is_removed(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """Two shades named, one removed: only the other is named."""
    zha_harness = zha_harness_without_quirks_path
    await add_second_shade(zha_harness)
    await install(zha_harness)
    await rename(zha_harness, SHADE_IEEE, "Office")
    await rename(zha_harness, OTHER_IEEE, "Bedroom")
    assert issue(zha_harness).translation_placeholders == {
        "shades": f"- Bedroom ({OTHER})\n- Office ({SHADE})"
    }

    await zha_harness.call("zha", "remove", {"ieee": SHADE})
    await zha_harness.clock.advance(60)
    await zha_harness.hass.async_block_till_done()

    assert issue(zha_harness).translation_placeholders == {
        "shades": f"- Bedroom ({OTHER})"
    }


async def test_renaming_a_shade_renames_it_in_the_issue(
    zha_harness_without_quirks_path: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """The user renames a shade's device: the issue follows, with no rediscovery."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    events = record_issue_events(zha_harness)

    await rename(zha_harness, SHADE_IEEE, "Office")

    assert issue(zha_harness).translation_placeholders == {
        "shades": f"- Office ({SHADE})"
    }
    assert directory(zha_harness).shades[SHADE].name == "Office"
    assert events == ["update"]
    assert len(warnings(caplog)) == 2


async def test_a_rename_that_leaves_the_text_alone_changes_nothing(
    zha_harness_without_quirks_path: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """Naming a shade what it is already called changes no issue and logs nothing."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    events = record_issue_events(zha_harness)

    await rename(zha_harness, SHADE_IEEE, zha_device(zha_harness, SHADE_IEEE).name)

    assert events == []
    assert len(warnings(caplog)) == 1


async def test_the_issue_is_deleted_once_the_quirk_is_active(
    zha_harness: ZhaHarness,
) -> None:
    """U supplied and ZHA reloaded: every shade has U, so the issue goes."""
    block_the_install(zha_harness)
    await install(zha_harness)
    assert issue(zha_harness) is not None

    await supply_quirk(zha_harness)
    await zha_harness.reload_zha()

    assert directory(zha_harness).shades[SHADE].quirk_active is True
    assert domain_issues(zha_harness) == []


async def test_zha_down_leaves_the_issue_alone(zha_harness: ZhaHarness) -> None:
    """While ZHA is unloaded nothing is reported, and nothing is withdrawn."""
    block_the_install(zha_harness)
    await install(zha_harness)
    hass = zha_harness.hass
    events = record_issue_events(zha_harness)

    assert await hass.config_entries.async_unload(ZHA_ENTRY_ID)
    await hass.async_block_till_done()
    assert issue(zha_harness) is not None
    assert events == []

    await supply_quirk(zha_harness)
    assert await hass.config_entries.async_setup(ZHA_ENTRY_ID)
    await hass.async_block_till_done()
    assert domain_issues(zha_harness) == []


async def test_the_last_shade_removed_while_zha_is_down(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """The only affected shade goes while ZHA is down: no issue once ZHA is back."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    hass = zha_harness.hass
    assert issue(zha_harness) is not None
    assert await hass.config_entries.async_unload(ZHA_ENTRY_ID)
    await hass.async_block_till_done()

    dr.async_get(hass).async_remove_device(zha_device(zha_harness, SHADE_IEEE).id)
    await forget_in_database(zha_harness, SHADE_IEEE)
    # Let the removal's debounced registry work finish.
    await zha_harness.clock.advance(60)
    await hass.async_block_till_done()
    assert directory(zha_harness).shades == {}
    assert issue(zha_harness) is not None  # unknown while ZHA is down

    assert await hass.config_entries.async_setup(ZHA_ENTRY_ID)
    await hass.async_block_till_done()

    assert directory(zha_harness).gateway_available
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID) is None


async def test_a_restart_with_no_shades_leaves_no_issue_record(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """The shade was dropped from zigpy's database: no issue, active or inactive."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    assert issue(zha_harness) is not None
    await zha_harness.stop()
    await forget_in_database(zha_harness, SHADE_IEEE)

    await zha_harness.start()

    assert directory(zha_harness).shades == {}
    assert directory(zha_harness).gateway_available
    assert ir.async_get(zha_harness.hass).async_get_issue(DOMAIN, ISSUE_ID) is None


async def test_unloading_the_entry_deletes_the_issue(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """Unload withdraws the issue."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    assert issue(zha_harness) is not None
    entry = zha_harness.hass.config_entries.async_get_entry(ENTRY_ID)

    assert await zha_harness.hass.config_entries.async_unload(ENTRY_ID)

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert domain_issues(zha_harness) == []


async def test_removing_the_entry_deletes_the_issue(
    zha_harness_without_quirks_path: ZhaHarness,
) -> None:
    """Deleting the integration leaves no Repairs issue behind."""
    zha_harness = zha_harness_without_quirks_path
    await install(zha_harness)
    assert issue(zha_harness) is not None

    await zha_harness.hass.config_entries.async_remove(ENTRY_ID)
    await zha_harness.hass.async_block_till_done()

    assert zha_harness.hass.config_entries.async_get_entry(ENTRY_ID) is None
    assert domain_issues(zha_harness) == []
