# position-readback Specification

## Purpose
TBD - created by archiving change add-final-position-readback. Update Purpose after archive.
## Requirements
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

#### Scenario: Without a report one read at the arrival estimate ends it
- **WHEN** the same close is made and no report reaches the hub
- **THEN** one read at the estimated arrival shows the cover `closed` at 0

#### Scenario: An early-travel reading never stands as the final position (F17)
- **WHEN** a refresh reads lift 0 at 10 s into a 60 s close to lift 100, because the radio answers
  reads from its copy of the lift until travel ends
- **THEN** nothing is re-sent, and the last value in the attribute cache after travel ends is 100

#### Scenario: A command reported as failed is still followed by tracking
- **WHEN** both frames' replies are lost, so `command-delivery` returns FAILURE, and the motor
  starts moving late (Part 1 §3h)
- **THEN** tracking runs and the cached position reflects the end of travel it observes

### Requirement: End of travel is established by target or stationarity
Tracking SHALL compare lifts seen, by report or read, in raw ZCL lift space with the commanded
wire target. The end of travel is established when a lift seen equals the commanded wire target,
or when two consecutive lifts seen are equal and either the shade has been seen to move (a lift
at least `MOVED_TOLERANCE` from delivery's baseline before the command, `command-delivery`) or the
lifts are within `AT_TARGET_TOLERANCE` of the target, where a go-to lands, with or without a
baseline; the latter, with no movement seen, ends tracking for display only and restores no
delivery baseline (`command-delivery`). A lift that differs from the previous one SHALL NOT end
tracking, and lifts away from the target that do not show movement SHALL NOT end it: after such
a lift the next read SHALL be taken as late as `TRACK_MAX_DURATION` allows, and a report ends
that wait, so a late start is still seen (Part 1 §3h).

#### Scenario: A late start on a short move is not mistaken for the end
- **WHEN** a go-to from lift 40 to lift 50 is acknowledged and the motor starts 100 s after the
  command
- **THEN** the read at the arrival estimate shows 40 and draws the one re-send, a later reading of
  40 does not end tracking, and the shade's report sets the cached lift to 50 within
  `TRACK_MAX_DURATION` of the re-send, with no WARNING

#### Scenario: An unknown start lift does not hide a late start
- **WHEN** the lift before a go-to lift 50 is unknown, and the motor starts 100 s after the command
- **THEN** readings of the start lift do not end tracking, and the cached lift becomes 50

#### Scenario: A first move after a restart that lands short ends quietly
- **WHEN** nothing has been read since a restart and a go-to stalls one lift point short of its
  target
- **THEN** the report and a confirming read there end tracking, the cover shows that position, no
  re-send follows, and no WARNING is logged

#### Scenario: A shade that never moves is never declared at rest
- **WHEN** the motor never moves
- **THEN** after the one re-send, tracking ends at its bounds with one WARNING and one deferred
  re-read, the cached lift stays the one read, and no reading is reported as the final position

#### Scenario: Reaching the target ends tracking after one matching read
- **WHEN** a go-to lift 60 is tracked with no report and a reading returns exactly 60
- **THEN** tracking ends and sends no further reads

#### Scenario: A shade stopped short of the target is settled where it stopped
- **WHEN** a go-to lift 0 is tracked on a shade with no closed limit set and the motor stalls at
  lift 45 (Part 1 §3b)
- **THEN** two consecutive readings of 45 end tracking, and the cover shows HA position 55

#### Scenario: A moving shade keeps being tracked
- **WHEN** consecutive readings are 30, 42, 55
- **THEN** tracking continues

### Requirement: Tracking is bounded and sparse
Tracking SHALL wait for the shade's report until its first read, which it SHALL take at the
estimated arrival time, computed from the remaining distance and the named constant
`FULL_TRAVEL_S` (plus `ARRIVAL_MARGIN_S`, no earlier than `TRACK_MIN_FIRST_READ_S`), then at most
one confirming read `CONFIRM_GAP_S` later, and at most `TRACK_MAX_READINGS` reads in total. It
SHALL end no later than `TRACK_MAX_DURATION` after it starts. When the first lift seen draws the
re-send (`command-delivery`), these bounds SHALL start again from the re-send, once. Every frame
and read attempt, including retries, the re-send and the deferred re-read, SHALL draw from the
per-command radio budget passed by `command-delivery`, and tracking SHALL stop when that budget
is spent; it SHALL never need more than `TRACKING_NEEDED_OPS`. When tracking ends without
establishing the end of travel, U SHALL log one WARNING naming the shade's IEEE and, if budget
remains, schedule exactly one deferred re-read 300 s later. That re-read SHALL be cancelled by
any later movement command on the same shade. Normal tracking SHALL log only at DEBUG (Part 3
§3c).

#### Scenario: A full close without a report costs one read
- **WHEN** a close from lift 0 to lift 100 is tracked, no report arrives, and the simulated motor
  travels for 60 s
- **THEN** the first tracking read happens at `FULL_TRAVEL_S + ARRIVAL_MARGIN_S` (73 s), returns
  100, and tracking ends after that one read

#### Scenario: A short move reads early
- **WHEN** a go-to from lift 50 to lift 60 is tracked
- **THEN** the first tracking read happens at 10/100 × `FULL_TRAVEL_S` + `ARRIVAL_MARGIN_S` (10 s)

#### Scenario: An unreachable shade stops being read
- **WHEN** every read during tracking fails
- **THEN** tracking ends after at most `TRACK_MAX_READINGS` readings, one WARNING naming the IEEE
  is logged, nothing is re-sent, and the read attempts do not exceed `TRACKING_MAX_OPS`

#### Scenario: A shade that never becomes stationary is abandoned at the bound
- **WHEN** every reading differs from the previous one
- **THEN** tracking ends after `TRACK_MAX_READINGS` readings (and by `TRACK_MAX_DURATION`), with
  one WARNING and one deferred re-read

#### Scenario: The deferred re-read corrects the position later
- **WHEN** tracking was abandoned, no report arrived, and the shade is readable 300 s later
- **THEN** the deferred re-read updates the cached position and the cover state

#### Scenario: A spent budget stops tracking
- **WHEN** delivery used all but two operations of the command's radio budget
- **THEN** tracking makes at most two read attempts and schedules nothing further

### Requirement: Tracking never delays or blocks commands
Tracking SHALL NOT hold the per-shade command lock from `command-delivery`, including while it
re-sends. Tracking SHALL start from `command-delivery`'s
`_on_movement_finished(target_lift, budget, resend)` hook and SHALL be cancelled from its
`_cancel_tracking()` hook. A new movement command on a shade SHALL cancel that shade's tracking,
any pending deferred re-read and any pending re-send, before it waits for the lock or is sent.
Cancellation SHALL NOT add to the command's documented worst-case duration (Part 3 §3g). A Stop
command SHALL NOT cancel tracking, which then shows where the shade halted, but SHALL drop the
pending re-send. Tracking on one shade SHALL NOT delay commands or tracking on another shade.

#### Scenario: A new command supersedes tracking
- **WHEN** a close is being tracked and the user calls `cover.open_cover` on the same shade
- **THEN** the close's tracking is cancelled, the open is sent without waiting for the close's
  tracking, and a new tracker follows the open

#### Scenario: Stop does not end tracking
- **WHEN** a go-to is being tracked and `cover.stop_cover` halts the shade
- **THEN** tracking continues, nothing is re-sent, and the cover ends where the shade halted

#### Scenario: Two shades track independently
- **WHEN** shade A is being tracked and shade B receives a command
- **THEN** shade B's command is sent within its own worst-case duration, unaffected by shade A

### Requirement: Moves made by the remote are corrected by an on-demand refresh
U SHALL NOT poll a shade periodically. A `homeassistant.update_entity` call on the shade's
`cover.*` entity SHALL perform a live read through `command-delivery`'s read retry and update
the cover state. This SHALL also hold after a Home Assistant restart. Whether the shade reports
the end of a move made with its remote, as it reports moves commanded over Zigbee (#51), has not
been measured; the refresh is the fallback. Because the record shows this refresh failing on some
shades before the read retry existed (DH:194-197), it SHALL be verified on the real Office Shade
during hardware acceptance (#15).

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

### Requirement: The shade's end-of-travel report ends tracking without a read
The motor sends its position when travel ends (at its target, a stall, or a Stop), and the radio pushes it, when it differs from the radio's copy, to the coordinator as a Report Attributes for 0x0102/0x0008, which zigpy and ZHA handle as any attribute report (#51; firmware analysis §4). Tracking SHALL wait for that report before each scheduled read and SHALL take the reported lift as a reading without sending a read. Only a pushed report SHALL wake the tracker: a lift read by anyone during travel returns the lift from before the move and SHALL NOT. A report that arrives while no tracker waits updates the cache as for any device, and SHALL restore a baseline when it is the exact target that tracking gave up on.

#### Scenario: A full move costs no read
- **WHEN** a go-to is delivered to a healthy shade that reports its end of travel
- **THEN** tracking ends on the report, at the target, with no read sent, and the target is the next baseline

#### Scenario: Through the real ZHA cover entity
- **WHEN** `cover.close_cover` is called from HA position 100 and the shade reports lift 100 at the end of a 60 s travel
- **THEN** the cover shows `closed` at position 0 with no read sent, and before the report it shows the starting position

#### Scenario: A late report of the previous move
- **WHEN** a go-to 80 ends, a go-to 20 is sent before its report arrives, and the report of 80 reaches the hub after the go-to 20's tracking has started
- **THEN** it never ends tracking early; at most it draws the one harmless re-send, and the cover ends at 20 with no WARNING

#### Scenario: A go-to where the shade already is
- **WHEN** a go-to is sent to the lift the shade is at, so no report follows
- **THEN** the read at the arrival estimate ends tracking at the target

#### Scenario: A report after readback gave up
- **WHEN** the shade starts after both readbacks have given up and reports its arrival at the target
- **THEN** the cover shows the target and it is the next baseline, with no further read

### Requirement: Tracking reads through the read retry and caches what the shade sent
Tracking SHALL obtain positions only through `command-delivery`'s `_read_lift_live()`, which uses the read retry and returns the lift without touching the cache. Tracking SHALL put each successful reading in the cache only through the cluster's `update_attribute`. The cluster SHALL cache every lift the shade sends, by a read, a report or tracking, exactly as sent, so that ZHA's own `100 - lift` is the only conversion between ZCL lift and HA position (F1). A lift outside 0-100, including the ZCL "unknown" 0xFF, SHALL NOT enter the cache, and SHALL raise no attribute event. Tracking SHALL compare only the returned lifts, SHALL NOT write the attribute cache by any other path, and SHALL NOT convert between coordinate spaces.

#### Scenario: A shade closed to its lower limit reads as closed
- **WHEN** `cover.close_cover` is tracked and the motor settles at its remote-set lower limit, reporting lift 100
- **THEN** the `cover.*` state is `closed` with `current_position` 0

#### Scenario: A position is shown as the shade reports it
- **WHEN** a read or report returns lift 41
- **THEN** the cached lift is 41 and the cover shows position 59

#### Scenario: Unknown position is not cached
- **WHEN** a read or report returns lift 255
- **THEN** the cached lift keeps its previous value and no attribute event is emitted

#### Scenario: A dropped read is retried, not counted as unreadable
- **WHEN** the first frame of a tracking read is dropped and its retry succeeds
- **THEN** the reading counts as one successful reading

