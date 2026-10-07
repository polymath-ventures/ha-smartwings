"""How the shades get the quirk: real Home Assistant, real ZHA, no YAML.

Importing the integration registers the quirk in ZHA's quirk registry. ZHA applies it to
the devices it builds from then on; a ZHA that already built a shade without it is
reloaded once.
"""

from collections.abc import Callable
import sys
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
import zha.quirks
import zhaquirks

from custom_components.smartwings.const import DOMAIN
from tests.quirk.conftest import QUIRK_FILE
from tests.smartwings_helpers import (
    ENTRY_ID,
    ISSUE_UPSTREAM,
    directory,
    domain_issues,
    install,
    issue,
    quirk_loaded,
    zha_reloads,
)
from tests.zha_harness import SHADE_IEEE, ZhaHarness, open_zha_harness

SHADE = str(SHADE_IEEE)


def integration_entries() -> list[zha.quirks.QuirkRegistryEntry]:
    """Return the entries the integration's quirk module registered in ZHA's registry."""
    return [
        entry
        for entry in zha.quirks.DEVICE_REGISTRY
        if entry.source is not None
        and entry.source.module == "custom_components.smartwings.quirk"
    ]


@pytest.mark.parametrize("custom_quirks_path", [True, False], ids=["path", "no-path"])
async def test_adding_the_integration_reloads_zha_once(
    tmp_path, hass_storage, custom_quirks_path: bool
) -> None:
    """ZHA running with the vendor quirk: one ZHA reload, then the shade has the quirk.

    With or without a custom_quirks_path, which ZHA purges at each setup.
    """
    async with open_zha_harness(
        tmp_path, hass_storage, custom_quirks_path_configured=custom_quirks_path
    ) as harness:
        assert not quirk_loaded(harness)

        shades = await install(harness)

        assert zha_reloads(harness) == 1
        assert quirk_loaded(harness)
        assert shades.shades[SHADE].quirk_active
        assert domain_issues(harness) == []


async def test_a_restart_applies_the_quirk_without_a_reload(
    zha_harness: ZhaHarness,
) -> None:
    """Integration installed, restart: imported before ZHA starts, so no reload."""
    await install(zha_harness)

    await zha_harness.restart()

    assert zha_reloads(zha_harness) == 0
    assert quirk_loaded(zha_harness)
    assert directory(zha_harness).shades[SHADE].quirk_active
    assert domain_issues(zha_harness) == []


async def test_a_restart_where_zha_starts_first_reloads_once(
    zha_harness: ZhaHarness,
) -> None:
    """ZHA builds the shade before the integration is imported: one reload."""
    await install(zha_harness)

    await zha_harness.restart(zha_first=True)

    assert zha_reloads(zha_harness) == 1
    assert quirk_loaded(zha_harness)
    assert domain_issues(zha_harness) == []


def front_vendor_quirk() -> None:
    """Put zha-quirks' vendor quirk for the WM25/L-Z in front, as draining it does."""
    for entry in list(zha.quirks.DEVICE_REGISTRY):
        if entry.source is not None and entry.source.module.startswith(
            "zhaquirks.smartwings"
        ):
            zha.quirks.DEVICE_REGISTRY.remove(entry)
            zha.quirks.DEVICE_REGISTRY.register(entry)


def draining_once(*, by_zha_only: bool) -> tuple[Callable[..., None], list[str]]:
    """Return a ``zhaquirks.setup`` whose first call drains the vendor quirk.

    That is the first call of all, or ZHA's first (the one given custom_quirks_path, as
    the harness configures one).
    """
    setup = zhaquirks.setup
    drained: list[str] = []

    def setup_draining(custom_quirks_path: str | None = None) -> None:
        setup(custom_quirks_path)
        if drained or (by_zha_only and custom_quirks_path is None):
            return
        drained.append(str(custom_quirks_path))
        front_vendor_quirk()

    return setup_draining, drained


async def test_the_vendor_quirk_queued_at_import_is_drained_first(
    zha_harness: ZhaHarness,
) -> None:
    """A vendor quirk still waiting to be drained when the integration is imported.

    The import drains it before registering the quirk, so ZHA needs no reload.
    """
    await install(zha_harness)
    setup, drained = draining_once(by_zha_only=False)

    with patch.object(zhaquirks, "setup", setup):
        await zha_harness.restart()

    assert drained == ["None"]
    assert zha_reloads(zha_harness) == 0
    assert quirk_loaded(zha_harness)


