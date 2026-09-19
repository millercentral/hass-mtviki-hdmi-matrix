"""One select entity per output: choose which input it shows."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_OUTPUTS, OPTION_NONE
from .coordinator import MatrixConfigEntry, MatrixCoordinator
from .entity import MatrixEntity
from .protocol import MatrixError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MatrixConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        MatrixOutputSelect(coordinator, output) for output in range(1, NUM_OUTPUTS + 1)
    )


class MatrixOutputSelect(MatrixEntity, SelectEntity):
    """Input routed to one output (or None for no signal)."""

    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator: MatrixCoordinator, output: int) -> None:
        super().__init__(coordinator, f"output_{output}")
        self._output = output
        self._attr_name = coordinator.output_name(output)
        self._attr_options = [OPTION_NONE, *coordinator.input_names]

    @property
    def _input(self) -> int | None:
        routing = self.coordinator.data
        if not routing or len(routing) < self._output:
            return None
        return routing[self._output - 1]

    @property
    def current_option(self) -> str | None:
        value = self._input
        if value is None or not 0 <= value < len(self.options):
            return None
        return self.options[value]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Read by the bundled Lovelace card.
        return {
            "output_index": self._output,
            "output_name": self._attr_name,
            "input_index": self._input,
        }

    async def async_select_option(self, option: str) -> None:
        try:
            input_num = self.options.index(option)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            ) from err
        try:
            await self.coordinator.client.route(input_num, self._output)
        except MatrixError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
