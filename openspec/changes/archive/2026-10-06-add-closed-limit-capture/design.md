## Context

The motor does not expose its remote-set stop: `installed_closed_limit_lift` reads 65535 (docs Part 1 §2, §7b). The user drives the shade to its stop with the remote, and Home Assistant copies the position. Three facts constrain how:

1. **Under closed-at-stop rescaling (Part 3 §2h, change `add-closed-limit-enforcement`), the cover entity's `current_position` is relative to the existing stop.** So it is not the raw position, and capture must read the motor directly (§2h-1).
2. **Reads are lossy the same way commands are** (Part 1 §3e): the first frame after idle is often lost, and reads that land take 0.8-1.9 s.
3. **One authoritative store** (Part 3 §3e). ADR 0001 (issue #6) settled it: ZHA hosts "Stops at" from the quirk's `LocalDataCluster` (`0xFC01`, attribute `0x0000`), and zigpy's database is the only store. The integration owns no entity. Capture writes through the same change and clear operations as #12's dialog, not a side door; the oldcode direct-write fallback was such a door. ZHA does not react to a clear, so every write is followed by a refresh of its control.

The oldcode capture (`oldcode/custom_components/smartwings/__init__.py`, `capture`) had several problems:
- It used `zha_toolkit.attr_read` when installed and `homeassistant.update_entity` otherwise.
- It slept a fixed 6 s, then read `current_position` from the state machine.
- It wrote either to the number entity or directly to the device.
- It logged success at WARNING.

Its error handling is worth keeping: every abort raises, and success is reported only after a store.

## Goals / Non-Goals

**Goals:**
- Capture from a fresh, raw, stationary live read. Never use the cache or the scaled entity state.
- Fail visibly with the reason on every failure path, and never report success without a store (F8).
- Provide clear, which restores stock behaviour and always works, even with the quirk absent.
- Work with ZHA's quirk-hosted "Stops at" control (ADR 0001).

**Non-Goals:**
- Defining the attribute, range or unset value (`add-closed-limit-contract`, #7, owns these) or the cover's rescaling (`add-closed-limit-enforcement`'s `LiftScale`, #9).
- The "Stops at" control (ZHA's, from the quirk, #7), the Change-stop dialog and removal clean-up (`add-stops-at-control`, #12).
- Rescaling the cover. `add-closed-limit-enforcement` (#9) owns this.
- Moving the shade. Capture never commands movement.

## Decisions

### D1. Both actions target the cover, not the "Stops at" entity
`smartwings.capture_closed_limit` and `smartwings.clear_closed_limit` are domain actions with one required field, `cover`: an entity selector, domain `cover`, integration `zha`.

**Why:**
- The user thinks in shades: "the office shade stops here".
- Capture must start from the cover anyway.
- ZHA hosts "Stops at" through the quirk's v2 `number` (ADR 0001), so the integration cannot attach entity actions to it. Targeting the cover is the option that works.

**Alternative rejected:** an entity action on the "Stops at" number (the oldcode `clear`). The entity is ZHA's, so the integration cannot register one, and it would be asymmetric with capture.

### D2. Read the raw lift with zigpy's uncached raw read, with capture's own bounded retry
The handler resolves the cover to its zigpy device through the integration core (#11) and takes the WindowCovering cluster on endpoint 1. It reads attribute 0x0008 with `Cluster.read_attributes_raw([0x0008])` (zigpy 2.3.0, `zigpy/zcl/__init__.py:1074`). That call sends a Read Attributes frame and returns the records without consulting or rewriting the cache. It also bypasses any quirk override of `read_attributes`, which may rescale for the cover (#9).

A read counts as usable only when the record has status SUCCESS and a value in 0–100. 255 means unknown. Each read uses the same retry policy as `add-verified-delivery` (#8): one retry after the same delay. The integration holds its own copy of that delay; it never imports quirk code (owner rule, 2026-10-05: the integration shares only the stored value and the published contract terms with the quirk).

**Alternatives rejected:**
- `read_attributes(..., allow_cache=False)`: it routes through the quirk's override, which may return the scaled value.
- `homeassistant.update_entity` plus the state machine: that gives the scaled position, after an arbitrary sleep.
- A quirk method that returns the raw value: it couples the integration to quirk Python code (Part 3 §1c).

**Coordination (verified in zha 2.3 and zigpy 2.3 source):** #9 rescales only in `_update_attribute`, the cache-update path. ZHA's cover reads its position only from the cache (`current_cover_position` uses `self._cluster.get(current_position_lift_percentage)`, `zha/application/platforms/cover/__init__.py:333-347`; `async_update` only repopulates the cache via `safe_read`, `:620-631`), while `read_attributes` and `read_attributes_raw` return the undecorated device value to their caller. So the raw lift capture reads is never scaled. A harness test in this change asserts it.

### D3. The shade must be stationary: two equal reads
Capture takes read A, waits a fixed settle interval (`CAPTURE_SETTLE_S`, default 2 s), takes read B, and requires A == B with exact equality. A difference fails with "still moving".

**Why:**
- Full travel is 30–70 s (Part 1 §4), so a moving shade changes several lift points in 2 s.
- A shade that is still coasting from the remote must not have its momentary position stored.
- One read cannot tell those cases apart.

**Exact equality:** if a stationary motor jitters, the user retries. That costs less than storing a wrong stop. If harness or hardware evidence shows jitter, a tolerance of 1 can be introduced as a design change.

**Alternative rejected:** a single read (oldcode). It accepts a mid-travel position.

### D4. Write through #12's store operations
The handler calls `async_change_closed_limit(shade, raw_value)` from `add-stops-at-control` (#12), which writes with zigpy's public `cluster.update_attribute` on cluster `0xFC01`, attribute `0x0000`, then `async_refresh_control(shade)`. That deliberately bypasses the quirk's refusal to change a set stop, but only after capture's own gate: over an existing stop it runs only with `replace_existing: true` (D9), which is capture's confirmation. If the store raises, capture fails (F8). There is no read-back: the store is a local attribute write (owner decision, 2026-10-05). Clear calls `async_clear_closed_limit(shade)` (`update_attribute(attr, None)`, which deletes the database row) and then refreshes the control.

There is no fallback writer. If the store path is unavailable, capture fails, because a second writer is a second store (§3e).

**Concurrent writers (review of PR #31, 2026-10-06).** The store holds one write lock per shade, taken by every change and clear, so the dialog, capture, clear, the removal sweep and owed clears never interleave. Capture records the stop it saw at its gate and passes it as `expected`: under the lock the store refuses if the stop changed during the reads (compare-and-set). Every change, capture's and the dialog's alike, is refused by the store when ZHA's "Stops at" control is missing from the entity registry (checked under the lock, before writing): if it was removed during capture's reads, the store refuses, because a write would put a stop in force that nothing shows and would cancel the clear owed for the removal (§2f, F9). A disabled control does not refuse: #12's watch keeps a stop behind a disabled control and raises a Repairs issue naming it, which the write's signal updates.

Every write is also refused under the lock once the integration's entry is neither loaded nor setting up (unloaded or removed during a writer's wait), except the removal sweep's own clears, so a capture cannot put back a stop the removal just cleared. An owed clear that compare-and-set refuses because the stop is no longer the one owed drops its debt at DEBUG, as a discovery would; only a failed write keeps the debt and logs an ERROR.

**The one failure after which the stop has changed** is the store's refresh check: the write landed but ZHA's control does not show it. The store's standard error says the closed limit is stored; capture and clear let it through unchanged.

### D4a. Registration
Both actions are registered in `async_setup` (with `CONFIG_SCHEMA = cv.config_entry_only_config_schema`), as Home Assistant's action-setup rule asks, so they exist even while the entry is not loaded; they then fail with a `ServiceValidationError`. The handlers find the shade through the loaded entry's `ShadeDirectory`.

### D5. Report by action response only
- **Response:** the action declares `SupportsResponse.OPTIONAL` and returns `{"entity_id": ..., "closed_limit": <int>}`. Scripts can use the value.
- **No notification** (owner decision, 2026-10-06): stock Home Assistant actions report through their response data, and ZHA's "Stops at" control shows the stored value at once. A persistent notification with hard-coded text would be invented UI that strings.json cannot translate.

**Why:** §2c's "tells the user the stored value" is met by the response (shown when the action is run from the Actions UI or a script) and by the "Stops at" control on the shade's device page.
**Logging:** success logs at INFO. Normal operation does not log at WARNING (§3c spirit).

### D6. Order of checks, all failing closed
1. Resolve the cover.
2. Check it is a WM25/L-Z under ZHA (device registry plus gateway).
3. Check the quirk is active (#11's contract check).
4. If a stop is already set and `replace_existing` is not true, refuse before any read (D9).
5. Read A, wait, read B.
6. Check stationary.
7. Convert raw lift to raw HA position with the plain ZCL→HA inversion, `100 − raw lift` (D8).
8. Check the range against #7's contract terms.
9. Store, then refresh ZHA's control.
10. Notify.

Each step's exception is wrapped as a `HomeAssistantError` naming the shade. Nothing writes before step 9 (F8). Guards fail closed (F13, a review-checklist item).

Clear runs steps 1–3 and 9 only. When ZHA is down or the quirk is not loaded the shade has no closed-limit cluster to clear, and #12's merged `async_clear_closed_limit` refuses then; clear fails with the same named reasons as capture (amended 2026-10-06 to the merged store).

An unexpected exception inside a check is not caught and relabelled (owner rule: no catch-all handler); it fails the action as it is, before any read or store. Failures that concern the request (no such cover, not a WM25/L-Z cover, a stop already set) raise `ServiceValidationError`, a `HomeAssistantError`; the rest raise `HomeAssistantError`.

### D7. A per-shade lock prevents concurrent capture or clear
A per-IEEE `asyncio.Lock` held for the whole handler prevents two captures, or a capture and a clear, from interleaving: an action issued while another runs for the same shade waits for it. Its write then also takes the store's per-shade write lock (D4), always in that order, so the two locks cannot deadlock.

This lock is separate from the quirk's per-shade command lock. Capture never holds both, so it cannot deadlock (F2).

### D8. Conversion is the plain ZCL→HA inversion, not `LiftScale`
Capture reads the motor's raw lift and stores raw HA cover position, so the only conversion is the
standard axis flip both ZCL and Home Assistant define: `stored = 100 − raw lift` (ZCL 0 = open,
HA 0 = closed; Part 1 §3g). That rule comes from the protocol, not from the quirk, so it is not
duplicated quirk logic. Capture does not use, import or mirror #9's `LiftScale`: rescaling applies
to what the cover displays and never to the stored raw value. One function in the integration
holds the flip, with a test (lift 84 → 16).

### D9. Capture over an existing stop requires `replace_existing` (owner decision, 2026-10-05)
Changing an existing stop must be deliberate (see `add-stops-at-control` D8). Capture therefore
has an optional boolean field `replace_existing` (default false). When the shade already has a
stop and the field is not true, capture reads nothing and fails: "<shade> already stops at <old>.
To replace it, run capture with replace_existing: true, or use Configure → Change stop." With the
field true, capture proceeds and returns the new value; the INFO log records old and new.

### D10. Failure messages say what to do
- Unreadable: "Could not read <shade>'s position. It may be asleep; try again. If it stays
  unresponsive, move it with its remote and try again."
- Still moving: "<shade> is still moving. Wait until it stops, then capture again."
These follow the delivery failure guidance (#8) and Part 1 §3h.

## Risks / Trade-offs

- **The settle interval adds 2 s plus read latency (about 4–8 s typical) to a capture.** Mitigation: capture is a rare, one-off action. The worst case is bounded: 2 reads × (1 + 1 retry) × the read timeout, plus the settle interval, plus the retry delays. The bound is documented in the action description and asserted in a test.
- **`read_attributes_raw` bypasses a quirk's read retry.** Mitigation: capture applies #8's retry constants itself.
- **A stationary but drifting motor estimate** (Part 1 §7f): capture records what the motor believes. #9 applies the stop-short margin, not capture.
- **Exact-equality stationarity may reject a jittering motor.** Mitigation: the failure tells the user to retry. A tolerance is a later, evidence-based change.
- **Dependence on four sibling changes.** Mitigation: tasks are ordered so capture is implemented last, against real interfaces, and each dependency is named in tasks.md.

## Migration Plan

The oldcode service `smartwings.capture_closed_position`, with its `cover_entity` field, is not carried forward. The deploy runbook (#15) removes the old install, including `script.smartwings_capture_closed_position`, before the new integration is installed. No data migration is needed: the owner re-captures, or re-types, Office Shade's 14.

## Open Questions

- **Settle interval default (2 s).** Confirm on the Office Shade during acceptance (#15) that two reads 2 s apart agree on a stationary shade.
- **Whether `read_attributes_raw` behaves identically for a sleepy end device under bellows on the box.** Confirm in acceptance, since the harness radio stub cannot show this.
