## Why

The WM25/L-Z ignores, over Zigbee, the closed limit stored with its 433 MHz remote and reports `installed_closed_limit_lift` as 65535 (docs Part 1 §3a, §7b). Home Assistant therefore has to supply each shade's stop itself. The quirk (U) and the integration (I) must agree on exactly one per-device setting without importing each other (Part 3 §1c); the previous attempt coupled the two by class name (REV 7c) and could be disabled by zigpy's "unsupported" mark (REV 2d). ADR 0001 (`docs/decisions/0001-quirk-v2-hosts-stops-at.md`, issue #6) settled where the setting lives and proved the mechanics on real HA and real ZHA. Every later change (#8–#13) builds on this contract, so it comes first.

## What Changes

- Make U a quirks v2 quirk (`zhaquirks.builder.QuirkBuilder`) that adds the closed-limit cluster: a zhaquirks `LocalDataCluster`, cluster id `0xFC01`, server side, endpoint 1, holding attribute `0x0000` (`uint8`, read/write, `manufacturer_code=0x1002`, listed in `_VALID_ATTRIBUTES`).
- Expose it with `QuirkBuilder.number` (range `CLOSED_LIMIT_MIN` = 0 to `CLOSED_LIMIT_MAX` = 95, step 1, unit `%`, translation key `closed_limit`, fallback name "Stops at"), so ZHA creates the one "Stops at" control on the shade's own device (`number.<shade>_stops_at`).
- Define the contract terms once, in U: location, type, coordinate space (raw HA cover position), range, unset representation (absent from the attribute cache) and local-only access.
- Add a fail-closed read accessor for U's own use: cache only, no radio, no disk on the event loop, no Home Assistant imports. An out-of-range or wrong-type value reads as unset and logs one ERROR (F7, F13).
- Validate writes in the cluster: out of range or wrong type → `INVALID_VALUE`, nothing stored (F7); a write that changes an already-set value → `READ_ONLY`, nothing changed (owner's confirm-before-change rule, ADR 0001 decision 4). Clearing is zigpy's public `update_attribute(attr, None)`, which also deletes the database row.
- Guarantee that nothing in U creates a value: no default, no restore, no fallback (F15).
- Provide a structural presence test (by cluster and attribute id, type and manufacturer code) for I to use instead of class or module names (§1c, F12 groundwork).
- Publish the contract terms as a protocol. I keeps its own copy, never imports or calls U's code (owner rule, 2026-10-05), and an equality test keeps the copies identical while both live in this repository.

## Capabilities

### New Capabilities
- `closed-limit-contract`: the per-shade closed-limit setting shared by U and I: its location, type, coordinate space, range, unset value, local-only access, persistence, write rules and presence detection.

### Modified Capabilities
<!-- none: openspec/specs/ is empty -->

## Impact

- **U (`quirk/zhaquirks/smartwings/wm25lz.py`):** becomes a v2 quirk with the closed-limit `LocalDataCluster` and its `number` metadata; contract constants; tests in upstream style.
- **I (`custom_components/smartwings`):** gains a contract-constants module, an import scan and an equality test; uses the presence test in `add-integration-core` and writes through zigpy's public cluster API in `add-stops-at-control` and `add-closed-limit-capture`.
- **Downstream changes:** `add-closed-limit-enforcement` replaces the WindowCovering cluster in the same v2 quirk, reads the value from the sibling `0xFC01` cluster, and owns all rescaling.
- **Dependencies:** zigpy 2.3.x attribute cache and `appdb` persistence; zhaquirks 2.3.x `LocalDataCluster` and `QuirkBuilder`. No new third-party packages.
- **Blocked by:** #2 (environment), #6 (decided: ADR 0001). The real-ZHA tests use the #5 harness.
