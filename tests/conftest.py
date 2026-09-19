"""Shared fixtures."""

from __future__ import annotations

import pytest

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtviki_hdmi_matrix.const import DOMAIN

from .fake_switch import FakeSwitch


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/ in every test."""


@pytest.fixture(autouse=True)
def _allow_sockets(socket_enabled):
    """Tests talk to the simulated switch over real localhost sockets."""


@pytest.fixture
async def switch():
    fake = FakeSwitch()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def entry(hass: HomeAssistant, switch: FakeSwitch) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="MT-ViKI HD4X2-X",
        unique_id="127.0.0.1",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: switch.port},
    )
    config_entry.add_to_hass(hass)
    return config_entry
