## 1. Prerequisites

- [x] 1.1 Confirm #2 (environment, layout, CI), #5 (real HA + real ZHA harness with a simulated WM25/L-Z) and #7 (closed-limit contract terms) are merged. Read ADR 0001 (`docs/decisions/0001-quirk-v2-hosts-stops-at.md`) for the contract location.
- [x] 1.2 Check out this branch rebased on main. Confirm `pytest` and `ruff check` pass on the untouched skeleton.

## 2. Manifest, config entry and translations (test first)

- [x] 2.1 Write failing tests. The config flow creates one entry with no input. A second attempt aborts with Home Assistant's `single_instance_allowed`. With no ZHA entry, it aborts `zha_not_configured`. `translations/en.json` equals `strings.json`.
- [x] 2.2 Implement `manifest.json` (D6), `const.py`, `config_flow.py`, `strings.json`, `translations/en.json`, and `hacs.json` with the approved beta `homeassistant: "2026.10.0b0"` (bump with the Home Assistant pin on release). Make 2.1 pass.
- [x] 2.3 Write a failing test that entry setup raises `ConfigEntryNotReady` when ZHA's gateway is unavailable, then implement it.

## 3. Contract mirror (test first)

- [x] 3.1 Write a failing test that imports U's source from this repo and asserts each mirrored term in `custom_components/smartwings/contract.py` equals U's. Terms: endpoint, cluster `0xFC01`, attribute ID `0x0000`, type, manufacturer code `0x1002`, coordinate space, `CLOSED_LIMIT_MIN`, `CLOSED_LIMIT_MAX`, unset representation.
- [x] 3.2 Implement `contract.py` and make 3.1 pass. Mutate one term locally and confirm the test fails, so it cannot pass vacuously (F14).
- [x] 3.3 Write a test that setting up the integration imports no U module and no `zhaquirks` quirk module, and leaves `zhaquirks.legacy.PENDING_LEGACY_QUIRKS` and ZHA's quirk registry unchanged.

## 4. The "U active" decision (test first, real zigpy clusters)

- [x] 4.1 Write failing unit tests for `quirk_active(zigpy_device)` against real zigpy devices built from the WM25/L-Z signature:
  - the released vendor quirk gives False;
  - U gives True;
  - a cluster class named `ReadbackWindowCoveringCluster` without the contract attribute gives False;
  - the contract ID, type and flag declared under another Python name gives True;
  - attribute `0x0000` on `0xFC01` with the wrong type or without manufacturer code `0x1002` gives False;
  - with the unsupported mark set on the attribute, it still gives True;
  - missing or malformed device structure gives False without raising;
  - an unexpected exception from an endpoint, cluster or attribute-definition lookup propagates (no catch-all, as `closed-limit-contract` requires).
- [x] 4.2 Implement `quirk_active` per D1 in one adapter module and make 4.1 pass.

## 5. Shade directory and discovery (harness tests)

- [x] 5.1 Write failing harness tests:
  - with one WM25/L-Z and one other device, exactly one shade is tracked, linked to ZHA's existing device entry and `cover.*` entity id, and no new device appears in the registry;
  - a shade joining after setup is tracked after `SIGNAL_ADD_ENTITIES`;
  - a removed shade is dropped.
- [x] 5.2 Implement `ShadeDirectory` (D3) using `get_zha_gateway_proxy`, `SIGNAL_ADD_ENTITIES` and `EVENT_DEVICE_REGISTRY_UPDATED`, holding no zigpy cluster references. Add `get_contract_cluster(hass, ieee)` for #12 and #13.
- [x] 5.3 Write failing harness tests for status fan-out (D4). A status signal fires when `u_active` changes. While ZHA is reloading, status is gateway-unavailable and the Repairs issue is untouched. After the reload completes, status is recomputed from the rebuilt devices.
- [x] 5.4 Implement the status signal and the gateway-unavailable handling, and make 5.3 pass.

## 6. Missing-quirk Repairs issue (harness tests)

- [x] 6.1 Write the Part 3 §5b item 1 setup-order tests against real HA and real ZHA.
  - With only the integration installed, restart: one Repairs issue names the shade and the `custom_quirks_path` remedy, and the status is not active.
  - With U in `custom_quirks_path`, restart: no Repairs issue, and the status is active.
- [x] 6.2 Write failing tests for the set lifecycle: the set shrinks (two shades become one), the set empties (dismissed), an unchanged set means no re-create and no extra WARNING, and unload dismisses.
- [x] 6.3 Implement the Repairs issue per D5 and make 6.1 and 6.2 pass.

## 7. Unload, reload and old-install independence

- [x] 7.1 Write failing tests:
  - after unload, a later `SIGNAL_ADD_ENTITIES` triggers no discovery and the ZHA cover is unaffected;
  - reloading the entry leaves exactly one set of listeners and at most one Repairs issue.
- [x] 7.2 Implement teardown via `entry.async_on_unload` and make 7.1 pass.
- [x] 7.3 Write a test that seeds the old install's artifacts: `input_number.smartwings_office_closed_position` and a `smartwings_calibration.json` in the config dir. Assert identical discovery, status and Repairs issue behaviour, and that neither artifact is read or modified.

## 8. Port review and finish

- [x] 8.1 Compare against `oldcode/custom_components/smartwings/__init__.py` and `number.py`. Port only what the tests above need. Confirm none of the D7 drop list exists in the new code (grep for `SmartWingsWM25LZCover`, `ReadbackWindowCoveringCluster`, `PENDING_LEGACY_QUIRKS` writes, `_LEGACY_ENTITY_ID_RE`).
- [x] 8.2 `ruff check` and the full `pytest` suite pass locally and in CI. Every log and Repairs issue string uses the protocol terms (closed limit, quirk) and the "Stops at" label (Part 3 §3h).
- [x] 8.3 Update #11 with the final "U active" rule and any deviation from this design.
