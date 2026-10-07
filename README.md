# SmartWings shades for Home Assistant

Makes SmartWings WM25/L-Z Zigbee roller shades work reliably in Home Assistant's Zigbee integration (ZHA).

Out of the box, these shades misbehave in ZHA:

- Open and Close are swapped.
- The motor sometimes ignores a command, and nothing notices.
- Commands can show an error even when the shade moved.
- The position on the card is often wrong after a move.

This project fixes all four. It has two parts: a ZHA **quirk** (`quirk/zhaquirks/smartwings/wm25lz.py`) that fixes how commands are sent, and a small **integration** that installs the quirk for you and keeps it up to date.

## Requirements

- Home Assistant 2026.10 or later
- ZHA, with your shades already paired

## Install

1. **Install the integration.** In HACS, open ⋮ → Custom repositories, add `https://github.com/polymath-ventures/ha-smartwings` as an **Integration**, then download **SmartWings**. (Or copy `custom_components/smartwings` into `/config/custom_components/`.) Restart Home Assistant.
2. **Add it.** Settings → Devices & services → Add integration → **SmartWings**. There is nothing to configure; it finds your shades by itself.
3. **Tell ZHA where to find the quirk.** Add this to `configuration.yaml` (if you already have a `zha:` section, add just the `custom_quirks_path` line):

   ```yaml
   zha:
     custom_quirks_path: /config/custom_zha_quirks/
   ```

   If you already use a different custom quirks folder, keep it. The integration uses whichever folder is set.

4. **Restart Home Assistant.**

That's it. Settings → Repairs should show nothing from SmartWings. If it shows something, see [Repairs messages](#repairs-messages).

ZHA will log a warning that it loaded custom quirks. That's expected.

## Set the open and closed positions with the remote

Each shade stops at the top and bottom limits programmed with its SmartWings remote, whether you use the remote or Home Assistant. Home Assistant can't change these limits. To set them (see SmartWings' [remote programming guide](https://cdn.shopify.com/s/files/1/0573/0215/5461/files/SmartWings_Remote_Programming_Guide_for_Roller_Shade.pdf)):

- **Bottom:** hold DOWN + STOP for 5 seconds, move the shade to where it should stop, then hold DOWN + STOP for 2 seconds.
- **Top:** the same with UP + STOP.

In Home Assistant, 0 is the bottom limit, 100 is the top limit, and 50 is halfway between.

## What to expect

- **The position updates when the shade stops, not while it moves.** These motors only report their position at the end of a move.
- **If a shade ignores a command, it's sent again** once the shade should have arrived.
- **Moves made with the remote** usually show up when the shade stops. If one doesn't, refresh the shade:

  ```yaml
  action: homeassistant.update_entity
  target:
    entity_id: cover.office_shade
  ```

## Repairs messages

| Message | What to do |
| --- | --- |
| Set ZHA's custom_quirks_path for the SmartWings quirk | Add the `configuration.yaml` lines from step 3, then restart. |
| Restart to load the SmartWings quirk | Restart Home Assistant, or reload ZHA. |
| SmartWings quirk not loaded | ZHA isn't using the quirk for the shades listed. Check the other SmartWings messages first, then make sure you restarted after step 3. |
| SmartWings quirk file is in the way | A different `wm25lz.py` is in your quirks folder. Remove it and restart. |
| SmartWings could not update its quirk file | Check the folder's permissions, then restart. |
| The SmartWings quirk is now part of Home Assistant | You no longer need this project's copy. Delete `wm25lz.py` from your quirks folder and restart. |

## Troubleshooting

- **A shade closes too far, or not far enough.** Reset its limits with the remote (see above).
- **Open closes the shade and Close opens it.** The quirk isn't loaded. Check Settings → Repairs.
- **"Failed to open cover" or "Failed to close cover".** The shade didn't respond. It may be out of range. Try again.
- **The shade didn't move and no error appeared.** The motor ignored the command twice. Try again. If a shade stays stuck, a short move in the other direction (or a press on its remote) usually frees it.

## Limitations

- Home Assistant can't read or set the shade's limits. Use the remote.
- The position doesn't change on the card while the shade is moving.
- The "go to lift value" and tilt commands in ZHA's device panel are refused, because the shade's radio garbles them. The normal controls, voice and automations don't use them.

## Uninstall

Remove the integration from Settings → Devices & services, delete `wm25lz.py` from your quirks folder, remove the `custom_quirks_path` line if nothing else uses it, and restart.

## More detail

How the shades behave over Zigbee, and why the quirk does what it does, is in [docs/device-behavior.md](docs/device-behavior.md).
