# SmartWings shades for Home Assistant

This project makes SmartWings WM25/L-Z Zigbee roller shades work reliably in Home Assistant's Zigbee integration (ZHA).

Out of the box, these shades misbehave in ZHA:

- Open and Close are swapped.
- The motor sometimes ignores a command, and Home Assistant doesn't send it again.
- Home Assistant can show an error even when the shade moved.
- The shade's card often shows the wrong position after a move.

This project fixes all four. It is one small **integration** that adds a ZHA **quirk** (`custom_components/smartwings/quirk.py`) to ZHA. The quirk fixes how commands are sent to the shades.

## Requirements

- Home Assistant 2026.10 or later
- ZHA, with your shades already paired

## Install

1. **Install the integration.** In HACS, open ⋮ → Custom repositories, add `https://github.com/polymath-ventures/ha-smartwings` as an **Integration**, then download **SmartWings**. (Or copy `custom_components/smartwings` into `/config/custom_components/`.)
2. **Restart Home Assistant.**
3. **Add the integration.** Settings → Devices & services → Add integration → **SmartWings**. You don't configure anything; the integration finds your shades by itself.

That's it. You don't edit `configuration.yaml` or copy any quirk file.

When you add the integration, it reloads ZHA once so that ZHA applies the quirk to your shades. Your Zigbee devices are unavailable for a few seconds while ZHA reloads. After a Home Assistant restart, the integration may need to reload ZHA once more, with the same short gap.

Settings → Repairs should show nothing from SmartWings. If it shows something, see [Repairs messages](#repairs-messages).

## Set the open and closed positions with the remote

Each shade stops at the top and bottom limits programmed with its SmartWings remote, whether you use the remote or Home Assistant. Home Assistant can't change these limits. To set them (see SmartWings' [remote programming guide](https://cdn.shopify.com/s/files/1/0573/0215/5461/files/SmartWings_Remote_Programming_Guide_for_Roller_Shade.pdf)):

- **Bottom:** hold DOWN + STOP for 5 seconds, move the shade to where it should stop, then hold DOWN + STOP for 2 seconds.
- **Top:** the same with UP + STOP.

In Home Assistant, 0 is the bottom limit, 100 is the top limit, and 50 is halfway between.

## What to expect

- **The position updates when the shade stops, not while it moves.** These motors only report their position at the end of a move.
- **If a shade ignores a command, the quirk usually notices and sends it again** once the shade should have arrived.
- **Moves made with the remote** may not show in Home Assistant. If one doesn't, refresh the shade:

  ```yaml
  action: homeassistant.update_entity
  target:
    entity_id: cover.office_shade
  ```

## Repairs messages

| Message | What to do |
| --- | --- |
| SmartWings quirk not loaded | ZHA isn't using the SmartWings quirk for the shades listed. Another quirk for these shades may take precedence, such as a file in your ZHA custom quirks folder: remove it, then restart Home Assistant. If the message says ZHA's quirks are turned off, remove `enable_quirks: false` from the `zha:` section of `configuration.yaml`, then restart. |

## Troubleshooting

- **A shade closes too far, or not far enough.** Reset its limits with the remote (see above).
- **Open closes the shade and Close opens it.** Check Settings → Repairs: the quirk is probably not loaded. If it is, the shade's direction may have been reversed when it was installed.
- **"Failed to open cover" or "Failed to close cover".** The shade didn't confirm the command, or another command to the same shade got in the way. The shade may be out of range. Try again.
- **The shade didn't move and no error appeared.** The shade's radio accepted the command, but the motor didn't act on it, and the quirk's retry didn't help. Try again. If a shade stays stuck, a short move in the other direction (or a press on its remote) usually frees it.

## Limitations

- Home Assistant can't read or set the shade's limits. Use the remote.
- The position doesn't change on the card while the shade is moving.
- The quirk refuses the "go to lift value" and tilt commands in ZHA's device panel, because the shade's radio garbles them. The normal controls, voice and automations don't use them.

## Uninstall

Remove the integration from Settings → Devices & services (SmartWings → ⋮ → Delete). If you installed it with HACS, remove it in HACS too; if you copied it, delete `/config/custom_components/smartwings`. Then restart Home Assistant. ZHA then goes back to the quirk that comes with Home Assistant, which swaps Open and Close for these shades.

## More detail

How the shades behave over Zigbee, and why the quirk does what it does, is in [docs/device-behavior.md](docs/device-behavior.md).
