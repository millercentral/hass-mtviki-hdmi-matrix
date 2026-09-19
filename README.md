# MT-ViKI HDMI Matrix for Home Assistant

Local control of the **MT-ViKI HD4X2-X** 4×2 HDMI matrix switcher over its TCP control port. Route any input to either output from Home Assistant, recall and save the switch's 16 presets, and use the bundled matrix card on your dashboards.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=millercentral&repository=hass-mtviki-hdmi-matrix&category=integration)

## Features

- **Output selectors**: one `select` entity per output with the options *None* and your four input names.
- **Instant sync**: a persistent connection picks up changes made with the switch's front-panel buttons or IR remote immediately; it reconnects on its own if the switch or network drops.
- **Presets**: *Recall preset 1–16* buttons, and *Save preset 1–16* buttons (under the device's Configuration section).
- **All outputs**: buttons that send one input (or no signal) to every output.
- **Friendly names**: rename the inputs and outputs from the device's *Configure* dialog.
- **Matrix card**: a bundled dashboard card, loaded automatically with nothing extra to install.

## Installation (HACS)

1. In Home Assistant open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/millercentral/hass-mtviki-hdmi-matrix` with type **Integration**.
3. Search HACS for **MT-ViKI HDMI Matrix**, click **Download**, and restart Home Assistant.

## Setup

1. Give the switch a fixed IP address (a DHCP reservation on your router is easiest).
2. Go to **Settings → Devices & services → Add integration → MT-ViKI HDMI Matrix**.
3. Enter the switch's **IP address** and **control port** (8080 by default). The integration connects and reads the model and firmware before finishing.
4. On the device page click **Configure** to name the inputs (e.g. *Apple TV*, *PC*) and outputs (e.g. *Living Room TV*, *Projector*). The integration reloads with the new names.

To change the IP address or port later, use **⋮ → Reconfigure** on the integration entry.

## Entities

| Entity | Purpose |
| --- | --- |
| `select.<device>_output_1`, `select.<device>_output_2` | Input shown on each output (`None` = no signal) |
| `button.<device>_all_outputs_to_input_1` … `_input_4` | Send one input to every output |
| `button.<device>_all_outputs_off` | No signal on any output |
| `button.<device>_recall_preset_1` … `_16` | Load a stored routing preset |
| `button.<device>_save_preset_1` … `_16` | Store the current routing (configuration entities) |

Entity IDs stay the same when you rename inputs or outputs; only the display names change.

### Automation example

```yaml
action: select.select_option
target:
  entity_id: select.mt_viki_hd4x2_x_output_1
data:
  option: Apple TV
```

## Matrix card

Edit a dashboard → **Add card** → search for **MT-ViKI Matrix Card**. With no options it finds your matrix automatically. Outputs are rows, inputs are columns; tap a cell to route. The *All outputs* row and the preset controls sit underneath. Saving a preset asks for a second tap so you don't overwrite one by accident.

```yaml
type: custom:mtviki-matrix-card
# all optional:
device_id: 0123456789abcdef   # pick a specific matrix if you have more than one
title: HDMI Matrix
show_all: true
show_presets: true
```

If the card doesn't appear after an update, refresh the browser (the integration serves the card and busts the cache on every new version).

## Troubleshooting

Enable debug logging to see every command and reply:

```yaml
logger:
  logs:
    custom_components.mtviki_hdmi_matrix: debug
```

The switch's control protocol is plain text over TCP. `scripts/smoke_test.py` checks a switch from any computer with Python (standard library only):

```sh
python scripts/smoke_test.py 192.168.0.245 --write --listen 20
```

## Protocol reference

| Command | Effect | Reply |
| --- | --- | --- |
| `[x]X[y].` | Input *x* to output *y* (x = 0: no signal) | `SWS a b c d` |
| `[x]ALL.` | Input *x* to every output | `SWS a b c d` |
| `Save[n].` / `Recall[n].` | Store / load preset *n* (1–16) | `Save[n].` / `SWS …` |
| `GetSWS.` | Current routing | `SWS a b c d` |
| `GetServiceNum.` | Model and firmware | `ServiceNum HD4X2-X Ver1.0` |

Commands end with `.` and CR/LF. The switch also sends `SWS …` on its own whenever routing changes from the front panel or IR remote.

## Development

```sh
pip install -r requirements_test.txt
python -m pytest
```

Tests run the integration inside a test Home Assistant against a simulated switch (`tests/fake_switch.py`).

## License

MIT
