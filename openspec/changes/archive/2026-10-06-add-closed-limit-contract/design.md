## Context

The quirk (U) changes behaviour per shade, but a quirk is library code that ZHA imports with no handle on Home Assistant (docs Part 2 §3a; ARCH:40-47). The only per-device store it can read is the zigpy device object, whose attribute cache zigpy persists in its own database. The integration (I) provides the UI. Part 3 §1c makes the boundary a data contract and forbids I from naming U's classes.

ADR 0001 (issue #6) settled the location with evidence from `tests/spikes/test_quirks_v2_spike.py`, run on real HA 2026.10.0b0 and ZHA 2.3.0:
- A quirks v2 `LocalDataCluster` attribute exposed with `QuirkBuilder.number` gives ZHA's own "Stops at" control on the shade's device; writes send no frame; a replaced WindowCovering cluster can read the value; the v2 quirk wins over the released v1 vendor quirk.
- The value survives restart and ZHA reload **only** with `manufacturer_code=0x1002` on the attribute definition. Without it zigpy reloads the row into its legacy cache and the control comes back `unknown` (negative control).
- A live read of an unset value is recorded as unsupported **unless** the attribute is in `_VALID_ATTRIBUTES`.
- `cluster.update_attribute(attr, None)` clears the value and deletes the row, but ZHA keeps showing the old value until the entity is refreshed.
- The cluster can refuse a write that changes a set value; ZHA surfaces `Failed to write attribute closed_limit=…: READ_ONLY`.

## Goals / Non-Goals

**Goals:**
- One authoritative store per shade: zigpy's attribute cache and database row (Part 3 §3e). There is no Home Assistant copy.
- Contract terms stated once, in U, and unable to drift from I's copy.
- Local-only access by construction (F10).
- Fail-closed reads and validated writes (F7, F13, F15).
- A presence test I can use without names (F12 groundwork).

**Non-Goals:**
- Enforcement, margin and rescaling: `add-closed-limit-enforcement`.
- The Change-stop dialog, removal clean-up and registry watching: `add-stops-at-control`.
- Capture and clear actions: `add-closed-limit-capture`.

## Decisions

### D1. Location: a `LocalDataCluster` at `0xFC01` (ADR 0001)
Attribute `0x0000`, `uint8`, read/write, `manufacturer_code=0x1002`, on a zhaquirks `LocalDataCluster` subclass with `cluster_id = 0xFC01`, added to endpoint 1 (server side) with `QuirkBuilder.adds`. `0xFC01` is in the manufacturer-specific range and exists only in the quirk; the motor never sees it. *Alternatives rejected (ADR 0001):* a v1 manufacturer attribute on the replacement WindowCovering cluster, which needs hand-written interception of every attribute I/O path to stay off the air; an I-hosted entity with Home Assistant restore state, which makes two stores to reconcile.

### D2. Range: `CLOSED_LIMIT_MIN = 0`, `CLOSED_LIMIT_MAX = 95`
- 0 is valid: a stop at the mechanical bottom is a legitimate choice, and enforcement's margin still keeps it clear of the hard end.
- 95 is the ceiling. `add-closed-limit-enforcement` rescales positions over `100 − stop`; a ceiling of 95 keeps that span at least 5 points, so it never divides by zero and a "close" can never mean "fully open". It matches the bound already validated on the owner's box (oldcode `CLOSED_LIMIT_SANITY_MAX`, R1 2b).

The same constants feed `QuirkBuilder.number(min_value=…, max_value=…)`, so the control and the quirk share one range (F7).

### D3. Unset = absent, never a sentinel
"Unset" is the absence of a cache entry, which zigpy's clear path persists by deleting the row. *Alternative rejected:* the ZCL `uint8` non-value 0xFF, a magic number on every read path that a bug could write by mistake. Absent-means-unset also makes F15 structural: a never-configured shade has no row.

### D4. Local-only I/O comes from `LocalDataCluster`
zhaquirks' `LocalDataCluster` serves reads from its cache, keeps writes local, and no-ops bind and reporting configuration (`zhaquirks/__init__.py:85-177`). Listing `0x0000` in `_VALID_ATTRIBUTES` makes an unset read answer "no value" rather than `UNSUPPORTED_ATTRIBUTE`, so zigpy never marks the setting unsupported (F10). `LocalDataCluster` does not cover zigpy's other send paths (structured reads and writes, discovery, commands and replies), so the cluster also overrides `request` and `reply` as the single boundary: a request gets the Default Response a device sends for an unsupported command, and a reply is dropped. Tests prove it, through the #5 harness, for ZHA's panel-style forced read with `allow_cache=False`.

### D5. Write rules live in the cluster's `write_attributes` and `write_attributes_raw`
Both overrides apply the same rules to each attribute, as a device applies ZCL Write Attributes, and store locally:
1. Not an integer in range → `INVALID_VALUE`, nothing stored (F7).
2. A valid stop is set and the new value differs → `READ_ONLY`, nothing changed (confirm-before-change; I changes a set stop through the dialog, which clears and re-writes through zigpy's `update_attribute`). An invalid cached value reads as unset and may be replaced.
3. Any other attribute (raw path) → `UNSUPPORTED_ATTRIBUTE`; with ids, names or definitions, an unknown key raises `KeyError`, as in zigpy.
4. Otherwise store it.

The reply lists a status record for each refused attribute, or a single `SUCCESS` record.

Clearing is not a `write_attributes` call; it is zigpy's public `update_attribute(attr, None)`. *Alternative rejected:* a magic "clear" value through `write_attributes`, which would reintroduce a sentinel.

### D6. Presence test is structural
`has_closed_limit_contract(zigpy_device) -> bool`: endpoint 1 has an in-cluster with id `0xFC01` whose attribute definitions include id `0x0000` with type `uint8` and `manufacturer_code` `0x1002`. Matching is by ids and definition, never by class name, module path or Python attribute name. Missing or malformed structure (no endpoints mapping, no endpoint 1, no cluster, no definitions, a definition that is not a `ZCLAttributeDef`) yields `False`; anything unexpected propagates, since a catch-all handler is not allowed (owner rule). Neither outcome answers "present" (F13).

### D7. The contract terms are a protocol; I keeps its own copy
I keeps a small `contract.py` with the published terms. That is data, not code coupling: I never imports or calls U's code (owner rule, 2026-10-05). Upstream maintainers will refactor U's Python freely, but zigpy's database stores every value under the endpoint, cluster and attribute ids and the manufacturer code, so those effectively cannot change; the type is a contract term for decoding the value. While both live in this repository, a test loads U's contract module from the source tree and compares every term with I's copy.

### What to port from `oldcode/` and what to drop
- **Port** (re-derived under the new tests): the cache-first read; the range check that returns unset and logs ERROR.
- **Drop:** the v1 attribute on the WindowCovering cluster and every interception it needed; the multi-key cache probing; the stale-unsupported-mark removal (the new cluster is never marked); `find_readback_cluster`'s class-name branch and `_handler_already_supplied()`; the "calibration file" comments; the duplicated range constants; WARNING-level logs on normal paths (§3c).

## Risks / Trade-offs

- [The `manufacturer_code` or `_VALID_ATTRIBUTES` line is lost in a refactor] → Both failures are silent in production. The restart round-trip and the unset-read tests guard them, and the presence test checks the manufacturer code.
- [Upstream asks for a different cluster id] → The id is a contract term; I's copy and the equality test change together, and no deployed box holds a `0xFC01` row today.
- [zigpy changes its cache or clear semantics in a later 2.x] → The persistence scenarios run against the pinned zigpy in CI, so an upgrade that breaks them fails loudly.
- [A direct edit of a set stop shows ZHA's generic `READ_ONLY` message] → Accepted in ADR 0001; the dialog and the docs explain how to change a stop.

## Migration Plan

Nothing on the owner's box uses this contract yet. v18's stop lived in attribute `0xFC01` of the WindowCovering cluster, which this contract does not read. The deploy runbook (#15) reads each shade's current stop before the uninstall and re-enters it through the new control; it must not assume the value carries over. Rollback is the uninstall described in #15.
