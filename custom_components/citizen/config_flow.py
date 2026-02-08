"""Config flow for Citizen integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_RADIUS_KM,
    CONF_SCAN_INTERVAL,
    CONF_MAX_INCIDENTS,
    DEFAULT_RADIUS_KM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_MAX_INCIDENTS,
)


class CitizenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Citizen."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # Use a unique ID based on location to prevent duplicates
            await self.async_set_unique_id(
                f"citizen_{user_input[CONF_LATITUDE]:.4f}_{user_input[CONF_LONGITUDE]:.4f}"
            )
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Citizen ({user_input[CONF_LATITUDE]:.3f}, {user_input[CONF_LONGITUDE]:.3f})",
                data=user_input,
            )

        # Default to Home Assistant's configured home location
        home_lat = self.hass.config.latitude
        home_lon = self.hass.config.longitude

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LATITUDE, default=home_lat): vol.Coerce(float),
                    vol.Required(CONF_LONGITUDE, default=home_lon): vol.Coerce(float),
                    vol.Required(
                        CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=50)),
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                    vol.Required(
                        CONF_MAX_INCIDENTS, default=DEFAULT_MAX_INCIDENTS
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=200)),
                }
            ),
        )
