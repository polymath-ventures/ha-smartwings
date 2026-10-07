## Context

Part 2 §3c traced, and Part 3 §5b item 1 must prove, the setup-order chain. ZHA's entry setup runs `zhaquirks.setup()`, which drains `PENDING_LEGACY_QUIRKS` into ZHA's registry, and then resolves every device from zigpy's database. Only after that is a custom integration that depends on `zha` imported. So nothing the integration does at import or setup time changes the quirk a shade was built with until ZHA itself sets up again. A re-interview does not apply a late-imported quirk either.

The old integration (`oldcode/custom_components/smartwings`) had three problems:
1. It imported a bundled copy of the quirk at module load, guarded by `_handler_already_supplied()`, which walked `DEVICE_REGISTRY.registry_v1` looking for the class name `SmartWingsWM25LZCover`.
2. It found the quirk's cluster by class name `ReadbackWindowCoveringCluster`, by `AttributeDefs.closed_limit`, or by probing `ep1` attribute names.
3. It rewrote entity ids it considered legacy.

The first two couple the integration to U's Python names, which Part 3 §1c forbids (REV 7c). The bundled import never applied after a restart.

Verified facts for HA 2026.10:
- A device belongs to one config entry. An entity is placed on ZHA's shade device by setting `entity.device_entry`, not `DeviceInfo(identifiers=...)`, which silently creates a duplicate device.
- `DeviceEntry.config_entries` is deprecated; use `config_entry_id`.
- `EntityRegistry.entities` is a UserDict, so iterate `.values()`.
- zha library `Device` objects have no `device_id`.
- ZHA exposes `get_zha_gateway_proxy(hass)`, whose `device_proxies` map EUI64 to `ZHADeviceProxy` (each carrying `device` and `device_id`), and it fires `SIGNAL_ADD_ENTITIES` ("zha_add_entities") after (re)building entities.

## Goals / Non-Goals

**Goals:**
- A minimal, correct integration skeleton that #12 and #13 build their entities and actions on.
- A "U active" decision that depends only on the #7 data contract and fails closed.
- A visible, per-shade warning whenever U is absent, correct regardless of setup order.

