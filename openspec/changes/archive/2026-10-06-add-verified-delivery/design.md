## Context

Every route into a shade (dashboard, voice, scenes, automations, bridges) ends at
`cluster.command(...)` on the WindowCovering cluster class the quirk installs (docs Part 2 §2).
That is the only layer where delivery can be fixed for every caller.

The measured hardware facts are in Part 1 §3e and §4.

- The first frame after idle usually produces no movement, and an identical re-send works.
- Reads drop the same way.
- Answered reads take 0.8–1.9 s.
- Full travel takes 30–70 s.
- One shade once took about 100 s to start.
- habot reports that all nine shades are end devices with receiver-on-when-idle clear (8b, partial). The parent therefore holds frames until the shade polls, which makes "frame 1 never reaches the application" more likely than "acknowledged and ignored". This is not proven.
- The motors never push position reports (§3f), so a live read is the only evidence of movement.

ZHA's behaviour, from source (zha 2.3.0, `platforms/cover/__init__.py`):

- `async_open_cover`, `async_close_cover` and `async_set_cover_position` call the cluster, then check `res[1] is not Status.SUCCESS`.
- On a non-SUCCESS status they clear the lift transition and raise `ZHAException`.
- An exception propagates through HA's `convert_zha_error_to_ha_error`, which turns a `ZigbeeException` into `HomeAssistantError("Failed to send request: <message>")`.

`oldcode/custom_components/smartwings/quirks/smartwings_wm25lz.py` (v18, live on the box) already does this. Its rules were learned the hard way and are worth keeping. Its structure is not: delivery, command translation and closed-limit logic are tangled in one 200-line `command()`. It logs at WARNING in normal operation, guesses at response shapes, and catches every `Exception`.

## Goals / Non-Goals

