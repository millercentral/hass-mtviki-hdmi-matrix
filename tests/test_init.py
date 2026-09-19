"""Setup, entities, push updates and availability."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtviki_hdmi_matrix.const import DOMAIN

from .fake_switch import FakeSwitch

OUT1 = "select.mt_viki_hd4x2_x_output_1"
OUT2 = "select.mt_viki_hd4x2_x_output_2"


async def _wait_state(hass: HomeAssistant, entity_id: str, value: str) -> None:
    async with asyncio.timeout(5):
        while (s := hass.states.get(entity_id)) is None or s.state != value:
            await asyncio.sleep(0.02)
            await hass.async_block_till_done()


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_setup_creates_device_and_entities(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _setup(hass, entry)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.manufacturer == "MT-ViKI"
    assert device.model == "HD4X2-X"
    assert device.sw_version == "1.0"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = sorted(e.domain for e in entities)
    assert domains.count("select") == 2
    assert domains.count("button") == 5 + 16 + 16

    state = hass.states.get(OUT1)
    assert state.state == "Input 1"
    assert state.attributes["options"] == ["None", "Input 1", "Input 2", "Input 3", "Input 4"]
    assert state.attributes["output_index"] == 1
    assert state.attributes["input_index"] == 1
    assert hass.states.get(OUT2).state == "None"

    recall = hass.states.get("button.mt_viki_hd4x2_x_recall_preset_3")
    assert recall.attributes["action"] == "recall"
    assert recall.attributes["preset"] == 3
    await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_unreachable(hass: HomeAssistant) -> None:
    bad = MockConfigEntry(
        domain=DOMAIN, title="x", unique_id="127.0.0.1",
        data={"host": "127.0.0.1", "port": 1},
    )
    bad.add_to_hass(hass)
    with patch("custom_components.mtviki_hdmi_matrix.SETUP_CONNECT_TIMEOUT", 0.3):
        await hass.config_entries.async_setup(bad.entry_id)
        await hass.async_block_till_done()
    assert bad.state is ConfigEntryState.SETUP_RETRY


async def test_select_routes_input(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    await _setup(hass, entry)
    await hass.services.async_call(
        "select", "select_option",
        {ATTR_ENTITY_ID: OUT2, "option": "Input 3"}, blocking=True,
    )
    assert switch.received[-1] == "3X2."
    await _wait_state(hass, OUT2, "Input 3")

    await hass.services.async_call(
        "select", "select_option",
        {ATTR_ENTITY_ID: OUT1, "option": "None"}, blocking=True,
    )
    assert switch.received[-1] == "0X1."
    await _wait_state(hass, OUT1, "None")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_front_panel_change_is_pushed(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    await _setup(hass, entry)
    await switch.front_panel(4, 1)
    await _wait_state(hass, OUT1, "Input 4")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_buttons(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    await _setup(hass, entry)

    await hass.services.async_call(
        "button", "press",
        {ATTR_ENTITY_ID: "button.mt_viki_hd4x2_x_all_outputs_to_input_2"}, blocking=True,
    )
    assert switch.received[-1] == "2ALL."
    await _wait_state(hass, OUT1, "Input 2")
    await _wait_state(hass, OUT2, "Input 2")

    await hass.services.async_call(
        "button", "press",
        {ATTR_ENTITY_ID: "button.mt_viki_hd4x2_x_save_preset_7"}, blocking=True,
    )
    assert switch.received[-1] == "Save7."

    await hass.services.async_call(
        "button", "press",
        {ATTR_ENTITY_ID: "button.mt_viki_hd4x2_x_all_outputs_off"}, blocking=True,
    )
    assert switch.received[-1] == "0ALL."
    await _wait_state(hass, OUT1, "None")

    await hass.services.async_call(
        "button", "press",
        {ATTR_ENTITY_ID: "button.mt_viki_hd4x2_x_recall_preset_7"}, blocking=True,
    )
    assert switch.received[-1] == "Recall7."
    await _wait_state(hass, OUT1, "Input 2")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_command_error_raises(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    await _setup(hass, entry)
    switch.silent = True
    client = entry.runtime_data.client
    client._command_timeout = 0.2
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select", "select_option",
            {ATTR_ENTITY_ID: OUT1, "option": "Input 2"}, blocking=True,
        )
    switch.silent = False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_then_recovers(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    await _setup(hass, entry)
    client = entry.runtime_data.client
    client._reconnect_min = 0.05

    port = switch.port
    await switch.stop()
    await _wait_state(hass, OUT1, STATE_UNAVAILABLE)

    await switch.start(port)
    await switch.front_panel(3, 1)
    await _wait_state(hass, OUT1, "Input 3")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch) -> None:
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    await asyncio.sleep(0.05)
    assert switch.client_count == 0
