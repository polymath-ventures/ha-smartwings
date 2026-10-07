## Why

Each SmartWings WM25/L-Z shade has a per-shade closed limit ("Stops at"), because the motors ignore the stop programmed with their remote whenever a command arrives over Zigbee (docs Part 1 §3a). ADR 0001 (issue #6) decided that the quirk (U) hosts the control: ZHA creates `number.<shade>_stops_at` from U's quirks v2 `number`, and zigpy's database is the only store. That leaves three guarantees ZHA cannot give on its own, which the integration (I) must: a confirmed way to change a stop once set (owner decision, 2026-10-05), no stop outliving the integration (F9), and no stop staying in force where the user can no longer see it (Part 3 §2f). Issue: polymath-ventures/ha-smartwings#12.

## What Changes

- The integration creates **no** number entity. The one "Stops at" control per shade is ZHA's, from U (Part 3 §1c, §3d).
- A **Change stop** dialog in the integration's Configure screen (options flow): pick a shade that has a stop, enter the new value (validated against `CLOSED_LIMIT_MIN..CLOSED_LIMIT_MAX` from #7), confirm "<shade>: <old> → <new>. Change it?". On confirm it writes through zigpy's public `cluster.update_attribute` on cluster `0xFC01`, attribute `0x0000` (U's cluster refuses a direct change of a set stop), then refreshes ZHA's control. Cancel writes nothing.
- On integration removal, every shade's stop is cleared (zigpy `update_attribute(attr, None)`, which also deletes the database row), so no stop outlives the integration (F9).
- The integration watches the entity registry: if ZHA's "Stops at" control for a shade is removed or disabled while a stop is set, the stop is cleared (removed) or a Repairs issue tells the user it is still in force (disabled), so no hidden stop stays active (Part 3 §2f).
- Store operations shared with capture (#13): set-after-confirm, clear, and refresh of ZHA's control (ZHA does not react to a clear, ADR 0001).

## Capabilities

### New Capabilities
- `stops-at-control`: the integration's guarantees around ZHA's quirk-hosted "Stops at" control: exactly one control, the confirmed Change-stop dialog, the shared store operations, clearing on integration removal, and protection against a hidden active stop.

### Modified Capabilities
<!-- none: no existing specs in openspec/specs/ -->

## Impact

- Code: the options flow in `custom_components/smartwings/config_flow.py`; a `store.py` with the set, clear and refresh operations; an entity-registry listener and the `async_remove_entry` sweep in `__init__.py`; translations for the dialog and the Repairs issue.
- Depends on #5 (real-ZHA harness), #7 (contract and U's closed-limit cluster with its `number`), #11 (shade directory, "U active" predicate and `get_contract_cluster`). #13 (capture and clear) uses the same store operations.
- Tests: Part 3 §5b items 3 (restart), 4 (ZHA reload), 6 (clear and removal) and 7 (range), plus F7, F9, F15.
- Deployment: the owner's box has nine legacy `number.smartwings_*` entities from the old integration. The runbook (#15) uninstalls them first. This change carries no migration code for them.
