## Why

These motors never push a position report (docs Part 1 §3f), so the only position Home Assistant
ever sees is one somebody read. Today the only reads happen during delivery verification, in the
first few seconds of a 30–70 s travel (Part 2 §3e-iv). When ZHA's transition timer expires, the
cover shows that early mid-travel value as the final position, which breaks Part 3 §2i ("the
displayed position is the real position") and is failure mode F17. GitHub issue #10.

## What Changes

- U (the SmartWings quirk) tracks every movement command to the end of travel. After delivery
  verification finishes, a per-shade background tracker reads the live position until the shade
  is stationary or at its target, so the last value in zigpy's attribute cache, and therefore on
  the `cover.*` entity, is where the shade actually stopped.
- Tracking is sparse and bounded: one read at the estimated arrival time, one confirming read,
  at most `TRACK_MAX_READINGS` readings, a maximum duration, and one deferred re-read when the end
  could not be observed. All reads count against `command-delivery`'s per-command radio budget.
- Tracking never holds the per-shade command lock from `add-verified-delivery`. A new movement
  command on the same shade cancels tracking before it is sent. Stop, which the device rejects,
  does not cancel tracking.
- Tracking never converts or writes positions itself. Values reach the cache only through the
  cluster's normal read path, which applies the single conversion owned by
  `add-closed-limit-enforcement` (F1).
- Positions changed by the 433 MHz remote are corrected by an on-demand refresh
  (`homeassistant.update_entity` on the cover), whose reads use the read retry from
  `add-verified-delivery`. U does no periodic polling. The README (issue #14) documents an
  example refresh automation.

## Capabilities

### New Capabilities

- `position-readback`: end-of-travel tracking after every movement command, its settle
  criterion and bounds, its interaction with command serialisation and cancellation, and
  on-demand refresh for moves made by the remote.

### Modified Capabilities

None. `command-delivery` and `closed-limit-enforcement` are introduced by sibling changes;
this change consumes their interfaces without changing their requirements.

## Impact

- Code: U's WindowCovering cluster module (the tracker and its constants). No change to I.
- Depends on: `add-verified-delivery` (#8): `_read_lift_live()` with read retry, the per-shade
  lock, the per-command radio budget, and the hooks `_on_movement_finished(target_lift, budget)` and `_cancel_tracking()`. `add-closed-limit-enforcement` (#9): the single HA↔ZCL conversion and rescaling (`LiftScale`).
  Test harness #5: real HA and real ZHA, a simulated motor with a configurable travel rate,
  remote-driven moves, and virtual time.
- Radio traffic: about two tracking reads per command, at most `TRACKING_MAX_OPS` (8). The card
  may briefly show a stale mid-travel position before the arrival read (accepted).
- Docs: #14 documents the refresh automation and the tracking bounds.
