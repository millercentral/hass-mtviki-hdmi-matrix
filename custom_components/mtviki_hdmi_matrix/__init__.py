"""The MT-ViKI HDMI Matrix integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    CARD_FILENAME,
    CARD_URL_BASE,
    DEFAULT_PORT,
    DOMAIN,
    SETUP_CONNECT_TIMEOUT,
)
from .coordinator import MatrixConfigEntry, MatrixCoordinator, MatrixRuntimeData
from .protocol import MatrixClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SELECT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled Lovelace card and load it on every dashboard."""
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    if hass.data.get(_CARD_REGISTERED) or hass.http is None:
        return
    # Imported lazily: both are always present in a real install, but not in
    # every test environment.
    from homeassistant.components.frontend import (  # noqa: PLC0415
        DATA_EXTRA_MODULE_URL,
        add_extra_js_url,
    )
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    if DATA_EXTRA_MODULE_URL not in hass.data:
        _LOGGER.debug("Frontend not loaded; skipping card registration")
        return

    integration = await async_get_integration(hass, DOMAIN)
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    url = f"{CARD_URL_BASE}/{CARD_FILENAME}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(url, str(card_path), cache_headers=False)]
    )
    # The version query string makes browsers fetch the new card after updates.
    add_extra_js_url(hass, f"{url}?v={integration.version}")
    hass.data[_CARD_REGISTERED] = True


async def async_setup_entry(hass: HomeAssistant, entry: MatrixConfigEntry) -> bool:
    """Connect to the switch and create entities."""
    client = MatrixClient(entry.data[CONF_HOST], entry.data.get(CONF_PORT, DEFAULT_PORT))
    await client.start()

    if not await client.wait_connected(SETUP_CONNECT_TIMEOUT) or not await _wait_routing(
        client
    ):
        await client.stop()
        raise ConfigEntryNotReady(
            f"Cannot connect to MT-ViKI matrix at {client.host}:{client.port}"
        )

    coordinator = MatrixCoordinator(hass, entry, client)
    coordinator.async_set_updated_data(list(client.routing or []))
    entry.runtime_data = MatrixRuntimeData(client=client, coordinator=coordinator)

    async def _stop(_: Event) -> None:
        await client.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop)
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _wait_routing(client: MatrixClient) -> bool:
    """After connecting, the client queries routing; wait briefly for it."""
    try:
        async with asyncio.timeout(SETUP_CONNECT_TIMEOUT):
            while client.routing is None:
                await asyncio.sleep(0.05)
    except TimeoutError:
        return False
    return True


async def _async_options_updated(hass: HomeAssistant, entry: MatrixConfigEntry) -> None:
    """Reload so entity names and select options pick up renamed inputs/outputs."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MatrixConfigEntry) -> bool:
    """Disconnect from the switch."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.coordinator.async_shutdown()
        await entry.runtime_data.client.stop()
    return unloaded
