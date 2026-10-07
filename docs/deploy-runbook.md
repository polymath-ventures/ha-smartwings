# Deploy runbook: retire the old install, install the integration, accept on every shade

Issue #15. The owner performs every step. Nothing in this runbook has been run yet. It was written on 2026-10-06 from a read-only look at the box, which is on Home Assistant 2026.10.0b2. That version is fine: the integration needs 2026.10.0b0 or later.

Each shade stops at the limits set with its own 433 MHz remote, for the remote and for Home Assistant alike (#54). So there is no stop to record, capture or re-enter. Step 5 only checks each shade's limits with its remote.

## Before you start

1. **#48 must be merged before Step 2.** That PR is the letter, and it holds the full session B evidence. `main` has only a partial copy of `smartwings_bench_B.json`, and Step 2 deletes the box's copy.
2. **Have each shade's remote** to hand. It sets the limits (Step 5), and its Stop halts a shade if anything goes wrong.
3. **Between Step 3 and the second restart in Step 4, do not move any shade from Home Assistant**, voice or a bridge. The old quirk is gone by then and ours is not yet loaded, so ZHA uses the quirk built into Home Assistant, which swaps Open and Close on these shades. Use the remotes.
4. **Time.** About 45 minutes for Steps 0 to 5, plus about 10 minutes per shade for Step 6.
5. **Shell commands** run in the Terminal & SSH add-on (Settings → Add-ons → Terminal & SSH → Open Web UI), where `/config` is the config folder, unless a step says "on the Mac".

**The shades.** Use the short name in the `item` column of `acceptance.csv`.

| Short name | Device | IEEE | Cover |
|---|---|---|---|
| office | Office Shade | 60:83:da:ff:fe:a0:00:02 | `cover.smartwings_wm25_l_z` |
| living-middle | Middle living room smartwings | 70:d0:7e:ff:fe:a0:00:06 | `cover.living_room_living_room_middle_smartwings` |
| living-left | Left living room smartwings | 70:d0:7e:ff:fe:a0:00:08 | `cover.left_living_room_smartwings` |
| living-right | Right living room smartwings | 70:d0:7e:ff:fe:a0:00:07 | `cover.living_room_smartwings_left` |
| master-left-sunshade | Left master sunshade Smartwings | 70:d0:7e:ff:fe:a0:00:09 | `cover.main_bedroom_left_master_sunshade_smartwings` |
| master-left-blackout | Left master blackout Smartwings | 70:d0:7e:ff:fe:a0:00:0a | `cover.left_master_blackout_smartwings` |
| master-right-sunshade | Right master sunshade Smartwings | 60:83:da:ff:fe:a0:00:01 | `cover.main_bedroom_right_master_sunshade_smartwings` |
| master-right-blackout | Right master blackout Smartwings | 70:d0:7e:ff:fe:a0:00:05 | `cover.right_master_blackout_smartwings` |
| guest-sunshade | Guest Sunshade Smartwings | 70:d0:7e:ff:fe:a0:00:0c | `cover.guest_sunshade_smartwings` |
| guest-blackout | Guest blackout Smartwings | 70:d0:7e:ff:fe:a0:00:0b | `cover.guest_blackout_smartwings` |

**There are ten shades.** "Right living room smartwings" was added on 2026-10-06 at 22:32 UTC. If a shade is unavailable ("Left living room smartwings" was on 2026-10-06), skip it and record its rows as `blocked`.

## Step 0: Back up

1. Settings → System → Backups → **Backup now** → **Manual backup**. Choose a full backup: Home Assistant settings and history, and all add-ons and folders. Name it `Before SmartWings #15`.
2. Download it (⋮ → **Download**) and keep the file on the Mac.
3. Make sure you have the backup encryption key (Backups → Configure → Encryption key). A downloaded backup cannot be restored without it.

## Step 1: Copy the research files off the box

The top of `/config` holds the raw data from 2026-10-03/04: about 150 `*.csv` files, `json/sw_*.json` and `scans/`. Part 1's measurements may rest on them alone. Pack them up:

```sh
cd /config && tar czf /config/smartwings-research.tgz *.csv json/sw_*.json scans configuration.yaml.bak* automations.yaml.bak*
```

On the Mac:

```sh
scp -i ~/.ssh/<your-key> root@homeassistant.local:/config/smartwings-research.tgz ~/smartwings-research.tgz
```

Then delete `/config/smartwings-research.tgz` on the box. Leave the files themselves. They do no harm, and you can delete them later once the copy is safe.

## Step 2: Remove the test leftovers

First, **turn off the three SmartWings automations** (Settings → Automations & scenes): "SmartWings: position refresh (start + hourly)", "SmartWings: a typed number becomes the calibration" and "SmartWings: re-read the position after a move". Nothing then acts on a shade while pieces are removed. Step 3 deletes them.

The bench and discovery sessions left a handler and three result files. The repository has copies of the results: `docs/evidence/sessions/2026-10-06-A.json`, `docs/evidence/sessions/2026-10-06-B.json` (complete only once #48 is merged), and `docs/evidence/discovery-office-shade.json`.

```sh
rm /config/custom_components/zha_toolkit/local/user.py
rm -rf /config/custom_components/zha_toolkit/local/__pycache__
rm /config/smartwings_bench_A.json /config/smartwings_bench_B.json /config/zha_discovery_office_shade.json
```

**ZHA Toolkit** is no longer needed. Removing it is the default, but keeping it is fine. To remove it, first delete the `zha_toolkit:` line from `configuration.yaml`, then go to HACS → ZHA Toolkit → ⋮ → **Remove**. The restart in Step 3 completes the removal. The old capture script that used it goes in Step 3.

## Step 3: Uninstall the old setup

Do these in order. The automations are already off (Step 2).

1. **Delete the three SmartWings automations.** Settings → Automations & scenes:
   1. "SmartWings: position refresh (start + hourly)", in `automations.yaml`. Delete it.
   2. "SmartWings: a typed number becomes the calibration" and "SmartWings: re-read the position after a move", which come from the package. They go with the package in 4.
2. **Delete the old integration.** Settings → Devices & services → **SmartWings** → ⋮ → **Delete**. This removes its ten `number.*closed_limit` controls and the nine model-less "SmartWings" devices. Nothing is sent to the shades.
3. **Clean the Shades dashboard** (`/shades` → ✏️ Edit). Delete the Markdown card, the "Stops at (the number a close aims at)" card and the grid of "Capture …" buttons. Keep the "Control" card. Optionally add `cover.living_room_smartwings_left` to it.
4. **Move the old files out**:

   ```sh
   mkdir -p /config/smartwings_retired
   mv /config/packages/smartwings_calibration.yaml /config/smartwings_retired/
   mv /config/custom_zha_quirks/smartwings_wm25lz_readback.py /config/smartwings_retired/
   rm -rf /config/custom_zha_quirks/__pycache__
   mv /config/custom_components/smartwings /config/smartwings_retired/custom_components_smartwings
   mv /config/smartwings_calibrate.py /config/smartwings_calibration.json /config/smartwings_retired/
   ls -la /config/custom_zha_quirks /config/packages /config/custom_components
   ```

   `custom_zha_quirks` and `packages` must be empty, and `custom_components` must have no `smartwings`. The new integration installs into the same folder, so the old one must go entirely. **Keep** `zha: custom_quirks_path: /config/custom_zha_quirks` in `configuration.yaml`, and keep the folder; the new quirk goes there. `homeassistant: packages: !include_dir_named packages` is harmless with an empty folder.
5. **Check the configuration, then restart.** Developer tools → YAML → **Check configuration** must pass. Then Settings → System → ⋮ → **Restart Home Assistant**.
6. **Remove the leftover registry entries.** Settings → Devices & services → Entities, search `smartwings`. Select the entries shown as not provided or unavailable: the nine `input_number.smartwings_*_closed_position`, `script.smartwings_capture_closed_position`, `script.smartwings_close`, and the three SmartWings automations if still listed. Then **Remove selected**. Do not select the shades' own ZHA entities (`cover.*`, `sensor.*`, `button.*`, `switch.*`, `update.*`).
7. **Check it is gone.** No SmartWings integration under Devices & services. Under Devices, searching "SmartWings" shows only the shades (model WM25/L-Z). Developer tools → States, filtered on `closed_`, shows nothing.

From here until the second restart in Step 4, **do not move any shade from Home Assistant** (Before you start, item 3).

## Step 4: Install the new integration

As in the README's Install section:

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/polymath-ventures/ha-smartwings`, category **Integration** → **SmartWings** → **Download**. Or copy the repository's `custom_components/smartwings` to `/config/custom_components/smartwings` by hand.
2. **Restart.**
3. Settings → Devices & services → **Add integration** → **SmartWings** → Submit. It asks nothing.
4. Settings → Repairs shows **Restart to load the SmartWings quirk**. **Restart** again.
5. **Confirm it is loaded.**
   1. Settings → Repairs shows no SmartWings issue, and in particular no **SmartWings quirk not loaded**.
   2. `head -1 /config/custom_zha_quirks/wm25lz.py` prints the line starting `# Installed by the SmartWings integration for Home Assistant`.
   3. Settings → System → Logs shows "Loaded custom quirks. Please contribute them to …". That is expected.

   Record one row, item `quirk-loaded`.

The shades can now be used from Home Assistant again.

## Step 5: Check each shade's limits with its remote

For each shade, with its remote:

1. Press **DOWN**. The shade must stop by itself where it should be when closed, with the fabric smooth.
2. Press **UP**. It must stop by itself where it should be when open.
3. If either end is wrong, set it again, as in SmartWings' remote guide (README, Install, step 4):
   1. **Bottom.** Hold DOWN and STOP for 5 s. Move the shade to the right place. Hold DOWN and STOP for 2 s.
   2. **Top.** The same with UP: hold UP and STOP for 5 s, move it, then hold UP and STOP for 2 s.

   Then repeat 1 and 2.

Record one row per shade, item `limits-<short name>`, noting in `observed` whether you re-set either limit.

## Step 6: Acceptance on every shade

Test `ACCEPT-CARD-CONTROLS` in `docs/test-plan.md`. Do this one shade at a time, at the shade, with its remote, from its card (Settings → Devices → the shade, or the Shades dashboard). Wait until the shade has stopped before the next control.

1. **Close**, from fully open. **Expected:** it goes down and stops at the remote's bottom limit, fabric smooth. Within 2 minutes the card shows Closed, 0.
2. **Open.** **Expected:** it goes up and stops at the remote's top limit. The card shows Open, 100.
3. **Slider to 50.** **Expected:** it goes down to about halfway between the two limits. The card shows about 50.
4. **Stop mid-move.** Press Open. When the shade is about halfway up, press the card's Stop (■). **Expected:** the shade halts, no error is shown, and within a few seconds the card shows where it stopped.

**No error should appear** for any control. If a shade moves the wrong way, passes a limit, or shows an error, stop it with the remote. Record the row as `no` and do not continue with that shade. That ends its series until the cause is understood.

**After all shades: one restart.** Settings → System → ⋮ → **Restart Home Assistant**. When ZHA is back (about 2 minutes), on each shade do **Close**, then **Open**, from the card, with the same expectations.

**Record** one row per control in `docs/evidence/acceptance.csv`. The columns are `date,ieee,item,action,expected,observed,pass`. `item` is `card-<short name>-<control>`, with control `close`, `open`, `slider-50` or `stop`, or `restart-close` or `restart-open` after the restart. `pass` is `yes`, `no` or `blocked`. Quote a field that contains a comma. Example:

```csv
2026-10-08 10:15,60:83:da:ff:fe:a0:00:02,card-office-close,Close from card,"stops at remote's bottom limit; fabric smooth; card Closed, 0","stopped at the bottom limit; smooth; card Closed 0 after ~70 s",yes
```

**When done:** commit `acceptance.csv` to a branch for issue #15, or hand it to the agent. Then delete `/config/smartwings_retired/`.

## Rollback

Restore the Step 0 backup. Settings → System → Backups → **Before SmartWings #15** → **Restore**, enter the encryption key, and confirm. Home Assistant restarts with the old setup.

If the UI is not reachable, run `ha backups` in the SSH add-on to find the backup's slug, then run `ha backups restore <slug> --password '<encryption key>'`. If the backup is no longer on the box, upload the downloaded copy first: Backups → ⋮ → **Upload backup**.

A restore loses everything done after the backup, including history, automation edits and any Zigbee pairing.
