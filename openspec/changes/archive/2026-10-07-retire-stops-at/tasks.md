## 1. Failing tests first

- [x] 1.1 Real HA+ZHA cover tests (`tests/test_cover_entity.py`, replacing `test_closed_limit_enforcement_entity.py`): `open_cover` sends raw `up_open` and ends open; `close_cover` sends raw `down_close` and ends closed at lift 100; `set_cover_position` 0, 50 and 100 send go-to 100, 50 and 0; `stop_cover` during travel raises nothing under the double reply (both orders and 0x81 alone), sends one Stop and the cover shows where the shade halted; the v2 quirk wins, declares `smartwings.wm25lz` in ZHA's `exposes_features`, adds no cluster or `number` entity, and keeps the battery doubling.
- [x] 1.2 Quirk tests: opens and closes pass through unswapped; a go-to's lift is sent unchanged; a standard Stop's 0x81 is SUCCESS in both orders and alone; a manufacturer-specific Stop's 0x81 is unchanged; a lift is cached as sent.
- [x] 1.3 Integration tests: U active iff ZHA's device lists the quirk ID (vendor quirk: not active; U: active; a variant without the ID: not active; renamed classes: active); upstream detection by quirk ID; the quirk-ID mirror test.
- [x] 1.4 Harness: `MotorSim` honours the remote's limits (`down_close` and go-to 100 stop at lift 100, `up_open` at 0).
- [x] 1.5 Run them against the current code and record which fail: 39 failed (17 quirk tests: open, close and Stop frames and replies, the quirk ID, no added cluster; 7 real-ZHA cover tests: Open as `up_open`, Stop with no error, the quirk ID, the controls after a cycle; 2 Stop tests in the delivery entity file; 13 integration tests: quirk-ID detection, the missing-quirk text, no options flow, no actions, quirk loaded after install), and `test_zha_quirk_sources.py` failed to import `zha_quirks_provide_quirk`.

## 2. The quirk

- [x] 2.1 Remove `LiftScale`, `ClosedLimitCluster`, the number entity, the closed-limit constants and helpers, the rescale on change and the re-send's closed-limit guard.
- [x] 2.2 `_translate()`: commands as ZHA sends them (D1).
- [x] 2.3 Stop: map a standard Stop's 0x81 to SUCCESS (D2).
- [x] 2.4 `.exposes_feature(QUIRK_ID)`; module docstring rewritten; bundled copy regenerated, byte-identical.

## 3. The integration

- [x] 3.1 Delete `contract.py`, `store.py`, `services.py`, `services.yaml`, `icons.json`, `pending_clears.py`, `stops_at_watch.py`; drop the options flow, `async_setup`, the remove-entry stop clearing, `ShadeStatus`, the status signal and the cover entity id.
- [x] 3.2 `const.QUIRK_ID`; `shades.py` decides U by `exposes_features`; `zha_gateway.zha_quirks_provide_quirk()` by the registry entry's quirk ID; the missing-quirk issue says the Open and Close commands go out swapped without U.
- [x] 3.3 Strings: drop the stop strings; rewrite the config-flow description, `quirk_not_loaded`, `custom_quirks_path_missing` and `restart_required` texts; `translations/en.json` equal to `strings.json`.

## 4. Tests removed

- [x] 4.1 Delete the stop, capture, clear, contract, dialog, store, watch, lifecycle, removal, actions-metadata and v2-spike tests; remove the closed-limit sections from `tests/quirk/test_smartwings.py` and the helpers.

## 5. Docs

- [x] 5.1 README: setup step "Set your shade's limits with its remote" (SmartWings' guide), What it does, What the cover shows, Known limitations, Troubleshooting, Uninstalling.
- [x] 5.2 Part 1 §3a reversed with its history kept; §3b, §3c, §3d, §5 and §6 follow.
- [x] 5.3 Part 3: the closed-limit requirements retired; §1, §2, §3a, §4, §5 follow. ADR 0001 superseded. `agent-instructions/source/00-product.md`.
- [x] 5.4 Test plan: stop and capture tests retired; HA-card acceptance (Open, Close, Stop, slider on every shade) added; `STOP-WHILE-MOVING` consequence recorded; the `up_open` stall count revived.

## 6. Verify

- [x] 6.1 `ruff check`, `ruff format --check`, the full suite twice, `openspec validate retire-stops-at --strict`.
- [x] 6.2 Archive so the REMOVED deltas land in the archive. OpenSpec rebuilds every spec a delta names and refuses one left with no requirements (`Spec must have at least one requirement`; with the canonical folder deleted first it treats the REMOVED-only delta as a new, empty spec and refuses it the same way), so the four retired capabilities cannot go through its spec update. Procedure, run from the repository root with `R="closed-limit-capture closed-limit-contract closed-limit-enforcement stops-at-control"`:
  1. Move the four REMOVED-only delta folders aside: `mkdir /tmp/hold && for c in $R; do mv openspec/changes/retire-stops-at/specs/$c /tmp/hold/; done`.
  2. `openspec archive retire-stops-at --yes`: it applies the other four deltas (bundled-quirk-install, command-delivery, integration-core, position-readback: + 6, ~ 8, - 4) and moves the change to `openspec/changes/archive/<date>-retire-stops-at/`.
  3. Put the four deltas back into the archived change, so its requirement-level record (every removed requirement with its Reason and Migration) is kept: `for c in $R; do mv /tmp/hold/$c openspec/changes/archive/<date>-retire-stops-at/specs/; done`.
  4. Delete the four canonical folders by hand: `for c in $R; do git rm -r openspec/specs/$c; done`.
  5. `openspec validate --all --strict`.

  This is safe because each of the four deltas removes every requirement of its capability and nothing else, and no other delta in the change touches those capabilities: deleting the canonical folder is exactly the result OpenSpec would produce if it allowed an empty spec. No flag is needed (`--skip-specs` would also skip the four surviving deltas). Checked on a scratch copy of the branch rebased on main: the archive holds all eight deltas (8, 10, 11 and 11 removed requirements in the four retired ones), `openspec/specs/` holds the four surviving capabilities, and `validate --all --strict` passes.