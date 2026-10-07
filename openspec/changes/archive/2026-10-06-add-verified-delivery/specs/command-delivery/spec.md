## ADDED Requirements

### Requirement: Movement commands are verified by reading the position back
For every command with a target lift, the quirk SHALL send the wire frame and then read the motor's live lift percentage. It SHALL re-send the identical frame only when those reads show no movement toward the target, and it SHALL stop sending once movement toward the target is observed (Part 3 §2j; §5a items 6 and 7). Movement means a change of at least `MOVED_TOLERANCE` lift points from the baseline, in the direction of the target. The baseline is the cached lift at the start of the command. The total number of frames per command SHALL NOT exceed `MAX_FRAMES`.

#### Scenario: First frame lost, second frame lands
- **WHEN** a go-to-lift command is issued with a cached baseline 40 points from the target, and the simulated motor ignores the first frame and obeys the second
- **THEN** exactly two identical frames are sent and the command reports success

#### Scenario: First frame lands
- **WHEN** a go-to-lift command is issued and the first verification read shows movement toward the target
- **THEN** exactly one frame is sent and the command reports success

#### Scenario: Frames are bounded
- **WHEN** the simulated motor never moves
- **THEN** no more than `MAX_FRAMES` frames are sent for that command

### Requirement: An unreadable position is not evidence of movement
A verification read that fails, times out, or returns a lift outside 0–100, including 255 ("unknown"), SHALL count as no evidence. When every verification read after a frame is unreadable, the quirk SHALL treat that frame as not having moved the shade, and it SHALL re-send if frames remain (F3; §5a item 9).

#### Scenario: Two unreadable reads after a frame
- **WHEN** both verification reads after the first frame fail
- **THEN** the frame is re-sent, and success is not reported on the strength of those reads

#### Scenario: Unknown position value
- **WHEN** a verification read returns lift 255
- **THEN** the read counts as unreadable, not as a position 255 points from the baseline

### Requirement: Movement away from the target is not success
A change in position away from the target SHALL NOT count as movement for the command being delivered (F4; §5a item 8).

#### Scenario: Shade coasting the wrong way
- **WHEN** the target lift is above the baseline and the verification reads show the lift falling by more than `MOVED_TOLERANCE`
- **THEN** the frame is treated as not landed and is re-sent while frames remain

### Requirement: A command that does not take effect fails through ZHA's standard path
When all frames, the verification reads and the final grace look show no movement toward the target, or `COMMAND_DEADLINE` expires first, the quirk SHALL return a Default Response whose status is `Status.FAILURE`, the reply ZHA's cover handles on its own non-SUCCESS path (owner decision 2026-10-05: match stock Home Assistant behaviour). It SHALL NOT raise a custom exception, add custom error text, or return a success status (F5; §2k; §5a item 11). Verification reads SHALL NOT write the attribute cache or notify its listeners, so the cover entity SHALL NOT show opening or closing at any point for a shade that does not move. The quirk SHALL log the shade's IEEE address at DEBUG.

#### Scenario: Total failure
- **WHEN** the simulated motor ignores every frame
- **THEN** the command returns a Default Response with `Status.FAILURE`, after at most `MAX_FRAMES` frames and one final grace look

#### Scenario: No animation after failure (real-ZHA harness)
- **WHEN** `cover.close_cover` is called on the real ZHA cover entity and delivery fails, with the verification reads answered or all lost, and the cover is then refreshed
- **THEN** the service call raises ZHA's standard `HomeAssistantError` (`Failed to close cover: …`), and no state the cover publishes, during the command or after the refresh, is `opening` or `closing`

#### Scenario: Late start inside the grace look
- **WHEN** the motor shows no movement during the frame verifications but has moved toward the target by the final grace look
- **THEN** the command reports success and no further frame is sent

