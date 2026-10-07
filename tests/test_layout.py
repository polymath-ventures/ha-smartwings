"""The integration is where Home Assistant expects it (issue #2)."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration


async def test_integration_is_discoverable(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Home Assistant's loader finds the custom integration, and it depends on ZHA."""
    integration = await async_get_integration(hass, "smartwings")

    assert integration.domain == "smartwings"
    assert integration.dependencies == ["zha"]
