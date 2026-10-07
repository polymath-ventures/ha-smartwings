## ADDED Requirements

### Requirement: Coordinate spaces are named and converted in one module

U SHALL perform every conversion between HA cover position, raw ZCL lift and scaled ZCL lift
in a single pure module (`LiftScale`) with no I/O and no device access. Every variable,
argument and attribute that holds a position SHALL name its space in its identifier
(`raw_lift`, `scaled_lift`, `ha_position`). "Stop short" SHALL be expressed only in raw lift,
where it means a smaller value (Part 3 F1).

Definitions, with the closed limit `s` in raw HA cover position (0 = mechanically closed,
100 = open) as defined by `closed-limit-contract`:
- stop lift `L = 100 - s`
- close target `A = L - CLOSE_TARGET_MARGIN`, with `CLOSE_TARGET_MARGIN = 2` lift points (the
  `CLOSED_LIMIT_` prefix is reserved for the published contract terms)
- closed band: raw lift `r >= S`, where `S = A - min(CLOSED_BAND, A // 4)` and
  `CLOSED_BAND = 2` lift points; the band shrinks so it never takes more than a quarter of the
  travel to the close target (at the highest stop, 95, `A = S = 3`)
- scale: `scaled_lift(r) = 100` if `r` is in the closed band, else
  `round_half_up(99 * r / (S - 1))`
- unscale: `raw_lift(p) = A` if `p = 100`, else `round_half_up(p * (S - 1) / 99)`
- with no closed limit set, both functions are the identity.

Scaled lifts 0 to 99 are spread over the open raw lifts 0 to `S - 1` in both directions, so a
go-to to any position short of closed lands short of the closed band; only scaled 100 (HA
position 0) is sent to `A` and reads closed. A position landed on reads back within half a raw
lift step of the one sent, `99 / (2 * (S - 1))` positions plus rounding: within 1 position for
closed limits 0 to 62, and up to 25 at 94 and 95.

Known limit: for closed limits 91 to 95 there are fewer than 8 lift points to the close target,
so the band is narrower than `CLOSED_BAND` (1 point for 91 to 94, none at 95). At 95 the close
target and the band start coincide at raw lift 3, so a landing one point short of the target
reads HA position 1 (open). Integer lift cannot avoid this without letting a position above 0
read closed.

#### Scenario: Stops at 14 maps to the expected raw lifts
- **WHEN** the closed limit is 14
- **THEN** the stop lift is 86, the close target is raw lift 84, raw lift 82 through 100 scale to 100, raw lift 0 scales to 0, scaled 50 unscales to raw lift 41, and scaled 99 unscales to raw lift 81

#### Scenario: Only slider position 0 reads closed
- **WHEN** any HA position from 0 to 100 is unscaled with any valid closed limit and the shade lands exactly there
- **THEN** the shown position is closed only for position 0, it is within `99 / (2 * (S - 1)) + 1/2` of the position sent, and the raw lifts sent never increase as the position rises

#### Scenario: The highest stop has no closed band
- **WHEN** the closed limit is 95 and the shade lands at raw lift 2, one point short of the close target 3
- **THEN** the cover reads HA position 1, open

#### Scenario: Unscale never exceeds the close target
- **WHEN** any scaled lift from 0 to 100 is unscaled with any valid closed limit
- **THEN** the raw lift is between 0 and the close target inclusive

#### Scenario: Scale is monotonic and round-trips outside the closed band
- **WHEN** raw lifts 0 through 100 are scaled with any valid closed limit
- **THEN** the scaled values never decrease, and for every raw lift below the closed band, unscaling its scaled value returns it within 1 lift point

#### Scenario: Unset limit is the identity
- **WHEN** no closed limit is set
- **THEN** every raw lift scales to itself and every scaled lift unscales to itself

### Requirement: Close and positions honour the closed limit

With a closed limit set, U SHALL translate every movement command so that the raw lift sent
over the air never exceeds the close target `A`:
- `down_close` (0x01) SHALL be sent as `go_to_lift_percentage(A)`.
- `go_to_lift_percentage(p)`, with `p` given positionally or as `percentage_lift_value=`, SHALL
  be treated as scaled lift and sent as `go_to_lift_percentage(raw_lift(p))`.
