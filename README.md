# SmartWings WM25/L-Z shades in Home Assistant

This repository makes SmartWings WM25/L-Z Zigbee roller shades behave under Home Assistant's Zigbee Home Automation (ZHA) integration. It has two parts that work together:

1. **The quirk**, one file: `quirk/zhaquirks/smartwings/wm25lz.py`. ZHA loads it for each shade and it changes what is sent to the motor.
2. **The integration**, `custom_components/smartwings`. It installs the quirk for ZHA, keeps it up to date, and tells you when the quirk is not loaded.

Where each shade stops, at the top and at the bottom, is set with its own remote (Install, step 4). The motor stops there for Home Assistant's Open, Close and position slider too.

The design record behind every statement here is in [docs/](docs/README.md).

## What it does

### The quirk

The motors stop every Zigbee move at the limits set with their 433 MHz remote, and position 0 to 100 runs between those limits (issue #54). They sometimes ignore the first command after idling, and they report their position only when a move ends: a read while the shade travels returns where it was before the move. Their radio also answers each command twice, once "done" and once "unsupported". The quirk:

1. **Sends Open, Close, Stop and positions as Home Assistant does.** Open is the standard open command (`up_open`), close the standard close command (`down_close`), and a position the standard "go to lift percentage" with the lift ZHA computes from Home Assistant's position (lift = 100 − position), passed through unchanged. The quirk built into ZHA swaps open and close, which is wrong for these shades, so that swap is not used (Part 1 §3c).
2. **Shows no error for the radio's second reply.** For open, close, set position and Stop, the radio's "unsupported" answer only means it passed the command on, so the quirk reports it as done and Home Assistant shows no error. Neither answer says whether the motor moved.
3. **Re-sends a command the motor ignored.** Each open, close or set-position is sent once and returns as soon as the shade's radio accepts it, as with any ZHA cover. Once the shade should have arrived, if neither its report nor a read shows it moved toward the target, the quirk sends the same command once more. Sending the same target twice is harmless: the shade moves once. A command whose frame the radio never answers is sent again once at once, and fails with ZHA's usual error if that is lost too (see Known limitations).
4. **Shows the final position.** After each command it waits for the shade's report at the end of the move. If none arrives, it reads the position once the shade should have arrived, so the card normally ends where the shade stopped. It reads at most three times within 2 minutes (again after a re-send); if it has not seen the shade stop by then, it may read once more 5 minutes later. Otherwise refresh the cover (see "What the cover shows").

It refuses three commands the shade's radio garbles (Known limitations, item 4). It keeps the built-in quirk's battery percentage correction, which doubles the reported value: the radio passes on the motor's battery figure unchanged, which is inferred to be whole percent where Zigbee expects half percent (a direct reading is still to be taken), so the battery shows the motor's own figure.

### The integration

1. A Repairs issue names every shade for which ZHA did not load the quirk.
2. It installs the quirk file into ZHA's `custom_quirks_path` folder and keeps it up to date. Once the quirk ships with Home Assistant, it stops updating its copy and tells you that you may delete it (see Install).

## Requirements

1. Home Assistant 2026.10 or later. It is tested on 2026.10.0b0.
2. ZHA set up, with the shades paired to it.

## Install

ZHA chooses each device's quirk when it starts, before any custom integration loads. Until this quirk is released in zha-quirks and ships with Home Assistant, the only way to give it to ZHA is ZHA's `custom_quirks_path` folder, so setting `custom_quirks_path` is required until then. The integration puts the quirk file there for you.

### 1. Set `custom_quirks_path`

Add this to `configuration.yaml`. If you already have a `zha:` section, add only the `custom_quirks_path` line to it. If you already use another folder for custom quirks, keep yours: the integration uses whichever folder is set.

```yaml
zha:
  custom_quirks_path: /config/custom_zha_quirks/
```

The folder must exist, or Home Assistant rejects the setting. If it does not exist yet, install the integration first: it creates `/config/custom_zha_quirks/` and puts the quirk in it, and a Repairs issue then gives you this line.

### 2. The integration

With HACS:

1. HACS → ⋮ → Custom repositories. Add `https://github.com/polymath-ventures/ha-smartwings` with the category **Integration**.
2. Download **SmartWings**, then restart Home Assistant.

Or by hand: copy `custom_components/smartwings` into `/config/custom_components/smartwings`, then restart Home Assistant.

Then add it: Settings → Devices & services → Add integration → **SmartWings**. It asks nothing, and it has nothing to configure later. It needs ZHA to be set up first, and it can be added once. It finds every WM25/L-Z in ZHA by itself.

### 3. Restart once more

When it is added, the integration copies its quirk into the `custom_quirks_path` folder as `wm25lz.py`. ZHA loads quirks only when it starts, so Settings → Repairs shows **Restart to load the SmartWings quirk** (in place of "SmartWings quirk not loaded"). Restart Home Assistant, or reload ZHA (Settings → Devices & services → Zigbee Home Automation → ⋮ → Reload). ZHA then logs a warning that it loaded custom quirks. That is expected.

After an update of the integration that changes the quirk, it replaces the file and asks for a restart again.

The integration writes only `wm25lz.py` in that folder, replaces it only when it is a plain file (not a link) whose first line is its own marker (`# Installed by the SmartWings integration for Home Assistant, …`), and never deletes it. Delete that line to keep a copy as your own: the integration then leaves the file alone. If an unmarked `wm25lz.py` is not a working SmartWings quirk, a Repairs issue says so.

Repairs issues you may see:

1. **Set ZHA's custom_quirks_path for the SmartWings quirk.** `custom_quirks_path` is not set. The issue gives the line to add; add it and restart.
2. **Restart to load the SmartWings quirk.** The quirk file was installed or updated. Restart, or reload ZHA.
3. **SmartWings quirk file is in the way.** A `wm25lz.py` without the marker (or a link) is in the folder and ZHA did not load the SmartWings quirk from it. Delete it or move it out of the folder, then restart: the integration installs its own copy and asks for one more restart.
4. **SmartWings could not update its quirk file.** Writing the file failed; the issue gives the reason. Fix the folder's permissions, or copy the file by hand (below), then restart.
5. **The SmartWings quirk is now part of Home Assistant.** The quirk ships with Home Assistant, so the integration no longer updates its copy. You may delete `wm25lz.py` and restart; you can also remove the `custom_quirks_path` line if nothing else uses it. The integration never deletes the file itself.

### Installing the quirk by hand instead

You can still copy the quirk yourself, for example to try a version from this repository:

1. Copy `quirk/zhaquirks/smartwings/wm25lz.py` from this repository into the `custom_quirks_path` folder, keeping its name: `/config/custom_zha_quirks/wm25lz.py`. Copy only the file. Do not point `custom_quirks_path` at the repository's `quirk/` folder.
2. Restart Home Assistant.

A copy that keeps the marker line is replaced by the integration's own version whenever they differ. Delete the line to keep your copy.

### 4. Set each shade's limits with its remote

Each shade stops where its remote's limits are set, whether you move it with the remote or from Home Assistant. If a shade closes too far or not far enough, set its limits again with the remote, as in SmartWings' [remote programming guide for roller shades](https://cdn.shopify.com/s/files/1/0573/0215/5461/files/SmartWings_Remote_Programming_Guide_for_Roller_Shade.pdf):

1. **Bottom.** Hold DOWN and STOP together for 5 seconds. Move the shade to where it should stop when closed. Hold DOWN and STOP together for 2 seconds to save it.
2. **Top.** The same with UP: hold UP and STOP for 5 seconds, move the shade to where it should stop when open, then hold UP and STOP for 2 seconds.

Home Assistant cannot set or read these limits (Known limitations, item 5). After you change them, close and open the shade once from Home Assistant so the card shows its new ends.

### Check that it worked

1. Settings → Repairs shows no "SmartWings quirk not loaded" issue, and no other SmartWings issue.
2. On each shade's card, Open, Close, Stop and the position slider move the shade, stop it at its remote's limits, and show no error.

## What the cover shows

1. **Positions run between the remote's limits.** Position 0 is closed, at the bottom limit set with the remote, and 100 is open, at the top limit; 50 is halfway between them. The shade reports its position on the same scale.
2. **The final position.** While the shade travels, the card shows the position it started from: the shade sends no position until it stops, and a read returns the old one. When the move ends the shade reports where it stopped, and the card shows it. If that report does not arrive, the quirk reads the position when the shade should have arrived, from about 5 seconds after a short move to about 73 seconds after full travel, and again if the shade has not yet stopped. It reads at most three times, all within 2 minutes (and again after a re-send). If it has not seen the shade stop by then, it logs a warning naming the shade and reads once more 5 minutes later.
3. **Moves made with the remote** show when the shade reports its position at the end of the move. That report has been seen for moves sent from Home Assistant, not yet checked for the remote; if a remote move does not show, refresh the cover to read it:

   ```yaml
   action: homeassistant.update_entity
   target:
     entity_id: cover.office_shade
   ```

   After a restart, a refresh also gives the quirk a position to check the next command against.

Optionally, refresh every shade when Home Assistant starts and every hour. This example has not been run in the test suite or checked on real shades (issue #15); the refresh it calls is tested. Each refresh reads each shade once, and once more if the first read is lost.

```yaml
automation:
  - alias: Refresh SmartWings shades
    triggers:
      - trigger: homeassistant
        event: start
      - trigger: time_pattern
        hours: "/1"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id:
            - cover.office_shade
            - cover.bedroom_shade
```

## Known limitations

Each is listed with its cause. The evidence for the motors' behaviour is in [Part 1](docs/1-the-devices.md).

1. **Stop works; its reply is not a measure of anything.** The shade's radio passes Zigbee Stop on to the motor, and in the tests so far the shade halted and then reported where it stopped (issue #51). After a Stop the quirk sends nothing more to move the shade: no retry, no re-send, and a command issued before the Stop that is still waiting its turn is dropped. If the shade does not report where it halted within 3 seconds, the quirk reads it once. The radio answers each of the commands it handles (open, close, stop and go to lift percentage, `0x00`, `0x01`, `0x02` and `0x05`, and the three in item 4, which the quirk never sends) twice, "done" and then "unsupported" (`UNSUP_CLUSTER_COMMAND`), and Home Assistant keeps whichever arrives first. For open, close, set position and Stop the quirk treats "unsupported" as the radio taking the command, as it does "done", so Home Assistant shows no error; neither says whether the motor moved. Whether the shade moved is judged once it should have arrived (item 2). The quirk never fakes a stop with a move to the last known position: that position is stale while the shade travels, so it would be a new move, not a stop.
2. **A command can be ignored, and that shows only after the travel time.** The motor sometimes ignores the first command after idling; the cause is not known, and how often is being measured again (Part 1 §3e). A read while the shade travels returns the position from before the move, so nothing can tell whether the shade moved until it should have arrived, up to about 73 seconds for full travel. The command therefore returns as soon as the radio accepts it, within about a second (at most 12.5 seconds if its frame is lost and sent again, 25 if another command to the same shade is still being sent), and the card shows opening or closing as for any cover. If the shade has not moved by the time it should have arrived, the quirk sends the command once more. A shade that ignores both shows where it really is, with a warning in the log; Home Assistant shows no error for it after the call has returned. With no recent position to compare with, as for the first command after a restart, only a position at the target counts as arrival, so a move that stops short is sent once more.
3. **The position changes only when a move ends.** The motors send their position when they stop, not during travel, and a read during travel returns the position from before the move (issue #51). So the card shows the starting position until the shade stops. If Home Assistant restarts or ZHA reloads during a move, the card shows the end when the shade reports it, or after the next command or refresh.
4. **Three commands are refused.** ZHA's device panel can send "go to lift value" (`go_to_lift_value`), "go to tilt value" and "go to tilt percentage". The shade's radio garbles all three on the way to the motor, which can repeat the previous command or spoil the next, so the quirk refuses them without sending anything, and ZHA reports them as unsupported (`UNSUP_CLUSTER_COMMAND`). It refuses an open, close or set position sent with a manufacturer code the same way, since the radio rejects every manufacturer-specific command without passing it on; a Stop sent so goes out and the radio's own "unsupported" comes back as an error. The dashboard, voice and automations do not use them; these shades have no tilt.
5. **The limits are set only with the remote.** The motor keeps its top and bottom limits to itself: over Zigbee it reports them as "not set", and nothing in its radio can set them (Part 1 §2b, §3a; [firmware analysis](docs/evidence/firmware-analysis.md) §5, §8). So Home Assistant can neither show nor change where a shade stops; use the remote (Install, step 4).
6. **One shade once stalled partway on Open.** On one day one shade stopped partway up three times on Open, while a move to position 100 reached the top (Part 1 §3b). It has not been seen since, and Open now goes out as the standard open command, as in stock Home Assistant. If a shade stops short on Open, setting its position to 100 opens it; please report it.

## Troubleshooting

1. **Repairs: "SmartWings quirk not loaded".** ZHA loaded another quirk for the shades it names, so their Open and Close commands go out swapped and nothing is re-sent. Check the other SmartWings Repairs issues first: they say what is missing. Otherwise check that `wm25lz.py` is in the folder that `custom_quirks_path` names, that the `zha:` section is in `configuration.yaml`, and that you restarted Home Assistant afterwards. If it is all there, search the log for `Unexpected exception importing custom quirk`. The issue clears itself once the quirk is loaded for every shade.
2. **A shade closes too far, or not far enough.** Its bottom limit is where its remote stops it. Set the limits again with the remote (Install, step 4).
3. **Open closes the shade and Close opens it.** Check that the quirk is loaded (Repairs shows no "SmartWings quirk not loaded"). If it is, the shade's direction may have been reversed when it was set up, which has not been seen on the shades tested so far (Part 1 §3c); please report it.
4. **A command fails with "Failed to close cover" or "Failed to open cover".** The shade's radio did not answer the command, sent twice (only once if you pressed Stop before the second try, which is then never sent). The shade may be out of range or asleep: try again.
5. **The shade did not move, but no error was shown.** The radio accepted the command and the motor ignored it. Once the shade should have arrived, the quirk sends the command once more; if the shade still has not moved, it logs a warning naming the shade and leaves it. Try again. One shade has been seen ignoring repeated identical commands until a small move in the other direction freed it, and in a similar case its remote freed it.
6. **The card shows the starting position while the shade moves.** Expected: the shade sends its position only when it stops, and the card updates then.
7. **The card shows the wrong position after you used the remote.** Refresh the cover (see "What the cover shows").
8. **An old "Stops at" control is still listed on a shade's device page.** It came from an earlier test version of this quirk. It does nothing now; delete it from the device page. Two other leftovers of those test versions are inert and can stay: a stop value stored in ZHA's Zigbee database (cluster 0xFC01), if one was ever set, which nothing reads any more; and a `.storage/smartwings.pending_clears` file, which no release ever shipped and which nothing reads.

## Uninstalling

Remove the integration from Settings → Devices & services. Removing it does not delete the quirk file, which ZHA may still be using. Then delete `wm25lz.py` from the custom quirks folder, remove `custom_quirks_path` from `configuration.yaml` if nothing else uses it, and restart Home Assistant.
