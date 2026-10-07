## Why

The closed-limit feature rests on Part 1 §3a: "the closed limit set with the remote is not honoured over Zigbee". Live on 2026-10-06, with the owner watching, that premise failed (#54). On the Office Shade, `go_to_lift_percentage(100)` (sent twice) and a raw `down_close` both stopped at the lower limit programmed with the remote, and the shade reported that position as lift 100. On the guest blackout, Home Assistant's own close stopped at the remote limit too. The motor scales positions between the limits set with its remote and enforces them for Zigbee commands. The fix for a shade that closes too far is to program its limits with the remote, as SmartWings' guide says, not to keep a second limit in Home Assistant. The owner decided to retire the feature, provided Home Assistant's Open, Close, Stop and position slider work on the shade cards.

## What Changes

- **BREAKING: "Stops at" is gone.** The quirk no longer adds the local-only cluster 0xFC01 or ZHA's `number.<shade>_stops_at`. It does no closed-limit enforcement, no lift scaling and no closed band, and it no longer turns an open into a go-to. The integration loses the capture and clear actions, the Change-stop options dialog, and the stored-stop machinery: the store, pending clears, the registry watch and its `stops_at_disabled` Repairs issue.
- **Commands go out as ZHA sends them.** Open is `up_open`, close is `down_close`, and a position is `go_to_lift_percentage` with ZHA's lift, unscaled. The vendor quirk's up/down swap stays unused: raw `down_close` lowers these units and raw `up_open` raised the Office Shade (#34, #51). The motor stops each at its remote-set limit.
- **Stop works, so its second reply is not an error.** Stop is still passed through once and never synthesised. The motor halts on it (#51), and the firmware's spurious 0x81 to a standard Stop is now reported as SUCCESS, the same as for movements. `cover.stop_cover` no longer raises.
- **Kept unchanged:** the double-reply tolerance for movements; refusal of 0x04, 0x07, 0x08 and of manufacturer-specific movements; #51's delivery and readback (send once, end-of-travel report, single re-send); battery doubling; the integration's config flow, quirk installer and its Repairs issues.
- **"Quirk not loaded" no longer reads 0xFC01.** The quirk declares a quirk ID through ZHA's exposed-features mechanism. The integration reads it on the ZHA device to decide whether U is active, and on ZHA's quirk registry to decide whether zha-quirks ships U.
- **Docs.** The README gets a setup step, "Set your shade's limits with its remote", linking SmartWings' guide, and Known limitations and Troubleshooting are updated. Part 1 §3a is reversed, with its history kept. Part 3's closed-limit requirements are retired. ADR 0001 is superseded. The test plan retires the stop and capture tests and adds HA-card acceptance: Open, Close, Stop and the slider on every shade.
- Closes #52 (capture stillness) as moot.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `closed-limit-contract`: every requirement removed (the 0xFC01 contract).
- `closed-limit-enforcement`: every requirement removed. The parts that survive move to `command-delivery`: commands as ZHA sends them, Stop never synthesised, one v2 quirk with the vendor battery reading.
- `closed-limit-capture`: every requirement removed (the capture and clear actions).
- `stops-at-control`: every requirement removed (the control, the dialog, the store and its watch).
- `command-delivery`: adds "commands go out as ZHA sends them", "Stop is passed through once and its second reply is not an error", and "U is one v2 quirk with a quirk ID and the vendor battery reading". It drops the closed-limit clauses from the re-send and refusal requirements.
- `position-readback`: readings reach the cache unconverted. ZHA's `100 - lift` is the only conversion.
- `integration-core`: U's activity is decided by its quirk ID on the ZHA device, not by the 0xFC01 contract. Discovery keeps no cover entity id. No per-shade status signal. The missing-quirk Repairs issue says what the shade loses without U.
- `bundled-quirk-install`: "zha-quirks provides U" is decided by the quirk ID on a registry entry, not by a declared 0xFC01 cluster.

## Impact

- `quirk/zhaquirks/smartwings/wm25lz.py` and its bundled copy.
- `custom_components/smartwings/`: `contract.py`, `store.py`, `services.py`, `services.yaml`, `icons.json`, `pending_clears.py` and `stops_at_watch.py` are deleted. `__init__.py`, `config_flow.py`, `shades.py`, `zha_gateway.py`, `installer.py`, `repairs_missing.py`, `const.py` and the strings change.
- Tests: the stop, capture, contract, dialog, store, watch and spike tests are deleted, and the quirk tests lose their closed-limit sections. The real HA+ZHA cover tests cover Open, Close, Stop and the slider end to end, including no error on Stop's double reply. `MotorSim` documents that remote-set limits are honoured: lift 100 is the lower limit.
- Migration: nothing to migrate. No shade on the owner's box has a stored stop: `zigbee.db` holds no 0xFC01 row (Part 1 §3c, #34). A stop stored by a test install stays in zigpy's database as an inert row that nothing reads.
- `README.md`, `docs/1-the-devices.md`, `docs/3-what-must-be-built.md`, `docs/decisions/0001-quirk-v2-hosts-stops-at.md`, `docs/test-plan.md`, `agent-instructions/source/00-product.md`, `openspec/config.yaml`. `docs/README.md`, Part 2 §3a and the letter (Part 4) carry notes that point to the reversal.
