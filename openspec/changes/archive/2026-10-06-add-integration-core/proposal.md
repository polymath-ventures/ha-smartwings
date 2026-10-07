## Why

The "Stops at" setting, capture and clear actions (#12, #13) need a home: a Home Assistant integration that finds every SmartWings WM25/L-Z shade ZHA knows about and can tell, per shade, whether the quirk that enforces the closed limit (U) is the one ZHA actually loaded. Part 2 §3c proves that ZHA resolves every device before a custom integration is imported, so with only the integration installed U is absent after every restart. The old integration noticed this only by recognising a Python class name (Part 3 §1c, REV 7c) and tried to register the quirk itself, which never took effect after a restart. The user must never see a stop that is not in force (Part 3 §2m, F12).

## What Changes

- New custom integration `custom_components/smartwings`. It has a single-instance config entry, a config flow, `strings.json` plus `translations/en.json`, and a manifest declaring `dependencies: ["zha"]`. The HA 2026.10 minimum is recorded in `hacs.json`.
- Shade discovery through ZHA's surfaces. A shade is any ZHA device whose zigpy manufacturer/model is `Smartwings` / `WM25/L-Z`. Discovery runs at entry setup, again whenever ZHA (re)builds its entities, and stops tracking a shade when its device is removed.
- One rule decides "U active for this shade", and it uses only the closed-limit data contract defined by #7 (`closed-limit-contract`). That means endpoint 1 carries the closed-limit cluster `0xFC01` declaring attribute `0x0000` with type `uint8` and manufacturer code `0x1002` (ADR 0001). It never uses a class name, module path or cluster class name.
- A per-shade status that #12 and #13 consume, so the Change-stop dialog and the capture and clear actions refuse a shade without U. The integration creates no per-shade entity: ZHA creates the "Stops at" control only from U, so a shade without U has no control at all, and never one showing a stop that is not in force (ADR 0001).
- One Repairs issue naming every shade without U and the `custom_quirks_path` remedy, the stock Home Assistant way to ask the user to fix their setup (owner decision 2026-10-06: match stock Home Assistant). It is updated as the set changes and deleted when the set is empty or the integration unloads or is removed.
- The integration never imports, registers or bundles the quirk at runtime to work around setup order. It only detects and reports.
- The integration does not read, adopt, migrate or depend on any artifact of the old install: `input_number.smartwings_*_closed_position` helpers, `automation.smartwings_*`, `script.smartwings_*` or `smartwings_calibration.json`. The owner chose a clean uninstall (#15).
- Things the old code did that are dropped: `_handler_already_supplied()` and its class-name walk of the quirk registry; the import-time registration of a bundled quirk; `find_readback_cluster`'s class-name branch and its `ep1` attribute-name probing; and legacy entity-id rewriting.

## Capabilities

### New Capabilities
- `integration-core`: the `smartwings` config entry and its lifecycle, shade discovery through ZHA, the contract-only "U active" decision, the per-shade status other platforms use, and the missing-quirk Repairs issue.

### Modified Capabilities
None. No specs exist yet in `openspec/specs/`.

## Impact

- New code: `custom_components/smartwings/__init__.py`, `config_flow.py`, `const.py`, a `shades.py` directory module, `contract.py` (I's mirror of the #7 contract terms), `manifest.json`, `strings.json`, `translations/en.json`, plus `hacs.json` at the repo root.
- Depends on #7 for the contract terms and on #5 for the real-HA plus real-ZHA test harness. The contract location is settled by ADR 0001 (#6).
- Consumed by #12 (`stops-at-control`) and #13 (`closed-limit-capture`), which refuse shades this capability reports as without U.
- Uses ZHA helper surfaces (`homeassistant.components.zha.helpers.get_zha_gateway_proxy`, `SIGNAL_ADD_ENTITIES`) and the HA device registry's update events. Those ZHA helpers are not a stable public API, so the harness tests pin their behaviour.
- Target: Home Assistant 2026.10, zha 2.3.x, zigpy 2.3.x, zha-quirks 2.3.x.