### Requirement: Commands that cannot be verified are sent at least twice
When the cache holds no baseline lift, or the cached lift is already within `AT_TARGET_TOLERANCE` of the target, the quirk SHALL send the frame at least twice, `BLIND_GAP` seconds apart, instead of trusting a single frame (F6; §5a item 12).

#### Scenario: No cached baseline
- **WHEN** a go-to-lift command is issued and the attribute cache has no lift value
- **THEN** two identical frames are sent

#### Scenario: Cache already at the target
- **WHEN** the cached lift equals the target
- **THEN** two identical frames are sent

#### Scenario: First of two blind frames raises
- **WHEN** the first blind frame raises a delivery exception
- **THEN** the second frame is still sent, and the command's result is the second frame's result

### Requirement: A frame that raises does not abort delivery
A Zigbee delivery exception or timeout from one frame SHALL be treated as a frame that did not land. Delivery SHALL continue with the next frame (§5a item 10). If every frame raises and no movement is observed, the command SHALL fail through ZHA's standard path. If movement toward the target is observed even though every frame raised, the command SHALL report success with a reply ZHA reads as SUCCESS.

#### Scenario: Every frame raises, shade never moves
- **WHEN** every frame raises `DeliveryError` and the reads show no movement
- **THEN** the command returns a Default Response with `Status.FAILURE`

#### Scenario: Every frame raises, but the shade moves
- **WHEN** every frame raises and a verification read shows movement toward the target
- **THEN** the command returns a reply whose status ZHA reads as `Status.SUCCESS`

### Requirement: Commands without a target lift pass through once
A command that the caller hands to delivery without a target lift (Stop, tilt, and any command other than open, close or go-to-lift) SHALL be sent exactly once, unverified. Its reply or exception SHALL be returned unchanged (§2l; §5a item 5).

#### Scenario: Stop rejected by the device
- **WHEN** Stop is sent and the device answers UNSUP_CLUSTER_COMMAND
- **THEN** exactly one frame is sent, no position read follows, and the device's status reaches the caller

### Requirement: Attribute reads retry once
Every `read_attributes` call on the cluster, including Home Assistant's refreshes, SHALL retry once after `READ_RETRY_DELAY` when the first attempt fails with a delivery exception or timeout.

#### Scenario: First read lost
- **WHEN** the first read request times out and the second succeeds
- **THEN** the caller receives the second read's result and no error

### Requirement: Real read responses are parsed
The live-lift read SHALL parse the Read Attributes Response records that zigpy's real request path returns from `read_attributes_raw`, without writing the attribute cache. Tests SHALL NOT replace the read with a stub (§5a item 17).

#### Scenario: Read through zigpy's request path
- **WHEN** the test application answers a Read Attributes request for 0x0102/0x0008 with lift 37
- **THEN** the live-lift read returns 37

#### Scenario: Attribute reported unsupported
- **WHEN** the response marks 0x0008 as `UNSUPPORTED_ATTRIBUTE`
- **THEN** the live-lift read returns "unreadable", not a number

### Requirement: Delivery exposes tracking hooks around every movement command
For every command with a target lift, delivery SHALL call `_cancel_tracking()` before attempting to acquire the shade's lock, and SHALL call `_on_movement_finished(target_lift, budget)` with the raw target lift after the lock is released, whether delivery succeeded or failed, unless a newer command has taken the shade's lock since. `budget` is the command's radio budget, which position readback draws from. A command that gives up waiting for the lock SHALL NOT suppress the finish hook of the command it waited behind. Both hooks SHALL default to no-ops. An exception raised by a hook SHALL NOT change the command's result. Commands without a target lift SHALL call neither hook.

#### Scenario: Cancel is called before the lock is taken
- **WHEN** a go-to-lift command is issued on a shade whose lock is held by another command
- **THEN** `_cancel_tracking()` has been called before the command starts waiting for the lock

#### Scenario: Finish hook runs after success and after failure
- **WHEN** one command lands on frame 2 and another fails with `Status.FAILURE`
- **THEN** `_on_movement_finished` is called once for each, with that command's raw target lift, after the lock is released, and the second command still fails

