## Why

Issue #51, measured live on the Office Shade on 2026-10-06 (bench session B): the radio answers a read of 0x0102/0x0008 from its own copy of the lift, which changes only when the motor sends a position, and the motor sends one only when travel ends (at its target, a stall, or a Stop). A go-to 50 from 0 read 0 at every read for 15 s, then 50 once stopped; a raw `up_open` from 71 read 71 at about 5 s and 7 s. When the motor sends that position the radio also pushes it to the coordinator as an attribute report, which ZHA takes as any report: a Stop at 0.5 s into a go-to 30 from 50 was reported as 44 at 2.5 s, and a go-to 30 from 44 as 30 at 6.2 s. A duplicate go-to (the same target twice, 2.5 s apart) moved the shade once. The motor halts on Stop.

U's verified delivery read the lift 2.5 s and 4 s after each frame and took "no change of 2 points" as "not moving". On any move longer than about 4 s it therefore re-sent up to three frames and returned FAILURE while the shade was moving normally. The harness motor interpolated its position continuously, so no test caught it. Part 1 §3e's "first frame produced no movement" was judged in the same window and is confounded.

## What Changes

- **Send once, return at once.** A movement is sent once and returns the radio's answer (0x81 already reported as SUCCESS, #47), as the stock quirk and the old blind path did; a frame lost on the air is sent once more after `SEND_RETRY_DELAY`, and only if both are lost does the command fail with FAILURE. Nothing is read before the command returns. `T_EXEC` falls from 25 s to 12.5 s.
- **Judge after the travel time, re-send once.** Position readback waits for the shade's end-of-travel report; without one, it reads at the estimated arrival (the existing schedule). The first lift so seen decides: if it is more than `AT_TARGET_TOLERANCE` from the target and shows no travel toward it from the baseline (with no baseline, any lift away from the target), the identical frame is re-sent once, as a single frame, and readback starts again from that lift with its bounds renewed. A read during travel never decides anything; only a pushed report wakes the tracker. Nothing is re-sent after a command that did not get SUCCESS, or once the closed limit has changed. Stop moves the shade's generation on, which cancels a pending retry of a lost frame and any re-send, even one the readback already holds. No error reaches Home Assistant after the command has returned: a shade that still does not move is logged at WARNING, as readback already does.
- **One path.** The blind path (two frames when there is no baseline or the cache is at the target) is gone: every movement takes the same path, and with no baseline only a lift within `AT_TARGET_TOLERANCE` of the target counts as arrival.
- **Budget.** Delivery needs at most `SEND_ATTEMPTS` (2) operations; readback, with its reads before and after the re-send, the one re-send frame and the deferred re-read, at most `TRACKING_NEEDED_OPS` (15). Both fit `RADIO_BUDGET` (25), unchanged.
- **Harness.** `MotorSim` answers reads from the radio's copy (`radio_cache`, default on), pushes a report when that copy changes (`reports`, default on; nothing for a go-to where the shade already is; a report already sent still arrives after a later command, `report_latency`), halts on Stop (`stop_halts`, default on), and can send positions during travel (`report_interval_s`) or acknowledge and ignore the next frames (`ignore_next`). Under the copy alone, 38 existing tests failed against the old quirk (listed in the tasks).
- **Docs.** Part 1 §3c-§3f and §4 record the measurements and the §3e confound; Part 3 §2j, §2k, §3g, F5, F6 and §5a follow the new contract; README and the test plan updated.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `command-delivery`: send once and return; a lost frame is sent once more; a movement that shows no travel by its travel time is re-sent once by the readback; the blind path and the delivery-time failure are removed; bounds, budget and hooks follow.
- `position-readback`: the shade's end-of-travel report ends tracking without a read; reads only at the arrival estimate; the first lift seen decides the single re-send, after which tracking starts again with renewed bounds; Stop drops the re-send.
- `closed-limit-enforcement`: a translated movement is sent under the lock and judged afterwards; a re-send never goes out under a closed limit other than the one it was translated under.

## Impact

- `quirk/zhaquirks/smartwings/wm25lz.py` and its bundled copy.
- `tests/zha_harness/motor.py`, `tests/zha_harness/radio.py`, the quirk tests and the real-ZHA delivery and readback tests.
- The integration's capture refuses a moving shade by two equal reads, which cannot see travel under the measured behaviour; filed as #52, its test marked `xfail(strict=True)`.
