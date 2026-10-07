## 0. Preconditions

- [x] 0.1 Read ADR 0001 (`docs/decisions/0001-quirk-v2-hosts-stops-at.md`) and the spike tests it cites; they are the reference for every mechanism below.
- [x] 0.2 Confirm the #2 environment imports zigpy and zhaquirks 2.3.x and the #5 harness boots with a quirk in `custom_quirks_path`.

## 1. Contract module (U)

- [x] 1.1 Write failing tests asserting every contract constant: endpoint 1, cluster `0xFC01`, attribute `0x0000`, `uint8`, manufacturer code `0x1002`, space name "raw HA cover position", `CLOSED_LIMIT_MIN == 0`, `CLOSED_LIMIT_MAX == 95`, unset semantics.
- [x] 1.2 Add the contract constants to U (`quirk/zhaquirks/smartwings/wm25lz.py`, upstream layout) and make 1.1 pass.
- [ ] 1.3 Add a repo-wide test that fails if a literal closed-limit bound (for example `95`) appears outside the contract modules (F7). *Dropped in review of PR #24 (1d): the scan was broader than the contract; the range is covered by runtime tests.*

## 2. The v2 quirk and the closed-limit cluster (U)

- [x] 2.1 Failing harness tests: with U in `custom_quirks_path`, ZHA creates one `number` on the shade's device named "Stops at", entity id `number.<shade>_stops_at`, min 0, max 95, state `unknown`.
- [x] 2.2 Implement the `LocalDataCluster` subclass (`cluster_id = 0xFC01`, attribute `0x0000` `uint8` rw `manufacturer_code=0x1002`, `_VALID_ATTRIBUTES = {0x0000}`) and the `QuirkBuilder(...).adds(...).number(...)` registration. Use `zhaquirks.builder` and `zhaquirks.clusters` imports, not the deprecated `zigpy.quirks` paths.
- [x] 2.3 Harness test: set 14, fully restart; the control shows 14 and the accessor returns 14 before any cover command. Repeat for a ZHA reload.
- [x] 2.4 Negative control: the same cluster without `manufacturer_code` loses the value on restart (guards the silent failure ADR 0001 found).

## 3. Read accessor (U)

- [x] 3.1 Failing tests: absent → unset with no frame; 14 → 14 with no frame; 96 / 255 / non-int → unset plus exactly one ERROR naming the IEEE; an exception inside the check never yields a value (F13).
- [x] 3.2 Implement the accessor using the attribute definition only (no bare-id cache keys). Port oldcode's cache-first read; drop its multi-key probing and mark clearing.
- [x] 3.3 Assert with a socket- and file-access guard in the test that the accessor performs no I/O and imports nothing from `homeassistant` (§3b). *Narrowed in review of PR #24 (1e): the guard covers file, socket and SQLite access on the calling thread; no Home Assistant import is covered by `test_quirk_imports_without_home_assistant`.*

## 4. Write rules and clear (U)

- [x] 4.1 Failing tests through `number.set_value`: first set stores and persists; same value again is accepted; a different value on a set stop fails visibly with `READ_ONLY` and changes nothing; 96 / -1 / non-int return `INVALID_VALUE` and store nothing; none sends a frame.
- [x] 4.2 Override `write_attributes` on the closed-limit cluster to apply the rules, then defer to `LocalDataCluster`.
- [x] 4.3 Failing harness test: `update_attribute(attr, None)` clears the stop; after `homeassistant.update_entity` the control shows `unknown`; after a restart it is still unset and the database row is gone.

## 5. Local-only I/O (U)

- [x] 5.1 Harness tests: a forced read (`allow_cache=False`) of a set and of an unset stop sends no frame, succeeds, and leaves the attribute not marked unsupported (F10). Prove the unset case fails without `_VALID_ATTRIBUTES`.
- [x] 5.2 Harness test: reporting configuration and bind on the closed-limit cluster send no frame.

## 6. No value nobody set (U)

- [x] 6.1 Harness test: pair a WM25/L-Z with U and restart three times with no write. The accessor returns unset each time, and zigpy's `attributes_cache` table has no row for the contract attribute (F15, §2e).
- [ ] 6.2 Grep-style test: the only writers of the contract attribute in U are `write_attributes` and the clear path. *Dropped in review of PR #24 (1d): the source scan was broader than the contract; F15 is covered by the runtime test in 6.1.*

## 7. Presence test and I's copy

- [x] 7.1 Failing tests: the presence test is false for a device built with the released `zhaquirks.smartwings.wm25lz` quirk, true with U, still true after renaming U's classes, and false for a `0xFC01` attribute without manufacturer code `0x1002` (§1c, REV 7c).
- [x] 7.2 Implement `has_closed_limit_contract(zigpy_device)` in the contract module.
- [x] 7.3 Add `custom_components/smartwings/contract.py` carrying I's copy of the constants and the presence test.
- [x] 7.4 Add the import-scan test: no module under `custom_components/smartwings` imports U's quirk file or `zhaquirks.smartwings`.
- [x] 7.5 Add the equality test that loads U's contract module from the source tree and compares every term with I's copy. Prove it fails when one constant is changed.

## 8. Wrap-up

- [x] 8.1 Run ruff with upstream zha-device-handlers rules on U, and confirm no WARNING-level logs on normal paths (§3c).
- [x] 8.2 Update the issue #7 checklist. *Issue #7 had acceptance bullets, no checkboxes; closed by PR #24.*
