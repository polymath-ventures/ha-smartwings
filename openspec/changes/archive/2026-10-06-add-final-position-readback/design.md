## Context

The motors never report position (Part 1 §3f). ZHA configures reporting on 0x0008, but nothing
ever arrives. The cached `current_position_lift_percentage` changes only when something reads it.

ZHA's cover state machine (zha 2.3.x, `zha/application/platforms/cover/__init__.py`) behaves as
follows:

1. When an HA command succeeds, ZHA sets a target and a transition timer of
   |Δ| × 0.01 × `LIFT_MOVEMENT_TIMEOUT_RANGE` (300 s), so a full close shows "closing" for up to 300 s.
2. Every position attribute event goes through `handle_attribute_updated`. That covers
   `AttributeReadEvent` (a read with an unchanged value) and `AttributeUpdatedEvent` (a changed
   or quirk-transformed value). Each event appends to a position history and re-determines state.
   While the cover is moving, the timer is cut to `DEFAULT_MOVEMENT_TIMEOUT` (5 s).
3. The cover is "not moving" when the reading equals the target, or when the previous and current
   readings are equal. When the timer expires, state is recomputed from the cache with no target.

So the delivery-verification reads at about 2.5–10 s (`add-verified-delivery`) set a mid-travel
value. Five seconds later ZHA recomputes from it and shows "open at <mid-travel>" until something
reads again. That is F17.

Constraints: U must not import Home Assistant or touch files (Part 3 §3b). It must meet upstream
norms, with no WARNING in normal operation (§3c). Commands have a documented worst-case duration
(§3g). Conversion between HA and ZCL space happens in exactly one place (F1), owned by
`add-closed-limit-enforcement`. Reads drop like commands (Part 1 §3e), and the shades are sleepy
end devices.

## Goals / Non-Goals

**Goals:**
- The cached position after every movement command is the shade's real resting position.
- The `cover.*` state shows a live position, rather than a stale one, while the shade travels.
- Traffic, duration and task lifetime are bounded, and commands are never delayed.
- Moves made by the remote are corrected by a documented on-demand refresh.

**Non-Goals:**
- Periodic background polling by U.
- Estimating position without reading (dead reckoning).
- Synthesising Stop (Part 3 §2l, F16). Tracking never sends a movement frame.
- HA-side automations. Those are documentation in #14.

## Decisions

### D1. A background tracker per shade, started after delivery
`add-verified-delivery` serialises commands per shade and returns success or failure within its
bound. When a movement command's delivery sequence finishes, whether it succeeded or raised, U
starts a tracker task for that shade, passing the commanded wire target in raw ZCL lift. The
trigger is #8's hook `_on_movement_finished(target_lift: int, budget)`, which `_deliver` calls after
releasing the per-shade lock, including when it raises a `DeliveryError`; this change overrides
#8's no-op default. Commands with `target_lift=None` (Stop, tilt) never call it. The
command returns to ZHA without waiting for the tracker, so §3g's bound is unchanged.

The tracker starts on failure too. A late start was observed once, about 100 s after
acceptance (Part 1 §3h). Starting the tracker anyway costs about two reads when nothing moves,
and those reads come from the same per-command budget (D4).

*Alternative rejected:* awaiting the end of travel inside `command()`. The service call would
block for up to 70 s, ZHA would hold the command, and §3g's bound would grow by the whole travel time.

### D2. Settle criterion: target reached, or two equal consecutive readings
Readings are compared in raw ZCL lift, the value the device returned, against the raw wire
target. Equality with the target ends tracking at once. Otherwise two consecutive successful
readings that are equal end it, but only once the shade has been seen to move: delivery's look
or a reading at least `MOVED_TOLERANCE` from the raw lift before the command (`_cached_lift_raw()`
when the command took the lock). With that lift unknown, only a reading equal to the target ends
tracking early. Readings still at the start may be a
late start (Part 1 §3h, up to about 100 s), so after one the next reading waits for the last slot
that fits in `TRACK_MAX_DURATION`; if the bounds run out first, D7's WARNING and re-read apply.
A failed read between two readings does not break the pair, because a shade cannot leave a
position and return to it unless a new command was sent, and a new command cancels the tracker.

The criterion also lines up with ZHA. An equal-value read emits `AttributeReadEvent`, and ZHA
then sees previous == current, declares the cover not moving, clears its timer, and shows
open or closed at the real position. A stall short of the target (Part 1 §3b) or a stop margin
(`add-closed-limit-enforcement`) settles at the real position, not at the target.

*Alternative rejected:* a tolerance band around the target, such as ±3. A shade still creeping
inside the band would be declared final.

### D3. Sparse reads at the estimated arrival time (owner decision, 2026-10-05)
These motors are battery-powered sleepy end devices, and every read costs battery and
coordinator airtime. Tracking therefore reads only when the answer is likely to be final:

