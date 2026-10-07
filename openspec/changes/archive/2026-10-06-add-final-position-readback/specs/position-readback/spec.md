## ADDED Requirements

### Requirement: Every movement command is tracked to the end of travel
U SHALL start end-of-travel tracking for a shade after it finishes delivering any movement
command (open, close, or go-to lift percentage), including one that `command-delivery` reported
as failed. Tracking SHALL continue until the end of travel is established or a bound in
"Tracking is bounded" is reached. "Complete" means the shade stopped travelling, not that the
command was accepted (Part 3 §2i).

#### Scenario: The cover shows the final position after a close, without a manual refresh
- **WHEN** a shade at HA position 100 receives `cover.close_cover` through the real ZHA cover
  entity, with no closed limit set, and the simulated motor travels to lift 100 over 60 s
- **THEN** after the simulated travel ends the `cover.*` state is `closed` with
  `current_position` 0, and no `homeassistant.update_entity` call was needed

#### Scenario: An early-travel reading never stands as the final position (F17)
- **WHEN** delivery verification reads lift 20 at 2.5 s into a 60 s close to lift 100, and ZHA's
  5 s post-update transition timer expires
- **THEN** tracking keeps reading, and the last value in the attribute cache after travel ends is
  100, not 20

#### Scenario: A command reported as failed is still followed by tracking
- **WHEN** `command-delivery` raises because no movement was seen, and the simulated motor
  starts moving late (Part 1 §3h)
- **THEN** tracking runs and the cached position reflects any movement it observes before it settles

### Requirement: End of travel is established by target or stationarity
Tracking SHALL compare live readings in raw ZCL lift space with the commanded wire target. The
end of travel is established when a successful reading equals the commanded wire target, or when
two consecutive successful readings are equal and the shade has been seen to move: delivery's look
or a reading at least `MOVED_TOLERANCE` from the raw lift before the command. With that lift
unknown, only a reading equal to the target ends tracking early. A reading that differs from the previous successful reading SHALL NOT end tracking, and
readings still at the pre-command lift SHALL NOT end it: after such a reading the next SHALL be
taken as late as `TRACK_MAX_DURATION` allows, so a late start is still seen (Part 1 §3h).

#### Scenario: A late start on a short move is not mistaken for the end
- **WHEN** delivery of a go-to from lift 40 to lift 50 gives up and the motor starts 100 s after
  the command
- **THEN** readings of 40 do not end tracking, and the cached lift is 50 within
  `TRACK_MAX_DURATION`, with no WARNING

#### Scenario: An unknown start lift does not hide a late start
- **WHEN** the lift before a go-to lift 50 is unknown, and the motor starts 100 s after the command
- **THEN** readings of the start lift do not end tracking, and the cached lift becomes 50, by a
  later reading or by the deferred re-read

#### Scenario: A shade that never moves is never declared at rest
- **WHEN** delivery gives up and the motor never moves
- **THEN** tracking ends at its bounds with one WARNING and one deferred re-read, the cached lift
  stays the one read, and no reading is reported as the final position

#### Scenario: Reaching the target ends tracking after one matching read
- **WHEN** a go-to lift 60 is tracked and a reading returns exactly 60
- **THEN** tracking ends and sends no further reads

#### Scenario: A shade stopped short of the target is settled where it stopped
- **WHEN** a go-to lift 0 is tracked on a shade with no closed limit set and the motor stalls at
  lift 45 (Part 1 §3b)
- **THEN** two consecutive readings of 45 end tracking, and the cover shows HA position 55

#### Scenario: A moving shade keeps being tracked
- **WHEN** consecutive readings are 30, 42, 55
- **THEN** tracking continues

### Requirement: Tracking is bounded and sparse
Tracking SHALL take its first reading at the estimated arrival time, computed from the remaining
distance and the named constant `FULL_TRAVEL_S` (plus `ARRIVAL_MARGIN_S`, no earlier than
`TRACK_MIN_FIRST_READ_S`), then at most one confirming reading `CONFIRM_GAP_S` later, and at most
`TRACK_MAX_READINGS` readings in total. It SHALL end no later than `TRACK_MAX_DURATION` after it
starts. Every read attempt, including retries and the deferred re-read, SHALL draw from the
per-command radio budget passed by `command-delivery`, and tracking SHALL stop when that budget
is spent. When tracking ends without establishing the end of travel, U SHALL log one WARNING
naming the shade's IEEE and, if budget remains, schedule exactly one deferred re-read 300 s
later. That re-read SHALL be cancelled by any later movement command on the same shade. Normal
tracking SHALL log only at DEBUG (Part 3 §3c).

#### Scenario: A full close usually costs one read
- **WHEN** a close from lift 0 to lift 100 is tracked and the simulated motor travels for 60 s
- **THEN** the first tracking read happens at `FULL_TRAVEL_S + ARRIVAL_MARGIN_S` (73 s), returns
  100, and tracking ends after that one read

#### Scenario: A short move reads early
- **WHEN** a go-to from lift 50 to lift 60 is tracked
- **THEN** the first tracking read happens at 10/100 × `FULL_TRAVEL_S` + `ARRIVAL_MARGIN_S` (10 s)

#### Scenario: An unreachable shade stops being read
- **WHEN** every read during tracking fails
- **THEN** tracking ends after at most `TRACK_MAX_READINGS` readings, one WARNING naming the IEEE
  is logged, and the total read attempts do not exceed `TRACKING_MAX_OPS`

