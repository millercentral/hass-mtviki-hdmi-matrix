"""Config flow for the MT-ViKI HDMI Matrix integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import (
    DEFAULT_MODEL,
    DEFAULT_PORT,
    DOMAIN,
    MANUFACTURER,
    NUM_INPUTS,
    NUM_OUTPUTS,
    OPTION_NONE,
    default_input_name,
    default_output_name,
    input_key,
    output_key,
)
from .coordinator import MatrixConfigEntry
from .protocol import DeviceInfo, MatrixError, probe

_LOGGER = logging.getLogger(__name__)


def _connection_schema(host: str = "", port: int = DEFAULT_PORT) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
        }
    )


async def _validate(user_input: dict[str, Any]) -> tuple[DeviceInfo | None, str | None]:
    """Return (info, error_key)."""
    try:
        info, _routing = await probe(user_input[CONF_HOST], user_input[CONF_PORT])
    except MatrixError as err:
        _LOGGER.debug("Validation failed: %s", err)
        return None, "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error while probing the switch")
        return None, "unknown"
    return info, None


class MatrixConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an MT-ViKI matrix by IP address and control port."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            info, error = await _validate(user_input)
            if error:
                errors["base"] = error
            else:
                assert info is not None
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{MANUFACTURER} {info.model or DEFAULT_MODEL}",
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                    },
                )
            schema = _connection_schema(user_input[CONF_HOST], user_input[CONF_PORT])
        else:
            schema = _connection_schema()

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the IP address or port of an existing switch."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            _info, error = await _validate(user_input)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(user_input[CONF_HOST])
                if user_input[CONF_HOST] != entry.data[CONF_HOST]:
                    self._abort_if_unique_id_configured()
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=user_input[CONF_HOST],
                    data_updates={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                    },
                )
            defaults = user_input
        else:
            defaults = entry.data

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                defaults[CONF_HOST], defaults.get(CONF_PORT, DEFAULT_PORT)
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: MatrixConfigEntry) -> OptionsFlow:
        return MatrixOptionsFlow()


class MatrixOptionsFlow(OptionsFlow):
    """Rename the inputs and outputs."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)

        if user_input is not None:
            cleaned = {k: str(v).strip() for k, v in user_input.items()}
            input_names = [
                cleaned.get(input_key(i)) or default_input_name(i)
                for i in range(1, NUM_INPUTS + 1)
            ]
            if len({n.casefold() for n in input_names}) != NUM_INPUTS:
                errors["base"] = "duplicate_input_names"
            elif any(n.casefold() == OPTION_NONE.casefold() for n in input_names):
                errors["base"] = "reserved_input_name"
            else:
                return self.async_create_entry(data=cleaned)
            current = cleaned

        fields: dict[Any, Any] = {}
        for i in range(1, NUM_INPUTS + 1):
            key = input_key(i)
            fields[vol.Optional(key, default=current.get(key) or default_input_name(i))] = str
        for o in range(1, NUM_OUTPUTS + 1):
            key = output_key(o)
            fields[vol.Optional(key, default=current.get(key) or default_output_name(o))] = str

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