- `go_to_lift_value` (0x04) SHALL be refused with an error naming the shade, because its units
  are relative to installed limits the device reports as unset (Part 1 §2), so it cannot be
  bounded.
No caller (dashboard, voice, scene, script, automation, bridge, direct service call or ZHA's
cluster-management panel) SHALL be able to cause a frame that moves the shade past its stop
(Part 3 §1a-2, §2g).

#### Scenario: Close with a stop set
- **WHEN** the closed limit is 14 and `down_close` is commanded
- **THEN** exactly one movement frame per delivery attempt is `go_to_lift_percentage` with raw lift 84, and no `down_close` or `up_open` frame is sent

#### Scenario: Position at, above and below the old raw stop
- **WHEN** the closed limit is 14 and `go_to_lift_percentage` is commanded with scaled lift 0, 50, 99 and 100, each in positional and keyword form
- **THEN** the frames carry raw lift 0, 41, 81 and 84 respectively, and no frame exceeds raw lift 84

#### Scenario: go_to_lift_value with a stop set
- **WHEN** the closed limit is set and `go_to_lift_value` is commanded
- **THEN** no frame is sent and the call raises an error naming the shade

#### Scenario: Open is unaffected by the stop
- **WHEN** the closed limit is 14 and the shade is commanded to any scaled lift
- **THEN** the shade can still reach raw lift 0 (fully open)

### Requirement: Every open is an absolute go-to 0

U SHALL send every `up_open` (0x00), whether or not a closed limit is set, as
`go_to_lift_percentage(0)` (raw lift 0), delivered and verified through `command-delivery`'s
`_deliver(WireCommand(...))`. This changes the form of the command, not its direction or end
point (fully open), which is what Part 3 §3a constrains; go-to 0 reached the top first time on
the unit where run-to-limit open stalled (Part 1 §3b, DH:210-222), and it does not depend on the
unverified direction of the raw command IDs (Part 1 §3c). Owner decision, 2026-10-05.

#### Scenario: Open with a stop set
- **WHEN** the closed limit is 14 and `up_open` is commanded
- **THEN** the frame is `go_to_lift_percentage` with raw lift 0

#### Scenario: Open with no stop set
- **WHEN** no closed limit is set and `up_open` is commanded
- **THEN** the frame is `go_to_lift_percentage` with raw lift 0, and no `up_open` or `down_close` frame is sent

### Requirement: Stock behaviour when no closed limit is set

