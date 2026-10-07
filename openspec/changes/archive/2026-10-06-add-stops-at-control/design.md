## Context

ADR 0001 (issue #6) settled the host. U is a quirks v2 quirk whose `LocalDataCluster` (`0xFC01`, attribute `0x0000`, `uint8`, `manufacturer_code=0x1002`) holds the stop, and `QuirkBuilder.number` makes ZHA create the "Stops at" control on the shade's device as `number.<shade>_stops_at`. zigpy's database is the only store, restored before ZHA builds entities, so a stop is in force before the first command after a restart or ZHA reload with no help from Home Assistant (proven in `tests/spikes/test_quirks_v2_spike.py`).

The spike also proved what ZHA does not do:
- It does not react to zigpy's clear event: after `update_attribute(attr, None)` the control keeps showing the old value until the entity is refreshed (`homeassistant.update_entity`).
- It cannot ask for confirmation. U's cluster therefore refuses a write that changes a set stop, and ZHA shows the generic `Failed to write attribute closed_limit=…: READ_ONLY`.
- It does not clear the stop when its entity is removed or disabled.

This change specifies the integration's side of those gaps. The contract is #7's; missing-quirk detection and the shade directory are #11's.

## Goals / Non-Goals

**Goals:**
- Exactly one "Stops at" control per shade, ZHA's.
- A confirmed way to change a set stop.
- No stop outliving the integration, and no stop in force where the user cannot see it.
- Store operations that capture (#13) reuses, so there is one write path.

**Non-Goals:**
- The control itself, its range and its persistence: U and ZHA (#7).
- The capture and clear *actions* (#13).
- Missing-quirk detection and its notification (#11).
- Migrating the old integration's entities: the runbook (#15) uninstalls them.

## Decisions

### D1. The integration hosts nothing; ZHA's control is the view, zigpy is the store
There is no integration `number` platform, no restore state, no reconciliation and no read-back. The stored value is raw HA cover position (percent of full travel; owner accepted, ADR 0001 decision 3), shown as such by ZHA's control while the cover slider is rescaled by #9. *Alternative rejected (ADR 0001):* an integration-hosted `RestoreNumber`, which adds a second store that can disagree with the device.

### D2. Store operations, by cluster and attribute id, through zigpy's public API
`store.py` provides three operations that resolve the live closed-limit cluster through #11's `get_contract_cluster(hass, ieee)` each time (never cached across a ZHA reload) and touch it only through zigpy's public cluster API, never quirk code (Part 3 §1c):
- `async_change_closed_limit(shade, raw_value)`: validates against #7's range, then `cluster.update_attribute(0x0000 by definition, raw_value)`, which bypasses U's refusal on purpose because the caller has already confirmed. Raises `HomeAssistantError` naming the shade if the cluster is missing or the call raises.
- `async_clear_closed_limit(shade)`: `cluster.update_attribute(attr, None)`, which removes the value and deletes the database row.
- `async_refresh_control(shade)`: calls `homeassistant.update_entity` on the shade's ZHA "Stops at" entity, found in the entity registry by device, ZHA's `number` platform and the translation key U publishes (`closed_limit`); the unique-id suffix is U's Python attribute name, which the contract does not publish, so the display follows a clear or a change.

Every write is followed by a refresh, and the refresh checks that the control's state shows the stored value, because `homeassistant.update_entity` swallows an entity's update failure. ZHA follows a set by itself; only a clear depends on the refresh. Capture (#13) uses the same three.

### D3. Change-stop dialog (owner decision, 2026-10-05)
A stop is set once, usually by capture, and changing it by accident moves where every close ends. The options flow has three steps: choose a shade (only shades with U active and a stop set), enter a value (number selector bounded by `CLOSED_LIMIT_MIN..MAX`, step 1), confirm "<shade>: <old> → <new>. Change it?". Confirm calls `async_change_closed_limit`; cancel or abort writes nothing. A first set needs no dialog: ZHA's control accepts it directly, because U refuses only changes to a set value. Clearing is the separate clear action (#13).

### D4. Clear every shade on integration removal (F9)
`async_remove_entry` clears the stop on every tracked shade with U active, then refreshes each control. A shade whose quirk is not U at removal time has no closed-limit cluster, so there is nothing to clear and nothing in force; a row left by an earlier U would revive only if U is reinstalled (accepted gap). With ZHA not running nothing can be cleared: Home Assistant cannot refuse or defer a removal and there is no device to clear, so one WARNING names every registered shade. This is a documented limit of F9, alongside the U-removed gap.

### D5. No hidden active stop
The integration listens for entity-registry updates on each shade's ZHA "Stops at" entity:
- **Removed** while a stop is set → clear the stop (D2), because the control that showed it is gone. If it cannot be cleared now (ZHA down, U not active, write failed), the owed clear is saved by IEEE in the integration's own `helpers.storage` Store and applied at the next discovery that reaches the shade; each debt records the stop it is owed for (unknown when ZHA was down, which is safe because nothing can write the stop until the discovery that applies the debt); a write through the integration cancels it, and a different stored value drops it. It is also dropped after a confirmed clear, when nothing is stored, when the shade leaves ZHA, or on integration removal; saves are serialised, and removal itself waits for every save in flight before deleting the store (Home Assistant's unload gives up on an entry's tasks after 10 s), so none lands after the store is deleted.
- **Disabled** while a stop is set → keep the stop (disabling is reversible and the user may want enforcement) and raise a Repairs issue per shade (stock Home Assistant, like #11's `quirk_not_loaded`): "<shade> still stops at <value>", saying how to see, change or clear it. Deleted when the entity is re-enabled or the stop is cleared, and on unload.

*Alternative rejected:* clearing on disable. A user hiding a control from a dashboard would silently lose a safety stop.

### D6. Entity id is ZHA's
Home Assistant derives the id from the name, giving `number.<shade>_stops_at` (ADR 0001, revising Part 3 §2b). The integration never renames it; a user's rename is the registry's and survives restart (F11).

### Port notes from `oldcode/.../number.py`
- **Keep:** the integration-removal sweep and the "fail visibly unless stored" pattern.
- **Drop:** the whole `number` platform; `RestoreNumber` re-apply; `_LEGACY_ENTITY_ID_RE` and `reconcile_entity_id`; `find_readback_cluster` by class name; the `hass.data` entity maps; hand-maintained range constants; broad `except Exception` turning errors into `False` (F13).

## Risks / Trade-offs

- **[ZHA stops recording the quirk's translation key on the registry entry in a zha upgrade]** → The refresh and registry listener find the entity by device plus the published translation key, pinned by a harness test so an upgrade fails CI.
- **[`update_attribute` bypasses U's write rules]** → Only after the dialog's own range check and confirmation; tests prove an out-of-range value never reaches it.
- **[A direct edit of a set stop shows ZHA's generic READ_ONLY error]** → Accepted in ADR 0001; translations and the README point to Configure → Change stop.
- **[Raw-space display may confuse users who expect slider space]** → Owner accepted; README (#14) explains "percent of full travel".

## Migration Plan

No in-place migration. Runbook #15 removes the old integration, its nine `number.smartwings_*` entities, the `input_number` helpers and `smartwings_calibration.json`, then installs the new code and re-enters each stop (Office Shade: 14) through ZHA's control or capture. Rollback: remove the integration, which clears stops per D4.