**Goals:**
- One delivery layer, separated from command translation, that the closed-limit-enforcement (#9) and position-readback (#10) changes build on unchanged.
- Each of F2–F6 ruled out by the code's structure, each with a test that would fail if it came back. F13 (guards fail closed) and F14 (no test passes on missing input) are design guidance and review-checklist items (§5e), not dedicated tests (owner decision, 2026-10-05).
- A per-command radio budget, because these are battery-powered sleepy end devices.
- A worst-case duration computed from named constants and asserted under virtual time (§3g).
- Parsing of zigpy's real read response (§5a item 17).

**Non-Goals:**
- Deciding what frame to send, or which target. Open versus close, the closed limit, rescaling and the up/down swap belong to #9. Until #9 lands, a minimal stock translator stands in (Decision 2).
- The end-of-travel position (#10). Delivery stops looking once movement starts.
- The closed-limit attribute and its unsupported mark (#7, §5a item 15).
- Diagnosing why frame 1 is lost (Part 1 test 8b). The design tolerates either cause.

## Decisions

### 1. The seam: `WireCommand` in, a zigpy reply or an exception out

```python
@dataclass(frozen=True)
class WireCommand:
    command_id: int          # the WindowCovering server command actually sent
    args: tuple              # its positional payload, already resolved
    target_lift: int | None  # RAW ZCL lift (0 open .. 100 closed) the motor should
                             # travel toward; None = pass through once, unverified

# The translator #9 replaces: returns the wire command and the kwargs left for zigpy
def _translate(self, command_id, args: tuple, kwargs: dict) -> tuple[WireCommand, dict]

async def _deliver(self, wire: WireCommand, *, manufacturer=None, expect_reply=True,
                   tsn=None, budget: RadioBudget | None = None, **kw) -> Any
async def _read_lift_live(self, budget: RadioBudget | None = None) -> int | None
                                                # raw motor lift, or None if unreadable;
                                                # with budget, charged to it
def _cached_lift_raw(self) -> int | None        # raw lift from the cache, no traffic

# Tracking hooks for add-final-position-readback (#10); no-op defaults here
def _cancel_tracking(self) -> None
def _on_movement_finished(self, target_lift: int, budget: RadioBudget) -> None

class RadioBudget:                              # one per movement command
    limit: int; frames: int; reads: int         # used, remaining: properties
    def take(self, *, read: bool) -> bool       # spend one operation if any is left
```

`command()` does two things: `_translate()` turns the incoming `(command_id, args, kwargs)` into a `WireCommand`, then `command()` calls `_deliver`. #9 owns the translator and overrides `_translate()`. #8 owns `_deliver`, `_read_lift_live`, `_cached_lift_raw`, the lock, the tracking hook points and the timing constants. #10 reuses `_read_lift_live` and implements the two hooks.

Every value crossing the seam is in raw motor lift space. `_cached_lift_raw()` is the single name for the raw baseline. Its default here reads the cluster's attribute cache, which is raw while nothing rescales it. `add-closed-limit-enforcement` (#9) overrides `_cached_lift_raw()` to return its in-memory raw lift, because once it rescales, the cache holds scaled values; there is no separate `raw_lift_baseline()`. `_read_lift_live()` stays raw without an override: `read_attributes` returns the decoded wire value to its caller even when `_update_attribute` stores a scaled one. Comparing a scaled position with a raw target is the F1 failure.

**Tracking hooks.** For every command whose `WireCommand` has a `target_lift`, `_deliver` calls `_cancel_tracking()` *before* it tries to acquire the per-shade lock, so a new command never waits behind a tracker; and it calls `_on_movement_finished(wire.target_lift, budget)` after the lock is released, whether delivery returned or raised (a `DeliveryError` included, because a late start has been seen once). `budget` is the command's `RadioBudget`, so tracking spends what delivery left (Decision 8a); #10 passes it to `_read_lift_live(budget)`. The finish hook runs only for the newest command: each command that takes the lock increments a per-instance generation, and a command superseded by a queued one (which takes the lock before the earlier command's finish runs) does not start tracking. A command that gives up waiting for the lock (it returns `Status.FAILURE`, unsent) never takes it, so it supersedes nothing and the command it waited behind still finishes. While one command holds the lock no tracker runs, because the holder cancelled tracking before taking it, so a waiter's cancel stops nothing live. Both hooks run as event-loop callbacks: a hook that raises is reported by the loop's exception handler (at ERROR) and cannot change the command's outcome, without a broad `except` in the quirk. Commands with `target_lift=None` (Stop, tilt) call neither hook: Stop is rejected by these motors and must not end tracking of a shade that is still moving.

*Alternatives considered.* Keeping one monolithic `command()`, as in oldcode, is what made its review rounds introduce new defects. Making delivery a separate object holding a reference to the cluster is cleaner in theory, but upstream quirks are single modules and the cluster already owns the device context. Methods on the cluster class, kept in their own section, are enough.

### 2. A minimal stock translator until #9 lands

So that #8 can ship and be tested alone without changing stock behaviour (§3a), its translator does only this:

- `up_open` and `down_close` keep the released vendor quirk's swapped wire IDs, byte for byte, with target lift 0 and 100 respectively.
- `go_to_lift_percentage` uses its argument, positional or `percentage_lift_value` keyword, as the target.
- Everything else gets `target_lift=None`.

#9 replaces this translator. The tests for `_deliver` construct `WireCommand`s directly, so they do not change when it does.

### 3. Evidence rules: what counts as "it moved"

For each frame:

1. Send it.
2. Wait `SETTLE`.
3. Look up to `LOOKS_PER_FRAME` times, `LOOK_GAP` apart. Stop looking as soon as one look counts as movement.

A look counts only if `_read_lift_live()` returns a number, that number differs from the baseline by at least `MOVED_TOLERANCE`, and it lies on the target's side of the baseline:

- `None` (failure, timeout, status not SUCCESS, or a value outside 0–100, including 255) is "no evidence" (F3).
- Movement the wrong way is "not landed" (F4).

The looks run even when the send raised, because a lost acknowledgement does not mean a lost command.

After `MAX_FRAMES` frames without movement, one final look follows after `FINAL_GRACE`, to catch a late start. Without movement there, the command fails (F5; Decision 5).

The baseline is `_cached_lift_raw()` at the moment the lock is acquired. The cache cannot see a shade moved by its remote, which is why F6 exists.

### 4. Blind mode when verification is impossible (F6)

When the baseline is missing, or within `AT_TARGET_TOLERANCE` of the target, movement cannot prove delivery. Delivery then sends the frame twice, `BLIND_GAP` apart. The first frame raising does not stop the second. The result is the second frame's reply, or its exception. It does not look at all, and #10 establishes the final position.

*Alternative considered.* A live read before the first frame, to establish a baseline. It costs a frame-sized delay on every command, and the read is as droppable as the command. Rejected, but it is an open question for the hardware tests.

### 5. Failure signalling: ZHA's standard non-SUCCESS path

Owner decision, 2026-10-05: do what stock Home Assistant does and invent nothing. When delivery gives up, `_deliver` returns a Default Response, the same type zigpy returns for a device's reply, with `Status.FAILURE`, ZCL's status for "the operation was not successful", which is what a device sends for a command it did not carry out. It does this:

- after the grace look shows no travel, or when `COMMAND_DEADLINE` expires first;
- when the shade's lock is not free within `LOCK_WAIT` (the command is not sent);
- when the command's radio budget is spent.

ZHA's cover then takes its own failure branch (`if res[1] is not Status.SUCCESS: self._clear_lift_transition(); raise ZHAException(...)`): it clears the lift transition target it set before the call, and Home Assistant shows ZHA's standard error, `Failed to close cover: <Status.FAILURE: 1>`, on that shade's service call (§2k). There is no custom exception and no custom error text. The quirk logs the IEEE, the wire command and the reason at DEBUG.

So that nothing appears to move before the outcome is known, delivery's verification reads use `read_attributes_raw` (Decision 6): they leave the attribute cache and its listeners alone, and ZHA, which evaluates every lift update against the target it set before the call, publishes no intermediate `closing` or `opening` state for a shade that does not move. The look that proves travel is written to the cache with `update_attribute` before success is returned. The real-ZHA harness test records every state the cover publishes during a failed close, with reads answered and with reads lost, and asserts none is `opening` or `closing`.

Pass-through commands are unchanged: the device's own reply, such as UNSUP_CLUSTER_COMMAND for Stop, already reaches ZHA's normal path. Blind mode returns its second frame's reply or exception, as Decision 4 says. Position readback after the command remains #10's job.

When at least one frame was acknowledged, success returns the reply of the frame that landed. When every frame raised but movement was seen, success returns a synthesised Default Response with `Status.SUCCESS`, so that ZHA's `res[1]` check passes.

### 6. Read retry lives in `read_attributes`

`read_attributes` is overridden to retry once after `READ_RETRY_DELAY`, catching only `DeliveryError` and `TimeoutError`. Each attempt is wrapped in `asyncio.timeout(READ_TIMEOUT)`, and zigpy's own retries are forced off, so each attempt is one frame. This covers Home Assistant's refreshes; delivery's looks get the same retry.

`_read_lift_live()` reads the lift through zigpy's real request path with `read_attributes_raw([ATTR_LIFT.id])`, which returns the decoded Read Attributes Response records without writing the cache or notifying listeners (Decision 5). It takes the record for 0x0008: a failure status, a whole-request failure status, or a value outside 0–100 is unreadable. There is no probing of shapes. A caller that wants the cache updated (the landed look here, final-position readback in #10) writes the returned raw lift with `update_attribute`, which is also where #9's rescaling applies.

### 7. Serialisation (F2, §3g)

There is one `asyncio.Lock` per cluster instance, which means one per shade. `command()` acquires it with `asyncio.timeout(LOCK_WAIT)` only when `target_lift is not None`. Pass-through commands such as Stop do not wait behind a 60-second verification. This matters if the firmware ever implements Stop.

Inside the lock, frames go out through `super().command(...)`, the zigpy base, never through `self.command`. Reads go through `read_attributes`, which never takes the lock. So no code path re-enters the lock (F2). A test runs a full delivery under `asyncio.timeout` and asserts it completes.

Locks are per instance, so different shades never contend.

### 8. Timing constants and the worst-case bound

All constants are module-level and named. The waits are the windows the previous handler used on the real shades (Part 1 §3e: 2.5 s to let the motor start, 1.5 s to a second look, 1.5 s before re-reading an unreadable position). A hard per-command deadline caps the total, so a hung send or read can never stretch it. Starting values, to be tuned against the hardware tests:

| Constant | Value | Why |
|---|---|---|
| `SETTLE` | 2.5 s | Time for the motor to start travelling (measured working) |
| `LOOK_GAP` | 1.5 s | Gap to the second look (measured working) |
| `READ_RETRY_DELAY` | 1.5 s | Gap before the single read retry (measured working) |
| `LOOKS_PER_FRAME` | 2 | |
| `MAX_FRAMES` | 3 | Every measured command landed by frame 2 or 3 |
| `FINAL_GRACE` | 2.5 s | One last look for a late start |
| `SEND_TIMEOUT` | 5.0 s | Bounds one frame send, whatever zigpy's own timeout is |
| `READ_TIMEOUT` | 2.5 s | Answered reads take ≤1.9 s |
| `BLIND_GAP` | 2.5 s | Gap between the two blind frames |
| `COMMAND_DEADLINE` | 25.0 s | Hard cap on one verified command |
| `MOVED_TOLERANCE` | 2 lift points | |
| `AT_TARGET_TOLERANCE` | 3 lift points | |
| `LOCK_WAIT` | `T_EXEC` | |

Derived bounds:

```
T_EXEC   = COMMAND_DEADLINE                                           = 25.0 s
T_BLIND  = 2·SEND_TIMEOUT + BLIND_GAP                                 = 12.5 s
T_PASS   = SEND_TIMEOUT                                               =  5.0 s
T_QUEUED = LOCK_WAIT + T_EXEC                                         = 50.0 s
```

The verified sequence runs inside `asyncio.timeout(COMMAND_DEADLINE)`. If the deadline expires before movement is seen, the command returns `Status.FAILURE` (Decision 5); movement seen earlier has already returned success. With answered reads, three frames' waits (3 × (`SETTLE` + `LOOK_GAP`) + `FINAL_GRACE` = 14.5 s) plus their reads fit inside the deadline; when reads are slow the deadline may cut the last look short, which is the intended trade.

The test computes these from the constants, not from literals, so tuning a constant cannot leave the test asserting a stale number. It drives the worst case (every send and read hangs) under virtual time and asserts each command finishes within its bound. A typical healthy command takes about `SETTLE` plus one read, roughly 4 s.

### 8a. Radio budget

These motors are battery-powered sleepy end devices (Part 1 8b), so every frame and read costs battery and coordinator airtime. Each movement command gets one budget, `RADIO_BUDGET = 25` operations, where an operation is one frame sent or one read attempt (a read retry is a second operation). Delivery's structural maximum is `DELIVERY_MAX_OPS = MAX_FRAMES + (MAX_FRAMES·LOOKS_PER_FRAME + 1)·2 = 17`. The remainder, `TRACKING_MAX_OPS = 8`, belongs to position-readback (#10), which draws from the same budget object passed through `_on_movement_finished`. When the budget is spent, no further frame or read goes out: delivery returns `Status.FAILURE`, and tracking stops on `RadioBudgetSpentError` from `_read_lift_live(budget)`. A healthy command uses about 4 operations (one frame, one or two looks, two tracking reads).

### 9. Logging (§3c)

Re-sends, blind sends, read retries, late starts and giving up log at DEBUG with the IEEE address. A failure reaches the user through ZHA's standard error (Decision 5); the quirk logs nothing above DEBUG for it. There is no activation log.

### 9a. Review checklist items (not tests)

Two lessons from the previous work are kept as review items under Part 3 §5e rather than as tested requirements, because neither can be tested meaningfully:

- **Guards fail closed (F13).** Only the expected outcomes of a lost frame or read (zigpy delivery exceptions, timeouts, failure statuses, out-of-range values) count as "no evidence". Any other exception propagates; no `except Exception`.
- **No test passes on missing input (F14).** Tests assert the frames or reads they rely on were actually captured.

### 10. What is ported from oldcode, and what is dropped

Ported, each behind a failing test first:

- The direction-aware movement check (`_started_moving`).
- The rule that two unreadable looks mean re-send.
- The double send when there is no baseline or the cache is at the target.
- A raising first frame not stopping the second.
- The final grace look.
- The single read retry.
- The synthesised SUCCESS when every frame raised but the shade moved.

Dropped:

- WARNING logs in normal operation.
- `_LOGGED_ONCE` and the activation banner.
- The `async_initialize` live read, which does not fire for cache-loaded devices.
- The multi-shape probing in `_live_lift` and `_cached_lift`.
- Blanket `except Exception` handlers.
- `QUIRK_VERSION`.

## Risks / Trade-offs

- **Bounds too short for a slow starter.** One shade once took about 100 s to start; delivery would fail and then the shade would move anyway. → Accepted. #10's end-of-travel read corrects the display, and the constants are tunable from the hardware data.
- **Re-sending while the first frame is still queued at the parent.** On a sleepy end device the parent may deliver frame 1 late, and the motor then gets two identical go-tos. → Harmless for an absolute go-to, which is idempotent. For the stock run-to-limit swap, a duplicate also goes the same way.
- **Blind mode cannot detect failure** when there is no baseline. → Accepted by F6's own wording. #10's read gives the truth, and a baseline exists after the first successful read.
- **ZHA's transition target after a failure** (Decision 5). → Settled: failure returns `Status.FAILURE`, so ZHA clears it on its own path; asserted by a harness test.
- **A 25 s deadline (50 s queued) can give up on a shade that would have moved** given a longer wait. → Accepted. #10 corrects the display if it does, and the constants are tunable from the hardware data.

## Migration Plan

This is new code; nothing is migrated. On the box it replaces v18 as part of #15's runbook. Rollback means restoring v18 in `custom_quirks_path` and restarting.

## Open Questions

- Should a pre-read baseline replace blind mode when the cache is empty? Decide from hardware data on the Office Shade (Part 1 8b).
- Do the constants hold on real hardware? Tune `SETTLE` and `MAX_FRAMES` from the hardware tests (#4) and the acceptance runs (#15).
- What exact type does zigpy return for a Default Response, so the synthesised SUCCESS matches it? Confirm in zigpy 2.3.x while implementing; the harness test asserts ZHA accepts it.
- Should a newer command on a busy shade pre-empt the in-flight one instead of queueing (open, then close a second later)? Out of scope here; raise it after acceptance if users hit `T_QUEUED`.
