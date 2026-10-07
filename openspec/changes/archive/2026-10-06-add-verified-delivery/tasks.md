## 1. Test scaffolding (needs #2's environment)

- [x] 1.1 Add a U test module in upstream zha-device-handlers style that builds the WM25/L-Z device from its signature and gets the quirk's real WindowCovering cluster instance
- [x] 1.2 Add a scripted motor at zigpy's application `request` layer. It decodes every outgoing ZCL frame, records it, answers Read Attributes for 0x0008 with real `ReadAttributesResponse` frames, and can be scripted to drop frames N, answer UNSUP_CLUSTER_COMMAND, hang, raise `DeliveryError`, move at a set rate or move the wrong way
- [x] 1.3 Run the tests in virtual time (event-loop time travel, no real sleeps), with a helper that asserts elapsed virtual time
- [x] 1.4 Add a helper that asserts the exact decoded frame list

## 2. Seam and live read (TDD)

- [x] 2.1 Failing test: `_read_lift_live()` returns 37 from a real response through zigpy's request path (§5a item 17); returns None for UNSUPPORTED_ATTRIBUTE, for 255, and on timeout
- [x] 2.2 Implement the `WireCommand` dataclass, `_cached_lift_raw()` and `_read_lift_live()`, which looks up `success[ATTR_LIFT]` by the requested definition
- [x] 2.3 Failing test: `read_attributes` retries once after a timeout or `DeliveryError`, and does not retry on other exceptions
- [x] 2.4 Implement the `read_attributes` override with `asyncio.timeout(READ_TIMEOUT)` per attempt

## 3. Verified delivery (TDD, one failing test before each step)

- [x] 3.1 Test and implement: no re-send after movement toward the target, so one frame (§5a item 7)
- [x] 3.2 Test and implement: re-send after no movement, so frame 2 lands (§5a item 6)
- [x] 3.3 Test and implement: wrong-direction movement is not success, so a re-send follows (F4, §5a item 8)
- [x] 3.4 Test and implement: two unreadable looks are no evidence, so a re-send follows (F3, §5a item 9)
- [x] 3.5 Test and implement: every frame raises with no movement, so delivery returns `Status.FAILURE` into ZHA's standard non-SUCCESS path (owner decision 2026-10-05); every frame raises with movement, so a SUCCESS reply that ZHA's `res[1]` check accepts (§5a items 10 and 11)
- [x] 3.6 Test and implement: a late start within `FINAL_GRACE` succeeds; no movement raises; never more than `MAX_FRAMES` frames (F5)
- [x] 3.7 Test and implement: blind mode sends two frames when there is no baseline and when the cache is at the target; a raising first frame still leads to a second (F6, §5a item 12)
- [x] 3.8 Test and implement: `target_lift=None` is sent exactly once, unverified, with no read; the UNSUP_CLUSTER_COMMAND reply is returned unchanged (§2l, §5a item 5)

## 4. Serialisation and bounds

- [x] 4.1 Test and implement: two concurrent commands on one shade are serialised, with frame order proving it (§5a item 13)
- [x] 4.2 Test: a stuck shade A does not delay shade B, and B finishes within its own bound (§3g)
- [x] 4.3 Test: a full delivery under `asyncio.timeout(T_EXEC + 1)` completes, with no path re-entering the lock (F2)
- [x] 4.4 Implement the per-instance lock with `LOCK_WAIT`; a lock-wait timeout returns `Status.FAILURE`; pass-through commands skip the lock
- [x] 4.5 Define the timing constants (old measured windows, `COMMAND_DEADLINE` = 25 s) and derive `T_EXEC`, `T_BLIND`, `T_PASS` and `T_QUEUED` from them in code; run the verified sequence under `asyncio.timeout(COMMAND_DEADLINE)`
- [x] 4.6 Test: with every send and read hanging, each command finishes within its derived bound, and a queued command within `T_QUEUED`, with bounds computed from the constants rather than literals (§3g, §5a item 14)
- [x] 4.7 Failing test, then implement: `_cancel_tracking()` is called for every movement command before the lock is awaited (a recording subclass proves the order while the lock is held elsewhere); Stop and tilt do not call it
- [x] 4.8 Failing test, then implement: `_on_movement_finished(target_lift, budget)` is called once after the lock is released, on success and on a returned `Status.FAILURE`, with the raw target; a hook that raises leaves the command's result unchanged; Stop and tilt do not call it
- [x] 4.10 Failing test, then implement: the per-command radio budget (`RADIO_BUDGET`, `DELIVERY_MAX_OPS`, `TRACKING_MAX_OPS`); worst case counts frames + read attempts ≤ `DELIVERY_MAX_OPS`; a spent budget sends nothing further and raises; the budget object is passed to `_on_movement_finished` for #10
- [x] 4.9 Test: `_cached_lift_raw()` is the only baseline accessor `_deliver` uses, so a subclass override (as #9 provides) changes the baseline without touching delivery

## 5. Stock translator and wiring

- [x] 5.1 Failing test: with no closed limit, `up_open`, `down_close` and `go_to_lift_percentage` (positional and `percentage_lift_value` keyword) put exactly the frames of the released vendor quirk `zhaquirks.smartwings.wm25lz.WM25LBlinds` on the wire (§3a)
- [x] 5.2 Implement the minimal stock translator from design Decision 2, with `command()` calling translate then `_deliver`; leave a clear hand-off point for #9
- [x] 5.3 Test: re-sends, blind sends, read retries and late starts emit nothing at WARNING or above; the quirk logs nothing at import or instantiation (§3c)

## 6. Entity layer (needs #5's real-ZHA harness)

- [x] 6.1 Harness test: `cover.close_cover` with the first frame dropped yields one service call, two frames on the wire and no error (§2j)
- [x] 6.2 Harness test: with the motor never moving, `cover.close_cover` raises `HomeAssistantError` containing the IEEE, and the cover state is neither `opening` nor `closing` afterwards (§2k). If this fails because ZHA keeps its transition target, switch to the non-SUCCESS-reply fallback from design Decision 5 and re-run
- [x] 6.3 Harness test: `cover.stop_cover` sends exactly one Stop frame, and the device's UNSUP_CLUSTER_COMMAND reaches the user as an error (§2l)

## 7. Close-out

- [x] 7.1 Document the delivery seam and the bound table in the quirk's module docstring (no fleet-specific text, §3c)
- [x] 7.4 Review checklist (§5e): guards fail closed (F13: no `except Exception`; only lost-frame outcomes count as no evidence) and no test passes on missing input (F14)
- [x] 7.2 `ruff check` passes under upstream zha-device-handlers rules; the full U test suite passes
- [x] 7.3 Note on issue #9 and issue #10 the final seam signatures, if they changed during implementation
