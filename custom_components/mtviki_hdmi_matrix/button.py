"""Buttons: recall/save presets 1-16 and route one input to every output."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NUM_INPUTS, NUM_PRESETS, OPTION_NONE
from .coordinator import MatrixConfigEntry, MatrixCoordinator
from .entity import MatrixEntity
from .protocol import MatrixClient, MatrixError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MatrixConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[MatrixButton] = []

    for num in range(0, NUM_INPUTS + 1):
        label = coordinator.input_name(num) if num else OPTION_NONE
        entities.append(
            MatrixButton(
                coordinator,
                key=f"all_input_{num}",
                name=f"All outputs to {label}" if num else "All outputs off",
                icon="mdi:video-switch" if num else "mdi:video-off",
                action=lambda c, n=num: c.route_all(n),
                attributes={"action": "route_all", "input_index": num},
            )
        )
    for preset in range(1, NUM_PRESETS + 1):
        entities.append(
            MatrixButton(
                coordinator,
                key=f"recall_{preset}",
                name=f"Recall preset {preset}",
                icon="mdi:playlist-play",
                action=lambda c, p=preset: c.recall_preset(p),
                attributes={"action": "recall", "preset": preset},
            )
        )
    for preset in range(1, NUM_PRESETS + 1):
        entities.append(
            MatrixButton(
                coordinator,
                key=f"save_{preset}",
                name=f"Save preset {preset}",
                icon="mdi:content-save",
                action=lambda c, p=preset: c.save_preset(p),
                attributes={"action": "save", "preset": preset},
                category=EntityCategory.CONFIG,
            )
        )
    async_add_entities(entities)


class MatrixButton(MatrixEntity, ButtonEntity):
    """A single fire-and-forget switch command."""

    def __init__(
        self,
        coordinator: MatrixCoordinator,
        *,
        key: str,
        name: str,
        icon: str,
        action: Callable[[MatrixClient], Awaitable[None]],
        attributes: dict[str, Any],
        category: EntityCategory | None = None,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_entity_category = category
        self._attr_extra_state_attributes = attributes
        self._action = action

    async def async_press(self) -> None:
        try:
            await self._action(self.coordinator.client)
        except MatrixError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