#### Scenario: A shade that never becomes stationary is abandoned at the bound
- **WHEN** every reading differs from the previous one
- **THEN** tracking ends after `TRACK_MAX_READINGS` readings (and by `TRACK_MAX_DURATION`), with
  one WARNING and one deferred re-read

#### Scenario: The deferred re-read corrects the position later
- **WHEN** tracking was abandoned and the shade is readable 300 s later
- **THEN** the deferred re-read updates the cached position and the cover state

#### Scenario: A spent budget stops tracking
- **WHEN** delivery used all but two operations of the command's radio budget
- **THEN** tracking makes at most two read attempts and schedules nothing further

### Requirement: Tracking never delays or blocks commands
Tracking SHALL NOT hold the per-shade command lock from `command-delivery`. Tracking SHALL start
from `command-delivery`'s `_on_movement_finished(target_lift, budget)` hook and SHALL be cancelled from its
`_cancel_tracking()` hook. A new movement command on a shade SHALL cancel that shade's tracking,
and any pending deferred re-read, before it waits for the lock or is sent. Cancellation SHALL NOT add to the command's documented worst-case duration (Part 3 §3g). A
Stop command, which the device rejects (Part 1 §3d), SHALL NOT cancel tracking. Tracking on one
shade SHALL NOT delay commands or tracking on another shade.

#### Scenario: A new command supersedes tracking
- **WHEN** a close is being tracked and the user calls `cover.open_cover` on the same shade
- **THEN** the close's tracking is cancelled, the open is sent without waiting for the close's
  tracking, and a new tracker follows the open

#### Scenario: Stop does not end tracking
- **WHEN** a close is being tracked and `cover.stop_cover` is rejected with UNSUP_CLUSTER_COMMAND
- **THEN** tracking continues and the cover ends at the shade's real final position

#### Scenario: Two shades track independently
- **WHEN** shade A is being tracked and shade B receives a command
- **THEN** shade B's command is sent within its own worst-case duration, unaffected by shade A

### Requirement: Tracking reads through the single conversion and the read retry
Tracking SHALL obtain positions only through `command-delivery`'s `_read_lift_live()`, which
uses the read retry and returns raw lift without touching the cache. Tracking SHALL put each
successful reading in the cache only through the cluster's `update_attribute`, so the single
HA↔ZCL conversion and rescaling owned by `closed-limit-enforcement` (`LiftScale`) applies (F1).
Tracking SHALL compare only the raw returned values, SHALL NOT write the attribute cache by any
other path, and SHALL NOT convert between coordinate spaces itself.

#### Scenario: A shade closed to its stop reads as closed
- **WHEN** the closed limit is HA position 14, `cover.close_cover` is tracked, and the motor
  settles at the stop
- **THEN** the `cover.*` state is `closed` with `current_position` 0, as defined by
  `closed-limit-enforcement`

#### Scenario: A dropped read is retried, not counted as unreadable
- **WHEN** the first frame of a tracking read is dropped and its retry succeeds
- **THEN** the reading counts as one successful reading

### Requirement: Moves made by the remote are corrected by an on-demand refresh
U SHALL NOT poll a shade periodically. A `homeassistant.update_entity` call on the shade's
`cover.*` entity SHALL perform a live read through `command-delivery`'s read retry and update
the cover state. This SHALL also hold after a Home Assistant restart. Because the record shows
this refresh failing on some shades before the read retry existed (DH:194-197), it SHALL be
verified on the real Office Shade during hardware acceptance (#15).

#### Scenario: A remote-driven move is corrected by a refresh
- **WHEN** the simulated motor is moved from lift 0 to lift 70 with no Zigbee command, and
  `homeassistant.update_entity` is called on the cover
- **THEN** the `cover.*` `current_position` becomes 30

#### Scenario: No reads happen without a command or refresh
- **WHEN** a shade is idle for one hour with no command and no refresh
- **THEN** U sends no frames to it

### Requirement: Tracking tasks end cleanly
Every tracking task and deferred re-read SHALL end, by settling, by a bound, or by cancellation,
without an unretrieved exception, including on Home Assistant shutdown and ZHA reload. Tracking
SHALL stop, and SHALL NOT start, once the shade's zigpy device is torn down (shutdown,
re-interview) or removed from the network.

#### Scenario: A removed or re-interviewed shade is no longer read
- **WHEN** a shade is being tracked and is removed, or its device is replaced by a re-interview
- **THEN** its tracking and any deferred re-read are cancelled and no further frame is sent to it

#### Scenario: A removal during delivery starts no tracking
- **WHEN** a shade is removed while a movement command to it is being delivered
- **THEN** the delivery's end starts no tracker and no deferred re-read, and no frame follows it

#### Scenario: A reload during delivery starts no tracking
- **WHEN** ZHA reloads while a movement command is being delivered
- **THEN** the delivery's end starts no tracker, and no frame follows it

#### Scenario: No lingering tasks after a test
- **WHEN** a tracked command's test finishes under pytest-homeassistant-custom-component's
  lingering-task and lingering-timer checks
- **THEN** no tracking task or timer is reported as lingering

#### Scenario: Shutdown during tracking
- **WHEN** Home Assistant stops while a shade is being tracked
- **THEN** the tracking task is cancelled and no "Task exception was never retrieved" is logged
