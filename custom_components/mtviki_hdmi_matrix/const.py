"""Constants for the MT-ViKI HDMI Matrix integration."""

from __future__ import annotations

from typing import Final

from .protocol import DEFAULT_PORT, NUM_INPUTS, NUM_OUTPUTS, NUM_PRESETS

DOMAIN: Final = "mtviki_hdmi_matrix"
MANUFACTURER: Final = "MT-ViKI"
DEFAULT_MODEL: Final = "HD4X2-X"
DEFAULT_NAME: Final = "MT-ViKI HDMI Matrix"

# How long setup waits for the first connection before HA retries later.
SETUP_CONNECT_TIMEOUT: Final = 10.0

# Option shown in the output selects for "no signal" (input 0).
OPTION_NONE: Final = "None"

CARD_FILENAME: Final = "mtviki-matrix-card.js"
CARD_URL_BASE: Final = f"/{DOMAIN}"

__all__ = [
    "CARD_FILENAME",
    "CARD_URL_BASE",
    "DEFAULT_MODEL",
    "DEFAULT_NAME",
    "DEFAULT_PORT",
    "DOMAIN",
    "MANUFACTURER",
    "NUM_INPUTS",
    "NUM_OUTPUTS",
    "NUM_PRESETS",
    "OPTION_NONE",
    "SETUP_CONNECT_TIMEOUT",
    "input_key",
    "output_key",
]


def input_key(num: int) -> str:
    """Options key holding the friendly name of input `num`."""
    return f"input_{num}_name"


def output_key(num: int) -> str:
    """Options key holding the friendly name of output `num`."""
    return f"output_{num}_name"


def default_input_name(num: int) -> str:
    return f"Input {num}"


def default_output_name(num: int) -> str:
    return f"Output {num}"