#### Scenario: A superseded command does not start tracking
- **WHEN** a second go-to-lift command is queued behind a first and takes the lock when the first finishes
- **THEN** `_on_movement_finished` is called only for the second command

#### Scenario: A command that gives up on the lock supersedes nothing
- **WHEN** a command gives up waiting for the lock (returning `Status.FAILURE`, unsent) while another command is in delivery
- **THEN** the in-flight command's `_on_movement_finished` is still called with its own target

#### Scenario: Stop calls neither hook
- **WHEN** Stop is sent
- **THEN** neither `_cancel_tracking()` nor `_on_movement_finished` is called

### Requirement: Commands are serialised per shade without deadlock and independently across shades
At most one command SHALL be in delivery on a given shade at a time. Delivery's own frames and reads SHALL NOT acquire the per-shade lock again (F2). A command waiting for a busy shade SHALL give up with an error naming the shade once it has waited `LOCK_WAIT`. Commands on different shades SHALL NOT wait on each other (§3g; §5a item 13).

#### Scenario: Two commands on one shade
- **WHEN** two go-to-lift commands are issued at once on the same shade
- **THEN** the second command's first frame is sent only after the first command has finished

#### Scenario: Stuck shade does not delay another
- **WHEN** shade A's motor never moves and a command on shade B is issued while A's command is in delivery
- **THEN** B's command completes within B's own worst-case bound, with no wait on A

#### Scenario: No self-deadlock
- **WHEN** delivery sends frames and reads positions while holding the shade's lock
- **THEN** the command completes, and no call path inside delivery waits on that lock

### Requirement: Every command has a documented worst-case duration
The quirk SHALL document the worst-case duration of a verified command (`T_EXEC`, equal to the named `COMMAND_DEADLINE`, 25 s to start), of a blind command and of a pass-through command, each as a formula over its named timing constants. Every frame send and every read SHALL be bounded by an explicit timeout, and the verified sequence SHALL be bounded by `COMMAND_DEADLINE`. A test running in virtual time, with every send and read hanging until its timeout, SHALL assert that each command finishes within its documented bound, and that a queued command finishes within `LOCK_WAIT + T_EXEC` (§3g; §5a item 14).

#### Scenario: Worst case for a verified command
- **WHEN** every send and every read hangs until its timeout
- **THEN** the command fails within `T_EXEC` of virtual time

#### Scenario: Worst case for a queued command
- **WHEN** a command is queued behind a worst-case command on the same shade
- **THEN** it finishes within `LOCK_WAIT + T_EXEC` of being issued

### Requirement: Each movement command stays within a radio budget
Each movement command SHALL draw every frame sent and every read attempt (including read retries) from one per-command budget of `RADIO_BUDGET` operations, a named constant, shared with position-readback (#10). When the budget is spent, the quirk SHALL send no further frame or read for that command; delivery SHALL return `Status.FAILURE` and tracking SHALL stop. Delivery alone SHALL never need more than `DELIVERY_MAX_OPS`, derived from its constants.

#### Scenario: Worst case stays inside the budget
- **WHEN** the simulated motor ignores every frame and drops every read
- **THEN** the number of frames plus read attempts for the command is at most `DELIVERY_MAX_OPS`, and at most `RADIO_BUDGET` including tracking

#### Scenario: Spent budget stops traffic
- **WHEN** a command's budget is exhausted before movement is seen
- **THEN** no further frame or read is sent for that command and it returns `Status.FAILURE`

### Requirement: Normal operation does not log at WARNING
Re-sends, blind double sends, read retries, and successful late starts SHALL log at DEBUG. Only a command that ultimately fails, or a condition that should never happen, MAY log above INFO (§3c).

#### Scenario: Second frame lands
- **WHEN** a command succeeds on its second frame
- **THEN** no record at WARNING or above is emitted by the quirk's logger
