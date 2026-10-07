"""The SmartWings config entry and its flow: real Home Assistant, real ZHA."""

import json
from pathlib import Path

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartwings.const import DOMAIN
from tests.smartwings_helpers import domain_issues
from tests.zha_harness import ZhaHarness
from tests.zha_harness.harness import ZHA_ENTRY_ID

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "smartwings"


def test_english_translations_equal_strings() -> None:
    """A custom integration ships translations/en.json as its strings.json."""
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    english = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text())

    assert english == strings


async def start_flow(hass: HomeAssistant) -> dict:
    """Start the flow the way the "Add integration" dialog does."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def test_the_flow_creates_one_entry_with_nothing_to_fill_in(
    zha_harness: ZhaHarness,
) -> None:
    """One confirm step, then one loaded entry with no data."""
    hass = zha_harness.hass

    result = await start_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["data_schema"] is None or not result["data_schema"].schema

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "SmartWings"
    assert result["data"] == {}
    [entry] = hass.config_entries.async_entries(DOMAIN)
    assert entry.state is ConfigEntryState.LOADED


async def test_a_second_flow_aborts(zha_harness: ZhaHarness) -> None:
    """Home Assistant refuses a second entry, with its own translated reason."""
    hass = zha_harness.hass
    first = await start_flow(hass)
    await hass.config_entries.flow.async_configure(first["flow_id"], {})
    await hass.async_block_till_done()

    result = await start_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_the_flow_aborts_without_zha(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """With no ZHA entry, the flow says to set up ZHA first and creates nothing."""
    result = await start_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "zha_not_configured"
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_setup_retries_while_zha_has_no_gateway(
    zha_harness: ZhaHarness,
) -> None:
    """Setup is not ready while ZHA is down, and reports no shade as missing its quirk."""
    hass = zha_harness.hass
    assert await hass.config_entries.async_unload(ZHA_ENTRY_ID)
    entry = MockConfigEntry(domain=DOMAIN, title="SmartWings")
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert domain_issues(zha_harness) == []
