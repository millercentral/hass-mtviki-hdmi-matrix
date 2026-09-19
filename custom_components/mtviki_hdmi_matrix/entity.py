"""Base entity for the MT-ViKI HDMI Matrix integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MODEL, DOMAIN, MANUFACTURER
from .coordinator import MatrixCoordinator


class MatrixEntity(CoordinatorEntity[MatrixCoordinator]):
    """Common device info and availability for every matrix entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MatrixCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        info = coordinator.client.info
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=info.model or DEFAULT_MODEL,
            sw_version=info.firmware,
            name=entry.title,
        )
