"""Push-based coordinator that mirrors the switch's routing into Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    NUM_INPUTS,
    NUM_OUTPUTS,
    default_input_name,
    default_output_name,
    input_key,
    output_key,
)
from .protocol import MatrixClient, MatrixConnectionError, MatrixError

_LOGGER = logging.getLogger(__name__)


@dataclass
class MatrixRuntimeData:
    """Objects stored on the config entry while it is loaded."""

    client: MatrixClient
    coordinator: MatrixCoordinator


type MatrixConfigEntry = ConfigEntry[MatrixRuntimeData]


class MatrixCoordinator(DataUpdateCoordinator[list[int]]):
    """Holds the routing list [input for output 1, output 2, ...].

    There is no polling interval: the client keeps a persistent connection and
    calls back whenever the switch reports new routing (including changes made
    with the front-panel buttons or IR remote) or the connection drops.
    """

    config_entry: MatrixConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: MatrixConfigEntry, client: MatrixClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.client = client
        self._unsub = client.add_listener(self._handle_client_update)

    @callback
    def _handle_client_update(self) -> None:
        if self.client.connected and self.client.routing is not None:
            self.async_set_updated_data(list(self.client.routing))
        elif not self.client.connected:
            self.async_set_update_error(
                MatrixConnectionError(
                    f"Lost connection to {self.client.host}:{self.client.port}"
                )
            )

    async def _async_update_data(self) -> list[int]:
        """Used by manual refreshes (e.g. homeassistant.update_entity)."""
        try:
            await self.client.refresh()
        except MatrixError as err:
            raise UpdateFailed(str(err)) from err
        if self.client.routing is None:
            raise UpdateFailed("Switch did not report its routing")
        return list(self.client.routing)

    async def async_shutdown(self) -> None:
        self._unsub()
        await super().async_shutdown()

    # ----------------------------------------------------------- friendly names

    def input_name(self, num: int) -> str:
        return self.config_entry.options.get(input_key(num)) or default_input_name(num)

    def output_name(self, num: int) -> str:
        return (
            self.config_entry.options.get(output_key(num)) or default_output_name(num)
        )

    @property
    def input_names(self) -> list[str]:
        return [self.input_name(i) for i in range(1, NUM_INPUTS + 1)]

    @property
    def output_names(self) -> list[str]:
        return [self.output_name(o) for o in range(1, NUM_OUTPUTS + 1)]
