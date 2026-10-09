"""Config flow for SmartWings: one entry, nothing to fill in."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, ZHA_DOMAIN


class SmartWingsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the integration once ZHA is set up.

    Home Assistant refuses a second entry itself (``single_config_entry``).
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then create the entry."""
        if not self.hass.config_entries.async_entries(ZHA_DOMAIN):
            return self.async_abort(reason="zha_not_configured")
        if user_input is not None:
            return self.async_create_entry(title="SmartWings", data={})
        return self.async_show_form(step_id="user")