With no closed limit set, U SHALL send, for every command other than an open (which follows
"Every open is an absolute go-to 0"), exactly the frame the released vendor quirk
(`zhaquirks.smartwings.wm25lz`, zha-quirks 2.3.x) sends: `down_close` swapped to `up_open`,
every other command unchanged. The close keeps the vendor frame until hardware test 8a (#4)
reports which way it moves these units. U SHALL NOT change the direction or end point of any
command in this state; it MAY add the delivery verification and re-sends of
`command-delivery` (Part 3 §3a, §2e). An absent closed limit SHALL never be replaced by a
default (F15).

#### Scenario: Close with no stop matches the released quirk frame for frame
- **WHEN** no closed limit is set and `down_close` is commanded through U and through the released `InvertedWindowCoveringCluster`
- **THEN** the decoded frames (command ID and payload) are identical, namely `up_open` with no payload

#### Scenario: Positions with no stop pass through unchanged
- **WHEN** no closed limit is set and `go_to_lift_percentage(37)` is commanded
- **THEN** the frame is `go_to_lift_percentage` with lift 37, identical to the released quirk's

#### Scenario: Out-of-range stored value behaves as unset
- **WHEN** the stored closed limit is outside the contract's valid range
- **THEN** every frame except an open is identical to the released quirk's, an open is `go_to_lift_percentage(0)`, and the displayed position is the raw lift

### Requirement: The displayed position is scaled to the closed limit

U SHALL store attribute 0x0008 `current_position_lift_percentage` in the cluster's attribute
cache as scaled lift, by transforming every incoming raw value (read responses and reports)
through `LiftScale` before it enters the cache. ZHA therefore reports HA position 0 and state
"closed" when the shade rests in the closed band, and scales positions between the open limit
and the stop (Part 3 §2h). U SHALL keep the most recent raw lift received from the device in
memory. The return value of `read_attributes` for 0x0008 SHALL remain the raw device value, so
capture (`closed-limit-capture`) and delivery verification (`command-delivery`) always see raw
lift. No code path SHALL compare a cached (scaled) lift with a raw lift. A raw value outside
0–100 (including the ZCL "unknown" 0xFF) SHALL NOT enter the cache or the raw field.

#### Scenario: Resting at the stop reads closed
- **WHEN** the closed limit is 14 and a read returns raw lift 84
- **THEN** the cached lift is 100, and the ZHA cover entity reports position 0 and state closed

#### Scenario: Mid-travel is scaled
- **WHEN** the closed limit is 14 and a read returns raw lift 41
- **THEN** the cached lift is 50 and the ZHA cover entity reports position 50

#### Scenario: Read return value stays raw
- **WHEN** the closed limit is 14 and a caller reads 0x0008 live
- **THEN** the call returns the raw device lift while the cache holds the scaled lift

#### Scenario: Unknown position is not cached
- **WHEN** a read or report returns lift 255
- **THEN** the cached lift and the in-memory raw lift keep their previous values

### Requirement: Changing or clearing the closed limit rescales at once

When the closed limit is set, changed or cleared, U SHALL recompute the cached scaled lift
from the in-memory raw lift under the new limit and emit the attribute update so the cover
entity redraws without a device read. If no raw lift has been received since startup, U SHALL
derive one by unscaling the cached value under the previous limit, SHALL use it for display
only, and SHALL report no raw baseline to the delivery layer until a live read replaces it.
A limit change SHALL NOT retarget a command already in flight; the next command uses the new
limit.

#### Scenario: Setting a stop rescales the card
- **WHEN** the shade's last raw lift is 84, no limit is set, and the limit is then set to 14
- **THEN** the cached lift changes from 84 to 100 and the cover entity reports closed without any frame being sent

#### Scenario: Clearing the stop restores raw display
- **WHEN** the limit is 14, the last raw lift is 42, and the limit is cleared
- **THEN** the cached lift becomes 42 and the cover entity reports position 58

#### Scenario: Limit change after restart with no live read
- **WHEN** after a restart the cache holds scaled lift 50 from limit 14, no read has succeeded, and the limit changes to 20
- **THEN** the raw lift is derived as 41, the cache is rescaled under limit 20, and the delivery layer receives no raw baseline

### Requirement: Stop is passed through and never synthesised

U SHALL send `stop` (0x02) exactly once, unchanged, without verification or re-send, in both
the set and unset states, and SHALL surface the device's reply to the caller unchanged. U SHALL
NOT synthesise a stop from a position read or any go-to (Part 3 §2l, F16, Part 1 §3d).

#### Scenario: Stop is sent once
- **WHEN** `stop` is commanded with or without a closed limit
- **THEN** exactly one `stop` frame is sent and no read or go-to follows it

#### Scenario: Device refusal is surfaced
- **WHEN** the device answers `stop` with UNSUP_CLUSTER_COMMAND
- **THEN** the caller receives that status and no other frame is sent

### Requirement: Lift values and command IDs are corrected independently

U SHALL never alter a lift value to compensate for a command-ID behaviour, and never alter a
command ID to compensate for a lift-value behaviour. The only command-ID substitutions are the
vendor quirk's `down_close` → `up_open` swap for a close in the unset state and the translation
of commands into `go_to_lift_percentage`; the only lift-value transform
is `LiftScale` (Part 3 F18).

#### Scenario: No inverted lift in the unset state
- **WHEN** no closed limit is set and `go_to_lift_percentage(10)` is commanded
- **THEN** the frame carries lift 10, not 90

#### Scenario: No run-to-limit frame in the set state
- **WHEN** a closed limit is set and any of `up_open`, `down_close` or `go_to_lift_percentage` is commanded
- **THEN** every frame sent is `go_to_lift_percentage`

### Requirement: A failure to read the closed limit fails closed

If reading the closed limit raises, rather than reporting it absent, U SHALL refuse the
movement command with an error naming the shade and send no frame. Absent means unset; an
error never means unset (Part 3 F13).

#### Scenario: Contract read raises
- **WHEN** the closed-limit read raises an unexpected exception during `down_close`
- **THEN** no frame is sent and the command raises an error naming the shade

### Requirement: Translated commands are delivered through the delivery layer

U SHALL translate every command that can move the shade (`up_open`, `down_close`,
`go_to_lift_percentage`, `go_to_lift_value`) exactly once, while holding `command-delivery`'s
per-shade lock, so the closed limit that shapes its frame is the one in force when it is sent;
a command queued behind another is translated only when its turn comes. The translated
`WireCommand(command_id, args, target_lift)` carries `target_lift` in raw lift and is delivered
and verified under that lock; one with no target (`go_to_lift_value` with no closed limit set)
is sent once, unverified, still under the lock. `stop`, tilt and every other command are
translated and sent once, unverified, without waiting for the lock. Every command that takes
the lock becomes the newest, so a command it waited behind does not start tracking afterwards.
`_cancel_tracking()` runs before the lock wait, so a movement then refused at translation
(`go_to_lift_value` with a closed limit set, which ZHA never sends) sends nothing and starts no
tracking, and the position shown stays as last read until the next refresh; this cost is
accepted so that a new command supersedes tracking at once. U SHALL provide delivery's
baseline by overriding `_cached_lift_raw()` to return the raw lift last received from the
device, the cached value when no closed limit is set, and `None` otherwise; no other baseline
accessor SHALL exist.

#### Scenario: Close target reaches delivery in raw lift
- **WHEN** the limit is 14 and `down_close` is commanded
- **THEN** delivery receives `WireCommand(go_to_lift_percentage, (84,), 84)` with the shade's lock held

#### Scenario: A stop set while a command waits is honoured
- **WHEN** no limit is set, a `down_close` or `go_to_lift_value` is queued behind another command on the shade, and the limit is set to 14 before it gets the lock
- **THEN** the close is sent as `go_to_lift_percentage(84)` and the `go_to_lift_value` is refused unsent

#### Scenario: Baseline stays raw under rescaling
- **WHEN** the limit is 14, a read returned raw lift 84 (cache holds scaled 100), and a go-to command is issued
- **THEN** `_cached_lift_raw()` returns 84 to delivery, not 100

#### Scenario: End to end through the real ZHA cover entity
- **WHEN** in the real-ZHA harness the closed limit is set to 14, `cover.close_cover` is called on the real cover entity, and the simulated motor reports arrival at raw lift 84
- **THEN** the wire carried `go_to_lift_percentage(84)`, and the `cover.*` state is closed with position 0

### Requirement: U is one v2 quirk that keeps the vendor quirk's behaviour

U SHALL be registered as a single quirks v2 quirk (`zhaquirks.builder.QuirkBuilder`) for
"Smartwings" / "WM25/L-Z" that replaces the WindowCovering cluster with the enforcement
subclass, adds the closed-limit cluster defined by `closed-limit-contract`, and keeps the
released vendor quirk's doubled battery percentage reporting (ADR 0001). The enforcement
subclass SHALL read the closed limit from the sibling closed-limit cluster on endpoint 1 by
cluster id, and SHALL rescale when that cluster reports the value updated or cleared.

#### Scenario: Battery percentage matches the vendor quirk
- **WHEN** the shade reports `battery_percentage_remaining` = 42
- **THEN** the battery entity shows the same value the released vendor quirk shows for that report

#### Scenario: A cleared stop rescales without a write through the cluster
- **WHEN** the limit is 14, the cover shows scaled positions, and the stop is cleared with zigpy's `update_attribute(attr, None)`
- **THEN** the displayed position returns to the raw scale at once and no frame is sent

#### Scenario: The v2 quirk wins over the vendor quirk
- **WHEN** U is supplied through `custom_quirks_path` and Home Assistant starts
- **THEN** the shade's WindowCovering cluster is the enforcement subclass and the closed-limit cluster is present

