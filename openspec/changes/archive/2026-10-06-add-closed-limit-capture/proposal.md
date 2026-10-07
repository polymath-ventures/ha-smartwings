## Why

The WM25/L-Z holds a closed limit set with its 433 MHz remote, but reports `installed_closed_limit_lift` as 65535 ("not set") over Zigbee and ignores the stored stop for Zigbee commands (docs Part 1 §2, §3a, §7b). The only way Home Assistant can learn the stop is to read the motor's position while the shade sits where the remote left it. Part 3 §2c and §2d require a one-step capture and a clear, and F8 forbids reporting success without a store. The previous capture (oldcode) read the cover entity's state after a fixed sleep and depended on an optional third-party integration; under the closed-at-stop rescaling (Part 3 §2h, issue #9) that state is no longer the raw position, so capture has to be rebuilt.

## What Changes

- New action `smartwings.capture_closed_limit`, targeting one SmartWings cover. It takes two fresh live reads of the motor's raw lift percentage (never the cache, never the cover entity's scaled `current_position`), requires them to agree, converts the reading to raw HA cover-position space with the plain ZCL→HA inversion (stored = 100 − raw lift), validates it against the contract range, writes it through the shared change operation from #12 (zigpy's `cluster.update_attribute` on the closed-limit cluster `0xFC01`, attribute `0x0000`), refreshes ZHA's "Stops at" control, and reports the stored value in its action response, as stock actions do (no persistent notification; owner decision, 2026-10-06). Over an existing stop it refuses unless called with `replace_existing: true` (owner decision, 2026-10-05).
- New action `smartwings.clear_closed_limit`, targeting one SmartWings cover. It clears the stop through #12's clear operation (`update_attribute(attr, None)`, which also deletes the database row) and refreshes ZHA's control, so the shade behaves as if none had ever been set. It sends nothing to the motor. There is no integration entity to write through: ZHA hosts "Stops at" from the quirk (ADR 0001).
- Every failure path raises `HomeAssistantError` naming the shade and the reason, and stores nothing, with one exception from the shared store: if the write landed but ZHA's "Stops at" control did not follow, the error says the closed limit is stored. The failure paths are: no such cover, not a WM25/L-Z under ZHA, ZHA not running, quirk not active, a stop already set without `replace_existing`, position unreadable, shade still moving, value out of range, the stop changed by another writer or the control removed during the reads, the integration unloaded or removed during the capture, store failed. Unreadable and still-moving errors tell the user what to do (wait for it to stop; if it is unresponsive, move it with its remote and try again).
- `services.yaml`, `strings.json` and `translations/en.json` describe both actions in protocol vocabulary ("closed limit"), with the human label "Stops at" (Part 3 §3h).
- Dropped from oldcode: the `zha_toolkit.attr_read` dependency, the `update_entity` fallback, the fixed 6 s sleep, reading `current_position` from the state machine, the direct-write fallback that bypasses the store, and WARNING-level logging of normal success.

## Capabilities

### New Capabilities
- `closed-limit-capture`: capturing a shade's closed limit from a fresh raw position read and clearing it, with visible failure and no store on any failure (Part 3 §2c, §2d, F8, §5b item 5).

### Modified Capabilities
<!-- None: no specs exist yet in openspec/specs/. -->

## Impact

- Code: `custom_components/smartwings/` (action registration and handlers, `services.yaml`, `strings.json`, `translations/en.json`).
- Depends on the other changes:
  - `add-closed-limit-contract` (#7): range constants and the unset value.
  - `add-verified-delivery` (#8): the read-retry policy, mirrored as the integration's own constants (no import of quirk code).
  - `add-closed-limit-enforcement` (#9): the guarantee that read return values stay raw. Capture does not use or mirror `LiftScale`; rescaling is irrelevant to the raw value.
  - `add-integration-core` (#11): shade lookup and the "quirk active" check.
  - `add-stops-at-control` (#12): the shared change, clear and refresh operations.
- Tests: the real-HA plus real-ZHA harness from #5. Every failure path is a test (Part 3 §5b item 5).
- Radio traffic: two attribute reads per capture (more only on read retry). No commands. Clear sends nothing.
