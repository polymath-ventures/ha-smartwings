# Working on ha-smartwings

Home Assistant support for SmartWings WM25/L-Z Zigbee roller shades under ZHA.

## Layout

- `quirk/zhaquirks/smartwings/wm25lz.py` — the ZHA quirk, written in zha-device-handlers
  style so it can be submitted upstream. It must not import Home Assistant or read files.
- `custom_components/smartwings/` — the integration. It installs the quirk into ZHA's
  `custom_quirks_path`, raises Repairs issues when the quirk isn't loaded, and finds the
  quirk only by its quirk ID `smartwings.wm25lz`.
- `docs/device-behavior.md` — how the shades behave over Zigbee, and why the quirk does what it does.

## Commands

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
```

## Rules

- ZCL lift is 0 = open, 100 = closed. HA cover position is 0 = closed, 100 = open. Name
  the space of every stored or sent position, and convert in one place only.
- Open sends `up_open`, close sends `down_close`, a position sends `go_to_lift_percentage`,
  exactly as stock ZHA does. Only the device's measured quirks are handled differently.
- Never fake a Stop with a move to the last known position: that position is stale while
  the shade travels.
- An unreadable position is not movement, and movement away from the target is not success.
- The shade's top and bottom limits are set with its remote. The motor enforces them for
  Zigbee commands too, so the code keeps no limits of its own.
- Prefer what Home Assistant and ZHA already do over custom behaviour.
- Never send a command to a real shade without the owner present and agreeing.