1. **Arrival read.** When tracking starts, the remaining distance is |target − last cached raw
   lift| (the last cached value is usually delivery's verification read; if there is none, a full
   travel is assumed). The first read is at `remaining / 100 × FULL_TRAVEL_S + ARRIVAL_MARGIN_S`,
   but no earlier than `TRACK_MIN_FIRST_READ_S`.
2. **Confirming read.** If the arrival reading equals the target, tracking ends. Otherwise one
   more read follows `CONFIRM_GAP_S` later; if it equals the previous reading (D2), tracking ends.
3. **Still moving.** If the confirming read differs, one further read is scheduled at the
   estimated arrival for the new remaining distance (at least `CONFIRM_GAP_S`). At most
   `TRACK_MAX_READINGS` readings are taken; then D7 applies.

`FULL_TRAVEL_S` defaults to 70 s, the top of the measured 30–70 s range (Part 1 §4), so the
arrival read usually finds the shade already stopped and a command costs about two tracking
reads. It is one named constant, tunable from the per-shade timings in hardware tests (#4, #15).

**Accepted cosmetic cost.** Between delivery's verification read and the arrival read, ZHA's
5 s `DEFAULT_MOVEMENT_TIMEOUT` can expire and show the mid-travel verification value as a
stationary position (for example "open at 70" during a close) for part of the travel. The final
position is still correct (§2i, F17 are about the final value). Polling every 4 s would hide
this, at roughly ten times the radio traffic; the owner chose fewer reads.

*Alternative rejected:* polling every 4 s (the first draft). About 18 reads per full travel and
about 160 reads in 70 s for a nine-shade scene, purely to keep the card animating.

### D4. Bounds and radio budget
| Constant | Value | Why |
|---|---|---|
| `FULL_TRAVEL_S` | 70 s | Top of measured full travel (Part 1 §4) |
| `ARRIVAL_MARGIN_S` | 3 s | Slack past the estimate |
| `TRACK_MIN_FIRST_READ_S` | 5 s | Never read sooner than ZHA's own movement timer |
| `CONFIRM_GAP_S` | 5 s | Gap to the confirming read |
| `TRACK_MAX_READINGS` | 3 | Arrival, confirm, one more |
| `TRACK_MAX_DURATION` | 120 s | Hard cap from tracker start; about 1.7× the longest travel |
| `DEFERRED_REREAD_DELAY` | 300 s | Matches ZHA's `LIFT_MOVEMENT_TIMEOUT_RANGE`; one read only |

Every read attempt, including the read retry and the deferred re-read, draws from the
per-command radio budget that `command-delivery` passes to `_on_movement_finished(target_lift,
budget)`. Tracking's share is `TRACKING_MAX_OPS = 8`: at most `TRACK_MAX_READINGS` readings plus
one deferred re-read, each at most two attempts. When the budget is spent, tracking stops
without scheduling anything further. Typical cost: two reads per command. One tracker per shade,
so a nine-shade scene runs at most nine trackers and about 18 reads in total.

### D5. Interaction with the per-shade lock: never hold it, cancel on supersede
The tracker never acquires `add-verified-delivery`'s lock. Before acquiring the lock, #8's
`command()` calls the hook `_cancel_tracking()` for every movement command; this change
overrides #8's no-op default to cancel that shade's tracker task and its deferred re-read handle.
The hook is synchronous and does not await the cancelled task: cancellation lands at the
tracker's next `await`, which is prompt because the tracker only sleeps or awaits a read. A tracker read in flight when cancellation lands is abandoned. If its response still
arrives, zigpy updates the cache with a value that is true at that moment, and the new command's
verification overwrites it immediately.

Stop is a pass-through that the device rejects, so it does not cancel tracking. If firmware
starts honouring Stop, two equal readings settle the tracker anyway.

*Alternative rejected:* tracking under the lock. One shade's 70 s travel would block the user's
next command on that shade for 70 s, which violates §3g and the "a new command must supersede"
requirement.

### D6. No converting; the cache is written only through `update_attribute`
The tracker calls `_read_lift_live(budget)`, the cluster's live-read helper owned by #8 and the
same one delivery verification uses. That helper applies the read retry and uses
`read_attributes_raw`, so it leaves the cache and its listeners alone and returns the raw lift.
As #8's delivery does for the look that proves travel, the tracker then writes each successful
reading with the public `update_attribute`, which reaches `_update_attribute`, where
`add-closed-limit-enforcement` applies its single raw↔rescaled transform, and emits the event
ZHA consumes. The tracker holds only raw readings, for comparison. It never calls
`_update_attribute` itself and never computes `100 - x` (F1, F18).

This split works because of how ZHA 2.3 reads the position (verified in source): the cover's
`current_cover_position` returns `100 - self._cluster.get(current_position_lift_percentage)`
(`zha/application/platforms/cover/__init__.py:333-347`), and `async_update` only repopulates the
cache through `safe_read` (`:620-631`). ZHA therefore displays whatever `_update_attribute`
cached, the scaled value when a stop is set, while `read_attributes` returns the undecorated
device value to its caller. The tracker's settle rule compares those returned raw values.

### D7. Abandoning, and the deferred re-read
If a bound ends tracking without establishing the end, U logs one WARNING with the IEEE and
the reason (still moving, unreadable, the duration cap, or a spent budget) and, while the
command's budget has operations left, schedules one deferred re-read 300 s later. The last live
reading stays in the cache. It is the latest observation, not an early-travel one.

*Alternative rejected:* invalidating the cached position. With `current_position` unknown,
ZHA's `async_set_cover_position` hits `assert self.current_cover_position is not None`, so the
slider would raise instead of moving the shade.

### D8. Moves made by the remote are corrected by refresh, documented in #14
ZHA entities do not poll (`should_poll` is False), and nothing is pushed. The correction path is
`homeassistant.update_entity`, which ZHA routes to `async_update`. That calls `safe_read(...,
allow_cache=False)`, which reaches the cluster's `read_attributes` and therefore the read retry.
U adds no polling loop: upstream norms and battery-powered devices argue against it, and the old
code's `async_initialize`-driven read never fired (oldcode quirk docstring). The README (#14)
documents an example automation: refresh every cover at HA start and hourly. I does not own a
refresh mechanism.

**Unverified on the real shades.** The research record says an `update_entity`-based refresh
"fixed 6 of 9 once and then left others wrong" (DH:194-197). Part 1 §3e attributes that to reads
with no retry, which `command-delivery` now adds, so it is expected to work; but nothing has
verified it since. Hardware acceptance (#15) must verify a remote-driven move is corrected by the
refresh on the Office Shade before the README presents it as the mechanism.

### D9. Virtual time and testability
The tracker and the deferred re-read are tasks that sleep through `asyncio.sleep` on the running
loop. They are created with the zigpy application's `create_task`, whose `shutdown()` cancels
them (Home Assistant stop, ZHA reload). Not the device's own `create_task`: zigpy 2.3's
`Device.on_remove()` empties that task set before the cancelled tasks finish, and each task's
done callback then raises `KeyError`. The cluster registers on the device's on-remove callbacks
(zigpy's `_on_remove_callbacks`, called on shutdown and when a re-interview replaces the device;
zigpy has no public hook) and, for its whole life, listens on the application for
`device_removed`, which zigpy 2.3 emits when a removal starts, up to 30 s before it lets go of the
device. Either marks the device gone: tracking is cancelled, a later finish starts none, and every
tracking step checks the mark before it reads. The listener is dropped in the same teardown. Tests drive time through the #5 harness's virtual clock. Unit
tests use the real cluster class and zigpy's real request path with the simulated motor, as
§5a requires, and never stub the read helper (§5a item 17).

## Risks / Trade-offs

- [The card can show a stale mid-travel position until the arrival read] → Accepted cosmetic
  cost (D3); the final position is correct.
- [`FULL_TRAVEL_S` too short for a slow shade] → The confirming and further reads catch it;
  tune the constant from hardware data.
- [The `update_entity` refresh for remote moves has a mixed record (DH:194-197)] → Verified in
  hardware acceptance (#15) before it is documented as the mechanism (D8).
- [A read in flight at cancellation lands after the new command's first verification read] →
  The value is still a real observation, and the next verification read overwrites it. No
  movement decision uses the tracker's readings.
- [The tracker starts a background task inside a quirk; upstream may question it] → Every task
  ends by settling, a bound or cancellation, and is tested against lingering-task checks. The PR
  (#17) explains the need with Part 1 §3f evidence.
- [The tracker settles on two equal readings while a motor is momentarily paused] → No pause
  mid-travel has been observed. If one appears in hardware testing, require three equal
  readings, a one-constant change.
- [ZHA reload while tracking] → Cluster objects are rebuilt and the old tracker's reads fail.
  It ends at the unreadable bound, logging at most one WARNING. The task is also cancelled on
  shutdown.

## Migration Plan

Nothing to migrate: this is new behaviour in U. Rollback is reverting the change, after which
positions are stale after moves, as today.

## Open Questions

- Is `FULL_TRAVEL_S` = 70 s right for each shade? Measure per-shade travel in #4/#15 on the
  Office Shade first, with tracking read counts logged at DEBUG.
- Does any real unit pause mid-travel long enough to produce two equal readings `CONFIRM_GAP_S`
  apart? If so, require three (see Risks).
