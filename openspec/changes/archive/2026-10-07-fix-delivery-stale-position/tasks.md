## 1. Harness

- [x] 1.1 `MotorSim.radio_cache` (default on): reads answer the lift last sent by the motor, which changes only when travel ends or on Stop; `report_interval_s` adds positions during travel.
- [x] 1.2 Failing first: under the copy alone (reports and Stop halting off), 38 tests failed against the old quirk: quirk tests `test_movement_after_the_first_frame_means_no_resend`, `test_no_movement_means_a_resend_that_lands`, `test_movement_away_from_the_target_is_not_success`, `test_every_frame_raising_with_movement_is_success`, `test_a_late_start_in_the_final_grace_look_is_success`, `test_a_stuck_shade_does_not_delay_another`, `test_delivery_never_waits_on_its_own_lock`, `test_two_commands_on_one_shade_are_serialised`, `test_a_raising_hook_does_not_change_the_result`, `test_the_baseline_comes_only_from_cached_lift_raw[override-gives-baseline]`, `test_a_lost_first_frame_through_the_cluster_is_resent`, `test_normal_operation_logs_nothing_at_warning`, `test_every_open_is_go_to_zero_without_a_stop` (2), `test_the_look_that_proves_travel_updates_the_cache`, `test_a_lift_read_after_readback_gave_up_in_travel_is_no_baseline`, `test_a_never_stationary_shade_is_abandoned_within_the_bounds`, `test_tracking_one_shade_does_not_delay_another`, `test_a_verified_movement_ignores_the_second_reply` (6); real-ZHA `test_a_movement_succeeds_whichever_reply_wins` (6) and seven position-readback entity tests; and the integration's `test_a_moving_shade_is_refused`. With reports and Stop halting on, `test_a_still_shade_near_its_target_ends_quietly_but_is_no_baseline` failed too (39).
- [x] 1.3 `MotorSim.reports` (default on): the radio stub pushes a Report Attributes of the lift when the motor sends it; `stop_halts` (default on); `ignore_next`. Harness tests for each.

## 2. Delivery

- [x] 2.1 Tests: one frame and no read before the command returns; a lost frame sent once more; both lost fail with FAILURE and are never re-sent; one path with or without a baseline.
- [x] 2.2 `_deliver_holding_lock()` sends through `_send_movement()` and hands the readback a re-send only after SUCCESS; the verified and blind paths, `COMMAND_DEADLINE`, `MAX_FRAMES`, `SETTLE`, `LOOK_GAP`, `FINAL_GRACE` and `BLIND_GAP` removed; `T_EXEC`, `DELIVERY_MAX_OPS` and the budget re-derived.

## 3. Readback

- [x] 3.1 Tests: the end-of-travel report ends tracking with no read; reads during travel decide nothing; an ignored first frame is re-sent once after the travel time, with or without reports; a slow shade gets one harmless re-send; a stuck shade is re-sent once and warned about; Stop and a changed closed limit drop the re-send; the tolerance boundaries.
- [x] 3.2 `_track()` waits for a report (`_reported_lift()`), reads at the arrival estimate without one, re-sends once on the first lift that shows no travel, and starts again with renewed bounds.

## 4. Specs and docs

- [x] 4.1 Delta specs for `command-delivery`, `position-readback` and `closed-limit-enforcement`; `openspec validate --strict`.
- [x] 4.2 Part 1 §3c-§3f, §4, §5, §7, §8; Part 3 §2j, §2k, §3g, F5, F6, §5a; README; test plan (`POS-DURING-TRAVEL`, `REPORT-NONE-OBSERVED`, `STOP-WHILE-MOVING`, `CMD-DUPLICATE-GOTO` done; `RADIO-FIRST-FRAME-FATE` reopened).
- [x] 4.3 Bundled copy regenerated, byte-identical.

## 5. Review (PR #53)

- [x] 5.1 Failing first: Stop while a lost frame waits for its retry, Stop after the readback took the re-send, a lost re-send is one frame. Fix: Stop moves the generation on; the retry and the re-send check it just before sending; the re-send is a single frame. `TRACKING_NEEDED_OPS` is 15.
- [x] 5.2 Failing first: the harness reported a go-to where the shade already is, and cancelled a report already sent when a new command came. Fix: reports only on a change of the radio's copy; a sent report still arrives (`report_latency`); the tracker tested against a late report of the previous move.
- [x] 5.3 Closed-limit change during a retry: superseded by the retirement of closed-limit enforcement (design.md).
- [x] 5.4 README troubleshooting; Part 1 §3a (Zigbee closes stop at the remote limit) and §3c; test plan `CMD-UP-OPEN-DIRECTION`, `CMD-NEW-GOTO-WHILE-MOVING`, `LIMIT-ZIGBEE-IGNORES-STOP` done.

## 6. Re-review (PR #53)

- [x] 6.1 Failing first: a go_to(20) queued before a Stop moved the shade after it. Fix: a movement issued before a Stop is dropped when it gets the lock, answering SUCCESS unsent.
- [x] 6.2 Failing first: Stop during delivery with no report left the position stale. Fix: after a Stop, wait `STOP_SETTLE_S` for the shade's report, else read once.
- [x] 6.3 README: Stop cancels the retry and drops queued commands; Part 1 §3c stale `up_open` sentence removed; test plan `CMD-UP-OPEN-DIRECTION` replies, start and travel recorded.
- [x] 6.4 Failing first: a go-to issued just before a Stop cancelled the Stop's read, leaving the position stale with reports off. Fix: a movement a Stop superseded skips its `_cancel_tracking()`.