async def test_the_vendor_quirk_drained_by_zha_after_the_quirk_still_loses(
    zha_harness: ZhaHarness,
) -> None:
    """ZHA's quirk setup puts the vendor quirk in front once: one reload, then ours."""
    await install(zha_harness)
    setup, drained = draining_once(by_zha_only=True)

    with patch.object(zhaquirks, "setup", setup):
        await zha_harness.restart()

    assert drained == [str(zha_harness.custom_quirks_path)]
    assert zha_reloads(zha_harness) == 1
    assert quirk_loaded(zha_harness)
    assert domain_issues(zha_harness) == []


async def test_a_shade_still_without_the_quirk_is_reported_after_one_reload(
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """Another quirk takes precedence: one reload, never a second, and the issue."""
    harness = zha_harness_shadowed

    await install(harness)

    assert zha_reloads(harness) == 1
    assert not quirk_loaded(harness)
    assert issue(harness) is not None

    # A later reload of ZHA, by the user, is not followed by another.
    await harness.reload_zha()
    assert zha_reloads(harness) == 2
    assert issue(harness) is not None


async def test_a_restart_with_the_shade_still_shadowed_reloads_once(
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """Every Home Assistant run reloads ZHA at most once, then reports."""
    await install(zha_harness_shadowed)

    await zha_harness_shadowed.restart()

    assert zha_reloads(zha_harness_shadowed) == 1
    assert issue(zha_harness_shadowed) is not None


async def test_when_zha_quirks_provides_the_quirk_none_is_registered(
    zha_harness: ZhaHarness,
) -> None:
    """zha-quirks has the quirk: the integration registers nothing, and says so."""
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await zha_harness.restart()
    assert quirk_loaded(zha_harness)

    await install(zha_harness)

    assert integration_entries() == []
    assert zha_reloads(zha_harness) == 0
    assert directory(zha_harness).shades[SHADE].quirk_active
    assert domain_issues(zha_harness) == [ISSUE_UPSTREAM]
    raised = issue(zha_harness, ISSUE_UPSTREAM)
    assert raised is not None
    assert raised.translation_key == ISSUE_UPSTREAM


async def test_the_upstream_note_goes_with_the_integration(
    zha_harness: ZhaHarness,
) -> None:
    """Removing the integration withdraws the note."""
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    await zha_harness.restart()
    await install(zha_harness)
    assert issue(zha_harness, ISSUE_UPSTREAM) is not None

    await zha_harness.hass.config_entries.async_remove(ENTRY_ID)
    await zha_harness.hass.async_block_till_done()

    assert domain_issues(zha_harness) == []


async def test_when_zha_quirks_has_the_quirk_but_it_loses_ours_is_used(
    zha_harness: ZhaHarness,
) -> None:
    """zha-quirks has the quirk, but its vendor quirk wins: one reload, ours, no note."""
    zha_harness.ship_upstream(QUIRK_FILE.read_text())
    front_vendor_quirk()
    await zha_harness.restart()
    assert not quirk_loaded(zha_harness)

    await install(zha_harness)

    assert zha_reloads(zha_harness) == 1
    assert quirk_loaded(zha_harness)
    assert domain_issues(zha_harness) == []


async def test_with_zha_quirks_turned_off_nothing_is_registered(
    zha_harness: ZhaHarness,
) -> None:
    """enable_quirks: false: no quirk, no reload, and the issue says why."""
    zha_harness.quirks_enabled = False
    await zha_harness.restart()

    await install(zha_harness)

    assert integration_entries() == []
    assert zha_reloads(zha_harness) == 0
    assert not quirk_loaded(zha_harness)
    raised = issue(zha_harness)
    assert raised is not None
    assert raised.translation_key == "quirk_not_loaded_quirks_off"


async def test_a_failed_registration_is_reported_not_raised(
    zha_harness: ZhaHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """ZHA's quirk registry refuses the quirk: the integration loads, and says so."""
    with patch.object(zhaquirks, "setup", side_effect=RuntimeError("changed API")):
        shades = await install(zha_harness)

    assert zha_harness.hass.config_entries.async_get_entry(ENTRY_ID) is not None
    assert shades.gateway_available
    assert zha_reloads(zha_harness) == 0
    assert issue(zha_harness) is not None
    assert "Could not add the SmartWings quirk to ZHA" in caplog.text


async def test_without_zhas_libraries_the_flow_asks_for_zha(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """ZHA never set up, so its libraries are missing: the flow still says what to do."""
    with patch.dict(sys.modules):
        for name in list(sys.modules):
            if name.startswith(("homeassistant.components.zha", "custom_components.")):
                del sys.modules[name]
        # None in sys.modules makes an import fail as if the library were missing.
        sys.modules.update(dict.fromkeys(("zha", "zhaquirks", "zigpy", "bellows")))
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zha_not_configured"