**Non-Goals:**
- The "Stops at" entity itself, range validation, restore, clearing on removal (#12).
- Capture and clear actions (#13).
- Any attempt to make U load: no runtime import, registration or bundling of the quirk. Packaging U for `custom_quirks_path` is #14.
- Migrating or cleaning up the old install (#15 runbook).

## Decisions

### D1. Detect U by declared contract attribute, matched by ID, type and manufacturer code
`quirk_active(zigpy_device) -> bool` looks up the in-cluster with id `0xFC01` on endpoint 1 (ADR 0001). It then searches the cluster's `attributes` mapping, keyed by attribute ID, for `0x0000`, and requires the definition's type to be `uint8` and its manufacturer code to be `0x1002`, as in the mirrored contract.
- Matching by ID, not by the `AttributeDefs` member name, means an upstream rename of the Python attribute cannot break detection (REV 7c).
- Reading the declaration, not the cached value, means zigpy's unsupported mark (F10) or an unset stop cannot flip the result.
- Missing or malformed device structure returns `False`. An unexpected exception propagates rather than being caught by a catch-all handler, as `closed-limit-contract` requires; no failure yields `True` (F13).

*Alternatives:*
- Class-name or registry inspection (the old approach) is forbidden by §1c.
- Probing the cached value cannot tell "U absent" from "stop unset".
- Importing U's module and using `isinstance` breaks whenever U arrives through `custom_quirks_path` under an arbitrary module name, or through upstream zhaquirks.

### D2. Mirror the contract terms; enforce equality by test
I cannot import U at runtime, since U may be loaded from `custom_quirks_path`, zhaquirks, or not at all. `custom_components/smartwings/contract.py` holds the terms as constants. A repository test imports U's source in this repo and asserts every term is equal. This is the "duplicates with a test asserting equality" option #7 allows.

### D3. A shade directory, re-resolved on every discovery
`shades.py` holds a `ShadeDirectory` keyed by lowercase IEEE. Each record has the IEEE, ZHA's `device_id` (the HA device registry id), the device name, the `cover` entity id from the entity registry, and `u_active`. The directory stores no zigpy cluster objects. Consumers resolve the cluster when they need it, through a `get_contract_cluster(hass, ieee)` helper that re-reads `get_zha_gateway_proxy(hass)`. ZHA reload replaces zigpy device objects, and the old code's stale references were a source of silent failure.

Discovery runs at setup and on every `SIGNAL_ADD_ENTITIES`. Removal is driven by the device registry's `EVENT_DEVICE_REGISTRY_UPDATED` with `action == "remove"`, which is a stable HA core event, rather than ZHA's internal gateway events.

### D4. Status fan-out via a dispatcher signal per entry
When a shade's `u_active` changes, or the gateway becomes (un)available, the directory sends `f"{DOMAIN}_status_{entry_id}"` with the IEEE. #12 and #13 subscribe: the Change-stop dialog lists only shades with U, and the capture and clear actions refuse a shade without it. The integration owns no per-shade entity; ZHA creates the "Stops at" control only from U, so a shade without U simply has none (ADR 0001). While `get_zha_gateway_proxy` raises (ZHA unloaded or reloading), every record is marked gateway-unavailable. The Repairs issue is not changed then, so a reload cannot flash a false "quirk missing".

### D5. One Repairs issue, fixed id, change-driven
Owner decision 2026-10-06: match stock Home Assistant, whose mechanism for "fix your setup" is a Repairs issue. Issue id and translation key: `quirk_not_loaded`, `is_fixable=False`, severity ERROR (Home Assistant's WARNING is for something that will break later; here the stop is not in force now), not persistent. Its text is in `strings.json` under `issues`, with the shade list as the `shades` placeholder; it names the shades and the `custom_quirks_path` remedy. Unlike the old text, it does not suggest a ZHA reload, because without a runtime import a reload only helps when U is already on disk in `custom_quirks_path`. The integration keeps the last reported set in memory, creates or updates only when the set or its text changes (a rename included), logs one WARNING per change, and deletes the issue on an empty set, on unload and on removal. Every completed discovery, including one that finds no shade, reconciles the issue, so the first one also deletes the inactive record Home Assistant keeps of an issue from before a restart, and a shade removed while ZHA was down leaves nothing behind.

### D6. Manifest and entry
`manifest.json`: `domain: smartwings`, `dependencies: ["zha"]`, `config_flow: true`, `single_config_entry: true`, `integration_type: "hub"`, `iot_class: "local_polling"` (capture performs a live read through ZHA), `requirements: []`, and a version. `hacs.json` records the approved beta `homeassistant: "2026.10.0b0"`, bumped with the Home Assistant pin on release. The config flow has one confirm step and aborts with `zha_not_configured`; Home Assistant itself aborts a second flow with `single_instance_allowed` (`single_config_entry`). An existing `smartwings` entry left by the old install is loaded as-is (same domain, no data). Nothing in it is migrated.

### D7. Port selectively from oldcode
Worth porting after its tests pass:
- The discovery loop shape.
- The set comparison and clear-on-empty lifecycle, now for a Repairs issue.
- `ConfigEntryNotReady` when the gateway is absent.

Drop:
- `_handler_already_supplied()`.
- The module-level `from .quirks import smartwings_wm25lz`.
- The class-name and `ep1` branches of `find_readback_cluster`.
- `_LEGACY_ENTITY_ID_RE` and `reconcile_entity_id`, which belong to #12 if anywhere, and F11 forbids renaming user ids.
- The getattr chains guessing at zha/zigpy object shapes, replaced by the typed 2026.10 surfaces.
- Comments narrating the review history.

## Risks / Trade-offs

- **[ZHA helper surfaces are not a public API]**: `get_zha_gateway_proxy`, `device_proxies` and `SIGNAL_ADD_ENTITIES` may change. → Isolate them in one adapter module, and pin their behaviour with real-ZHA harness tests (#5) so an HA upgrade fails CI rather than the user's shades.
- **[False "missing" during startup races]** → The decision is evaluated only when the gateway is available. The Repairs issue is never touched while it is not.
- **[A user leaves the old install in place]** → No behaviour depends on it. The #15 runbook removes it.
- **[A third-party quirk declares the same attribute ID and type]** → It is only consulted for `Smartwings`/`WM25/L-Z` devices, where the ID is reserved by our contract. The residual risk is accepted.

## Migration Plan

There is no data migration. Deploy is per the #15 runbook: remove the old install, upgrade HA to 2026.10, install U in `custom_quirks_path` and the integration, then restart. Rollback is removing the integration, which by this capability changes no ZHA state.

## Open Questions

- `integration_type` "hub" vs "service": hassfest accepts both. Revisit if HA quality-scale review prefers "service" for an integration that owns no devices.
