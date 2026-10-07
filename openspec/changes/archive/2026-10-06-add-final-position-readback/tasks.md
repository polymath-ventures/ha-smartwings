## 1. Prerequisites and harness support

- [x] 1.1 Confirm `add-verified-delivery` (#8) has landed and exposes the read helper with retry, the per-shade lock, and a point where a movement command's delivery finishes. The hooks are `_on_movement_finished(target_lift, budget)` (called by `_deliver` after the lock is released, also on `DeliveryError`) and `_cancel_tracking()` (called by `command()` before the lock); confirm #8 shipped them as specified.
- [x] 1.2 Confirm `add-closed-limit-enforcement` (#9) has landed and owns the single raw↔rescaled conversion applied on attribute updates.
- [x] 1.3 Extend the #5 simulated motor if missing: configurable travel rate, a stall at a given lift (Part 1 §3b), a late start (Part 1 §3h), a move with no Zigbee command (remote), drop-the-next-N-reads, and a read counter. Each extension gets its own test.

## 2. Failing unit tests (real cluster class, zigpy request path, simulated motor, virtual time)

- [x] 2.1 Settle on target: a go-to lift 60 tracker ends after the first reading of 60 and sends no further reads.
- [x] 2.2 Settle on stationarity: with no closed limit set, a stall at 45 ends after two equal readings; the cached lift is 45.
- [x] 2.3 A moving shade keeps being tracked (30, 42, 55 → still tracking).
- [x] 2.4 F17: a delivery verification read of 20 early in a 60 s close is not the final cached value; the final value is 100.
- [x] 2.5 The tracker starts after a failed delivery and observes a late start.
- [x] 2.6 Sparse schedule: a full close's first read is at `FULL_TRAVEL_S + ARRIVAL_MARGIN_S`; a 10-point move's first read is at about 10 s; never before `TRACK_MIN_FIRST_READ_S`; at most `TRACK_MAX_READINGS` readings; ends by `TRACK_MAX_DURATION`.
- [x] 2.7 Unreadable: failed readings end tracking after `TRACK_MAX_READINGS`; one WARNING with the IEEE; exactly one deferred re-read at 300 s if budget remains.
- [x] 2.7a Radio budget: tracking read attempts (including retries and the deferred re-read) never exceed `TRACKING_MAX_OPS` or the command's remaining budget; a spent budget schedules nothing.
- [x] 2.8 A dropped read followed by a successful retry counts as one successful reading.
- [x] 2.9 The deferred re-read updates the cache; a later movement command cancels a pending deferred re-read.
- [x] 2.10 Supersede: a new movement command cancels tracking and is sent without waiting for it; a new tracker follows.
- [x] 2.11 The lock is never held by the tracker: assert the lock is free while tracking runs.
- [x] 2.12 Stop (rejected with UNSUP_CLUSTER_COMMAND) does not cancel tracking.
- [x] 2.13 Two shades: tracking on A does not delay B's command beyond B's worst-case duration (§3g).
- [x] 2.14 F1: the tracker never writes the cache or converts spaces. Assert cache updates come only from the read path, and with a closed limit set the cached value is the rescaled one produced by #9.
- [x] 2.15 Normal tracking logs nothing above DEBUG.
- [x] 2.16 Cancellation and shutdown leave no lingering tasks or timers and no unretrieved exceptions.

## 3. Implementation

- [x] 3.1 Add the tracker constants (`FULL_TRAVEL_S`, `ARRIVAL_MARGIN_S`, `TRACK_MIN_FIRST_READ_S`, `CONFIRM_GAP_S`, `TRACK_MAX_READINGS`, `TRACK_MAX_DURATION`, `DEFERRED_REREAD_DELAY`) to U's cluster module with one-line reasons.
- [x] 3.2 Implement the per-shade tracker task (D1, D2, D4, D7) using the shared live-read helper; the minimum code to pass section 2.
- [x] 3.3 Override #8's no-op hooks: `_on_movement_finished(target_lift, budget)` starts the tracker with the command's budget; `_cancel_tracking()` cancels the tracker task and the deferred re-read handle (D1, D5). #8 already omits both for Stop and other pass-through commands; add a test that Stop leaves tracking running.
- [x] 3.4 Before porting anything from `oldcode/`, check it against section 2. Do not port `async_initialize` reads or `_read_position_now` (they never fired; WARNING in normal operation).

## 4. Real HA + real ZHA harness tests (#5)

- [x] 4.1 `cover.close_cover` from HA position 100 with no limit: after simulated travel the `cover.*` state is `closed`, `current_position` 0, with no manual refresh (§2i, §5b item 2).
- [x] 4.2 With "Stops at" 14: after `cover.close_cover` the state is `closed`, `current_position` 0 (§2h via #9).
- [x] 4.3 `cover.set_cover_position(40)`: the final state is open at 40 after the arrival read. A stale mid-travel display before then is the accepted cosmetic cost (design D3); assert only the final state.
- [x] 4.4 Remote move: the motor moves with no command; `homeassistant.update_entity` updates `current_position`.
- [x] 4.5 Idle hour: no frames are sent with no command and no refresh.
- [x] 4.6 Full HA restart, then `homeassistant.update_entity`: the position is correct (§5b item 3).
- [x] 4.7 ZHA reload during tracking: the old tracker ends within its bounds and the new cluster works.

## 5. Finish

- [x] 5.1 `ruff check` and the full test suite pass in CI. *CI green on PR #28.*
- [x] 5.2 Hand #14 the README facts: tracking bounds, the brief stale mid-travel display, the refresh automation example (HA start plus hourly `homeassistant.update_entity` on every SmartWings cover) once #15 verifies it, and the D3 traffic numbers.
- [x] 5.3 Add to #15's acceptance checklist: on the Office Shade, a commanded close shows the correct position at 5 minutes with no manual refresh (§5c item 5), with tracking read counts from DEBUG logs; and a remote-driven move is corrected by `homeassistant.update_entity` (DH:194-197 says this once failed on some shades).

Posted 2026-10-06: #14 issuecomment-6010194079 (5.2), #15 issuecomment-6010194254 (5.3). 5.1 is checked by CI on the PR; locally `ruff check`, `ruff format --check` and the full suite pass.
