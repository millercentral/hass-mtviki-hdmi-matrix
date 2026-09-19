"""Config, reconfigure and options flow tests."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtviki_hdmi_matrix.const import DOMAIN

from .fake_switch import FakeSwitch


async def test_user_flow_success(hass: HomeAssistant, switch: FakeSwitch) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: " 127.0.0.1 ", CONF_PORT: switch.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MT-ViKI HD4X2-X"
    assert result["data"] == {CONF_HOST: "127.0.0.1", CONF_PORT: switch.port}
    assert result["result"].unique_id == "127.0.0.1"
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 1}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unexpected_error(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.mtviki_hdmi_matrix.config_flow.probe",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: 8080}
        )
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_already_configured(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: switch.port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Move the switch to a new port.
    await switch.stop()
    new_port = await switch.start()

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "127.0.0.1", CONF_PORT: new_port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PORT] == new_port
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    names = {
        "input_1_name": "Apple TV",
        "input_2_name": "PC",
        "input_3_name": "Xbox",
        "input_4_name": "Chromecast",
        "output_1_name": "Living Room TV",
        "output_2_name": "Projector",
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**names, "input_2_name": "apple tv"}
    )
    assert result["errors"] == {"base": "duplicate_input_names"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**names, "input_4_name": "none"}
    )
    assert result["errors"] == {"base": "reserved_input_name"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], names
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # The entry reloaded and entities use the new names.
    # Entity IDs are stable; the display name and options change.
    state = hass.states.get("select.mt_viki_hd4x2_x_output_1")
    assert state.attributes["friendly_name"] == "MT-ViKI HD4X2-X Living Room TV"
    assert state.attributes["output_name"] == "Living Room TV"
    assert state.attributes["options"] == ["None", "Apple TV", "PC", "Xbox", "Chromecast"]
    assert state.state == "Apple TV"
    button = hass.states.get("button.mt_viki_hd4x2_x_all_outputs_to_input_3")
    assert button.attributes["friendly_name"] == "MT-ViKI HD4X2-X All outputs to Xbox"
    await hass.config_entries.async_unload(entry.entry_id)
