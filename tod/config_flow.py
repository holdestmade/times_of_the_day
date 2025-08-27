"""Config flow for Times of the Day integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaConfigFlowHandler,
    SchemaFlowFormStep,
)

from .const import (
    DOMAIN,
    CONF_AFTER_TIME,
    CONF_BEFORE_TIME,
    CONF_AFTER_MODE,
    CONF_BEFORE_MODE,
    CONF_AFTER_OFFSET,
    CONF_BEFORE_OFFSET,
    MODE_TIME,
    MODE_SUNRISE,
    MODE_SUNSET,
)

MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[MODE_TIME, MODE_SUNRISE, MODE_SUNSET],
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)

TIME_SELECTOR = selector.TimeSelector()

# Negative offsets supported via a signed "minutes" number input
OFFSET_MINUTES_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=-1440,  # -24h
        max=1440,   # +24h
        step=1,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="min",
    )
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AFTER_MODE, default=MODE_TIME): MODE_SELECTOR,
        vol.Required(CONF_AFTER_TIME, default="00:00:00"): TIME_SELECTOR,  # used only when mode == time
        vol.Required(CONF_AFTER_OFFSET, default=0): OFFSET_MINUTES_SELECTOR,  # signed minutes
        vol.Required(CONF_BEFORE_MODE, default=MODE_TIME): MODE_SELECTOR,
        vol.Required(CONF_BEFORE_TIME, default="00:00:00"): TIME_SELECTOR,  # used only when mode == time
        vol.Required(CONF_BEFORE_OFFSET, default=0): OFFSET_MINUTES_SELECTOR,  # signed minutes
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
    }
).extend(OPTIONS_SCHEMA.schema)

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(CONFIG_SCHEMA),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(OPTIONS_SCHEMA),
}


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for Times of the Day."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options["name"])
