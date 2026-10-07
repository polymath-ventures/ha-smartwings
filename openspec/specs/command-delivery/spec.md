# command-delivery Specification

## Purpose
TBD - created by archiving change add-verified-delivery. Update Purpose after archive.
## Requirements
### Requirement: An unreadable position is not evidence of movement
A read that fails, times out, or returns a lift outside 0–100, including 255 ("unknown"), SHALL count as no evidence: it SHALL neither end travel nor decide the re-send, and readback SHALL read again `CONFIRM_GAP_S` later (F3; §5a item 9).

#### Scenario: Unreadable reads at the arrival estimate
- **WHEN** the read at the arrival estimate is lost twice, or returns lift 255
- **THEN** nothing is re-sent on its strength, and the next read shows the shade at its target

### Requirement: Movement away from the target is not success
A change in position away from the target SHALL NOT count as travel for the command being delivered (F4; §5a item 8).

#### Scenario: Shade sent the other way by its remote
- **WHEN** the remote sends the shade away from the target and the motor ignores the go-to
- **THEN** the lift seen after the travel time draws the one re-send, and the shade reaches the target

### Requirement: A frame that raises does not abort delivery
A Zigbee delivery exception or timeout from one frame SHALL be treated as a frame that was lost: the frame is sent once more (§5a item 10). If every frame raises, the command SHALL fail through ZHA's standard path; position-readback still follows it and shows where the shade went.

#### Scenario: Every frame raises, shade never moves
- **WHEN** every frame raises `DeliveryError`
- **THEN** the command returns a Default Response with `Status.FAILURE` after `SEND_ATTEMPTS` frames

### Requirement: Commands without a target lift pass through once
A command that the caller hands to delivery without a target lift (Stop, and any command other than open, close or go-to-lift that is not refused under "Commands the radio mangles are refused unsent") SHALL be sent exactly once, unverified. Its reply or exception SHALL be returned unchanged (§2l; §5a item 5), except that a standard Stop's UNSUP_CLUSTER_COMMAND is reported as SUCCESS: the motor halts on it (#51), so it is the firmware's second reply ("Stop is passed through once, never synthesised, and its second reply is not an error"). Stop SHALL drop a pending re-send of the previous movement. A movement issued before a Stop and still waiting for the shade's lock when the Stop is sent SHALL NOT be sent: once it gets the lock it SHALL release it and return a Default Response SUCCESS, unsent, since the user's later Stop supersedes it. After a Stop, the quirk SHALL wait `STOP_SETTLE_S` from sending it for the shade's report of its lift and, if none comes, read the lift once (a read and its retry, on a budget of its own) and cache it; a new movement cancels that read.

#### Scenario: Stop answered with the 0x81 alone
- **WHEN** Stop is sent and the device answers UNSUP_CLUSTER_COMMAND
- **THEN** exactly one frame is sent, the caller receives SUCCESS, and no read follows before `STOP_SETTLE_S`

#### Scenario: Stop under the double reply
- **WHEN** the motor sends the double reply in either order and Stop is sent
- **THEN** exactly one frame is sent, and the caller receives SUCCESS

#### Scenario: A movement queued before a Stop is dropped
- **WHEN** a go-to 80 is being delivered, a go-to 20 waits for the lock, and Stop is sent
- **THEN** the go-to 20 is never sent, returns SUCCESS, and the shade stays where Stop halted it

#### Scenario: A movement dropped by a Stop does not cancel the Stop's read
- **WHEN** a go-to and a Stop arrive in one loop turn, the go-to first, and no report reaches the hub
- **THEN** the go-to is dropped unsent, and the read after `STOP_SETTLE_S` caches where the shade halted

#### Scenario: A Stop is read back when no report comes
- **WHEN** Stop halts the shade during a movement's delivery and no report reaches the hub
- **THEN** one read `STOP_SETTLE_S` later caches where the shade halted

#### Scenario: A reported Stop is not read
- **WHEN** Stop halts the shade and it reports where
- **THEN** no read follows

#### Scenario: What Home Assistant shows for Stop
- **WHEN** in the real-ZHA harness `cover.stop_cover` is called with the motor sending the double reply in either order
- **THEN** the call raises nothing

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
For every command with a target lift, delivery SHALL call `_cancel_tracking()` before attempting to acquire the shade's lock, unless a Stop has been sent since the command was issued (that command is dropped unsent and SHALL NOT cancel tracking or the Stop's read), and SHALL call `_on_movement_finished(target_lift, budget, resend)` with the raw target lift after the lock is released, whether delivery succeeded or failed, unless a newer command has taken the shade's lock since. `budget` is the command's radio budget, which position readback draws from; `resend` sends the command's frame once more, and is None unless the command returned SUCCESS. `_cancel_tracking()` SHALL also drop a pending re-send. A Stop moves the generation on, so a movement in delivery when Stop arrives starts no tracking; the shade's report of where it halted still updates the position. A command that gives up waiting for the lock SHALL NOT suppress the finish hook of the command it waited behind. An exception raised by a hook SHALL NOT change the command's result. Commands without a target lift SHALL call neither hook.

#### Scenario: Cancel is called before the lock is taken
- **WHEN** a go-to-lift command is issued on a shade whose lock is held by another command
- **THEN** `_cancel_tracking()` has been called before the command starts waiting for the lock

#### Scenario: Finish hook runs after success and after failure
- **WHEN** one command fails with both frames lost and another succeeds
- **THEN** `_on_movement_finished` is called once for each, with that command's raw target lift, after the lock is released; only the successful one carries a re-send

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
The quirk SHALL document the worst-case duration of a movement command (`T_EXEC = SEND_ATTEMPTS × SEND_TIMEOUT + (SEND_ATTEMPTS − 1) × SEND_RETRY_DELAY`, 12.5 s) and of a pass-through command (`T_PASS`), each as a formula over its named timing constants. Every frame send and every read SHALL be bounded by an explicit timeout. The re-send after the travel time comes after the command has returned and SHALL NOT count toward it. A test running in virtual time, with every send hanging until its timeout, SHALL assert that each command finishes within its documented bound, and that a queued command finishes within `LOCK_WAIT + T_EXEC` (§3g; §5a item 14).

#### Scenario: Worst case for a movement command
- **WHEN** every send hangs until its timeout
- **THEN** the command fails within `T_EXEC` of virtual time, after two frames

#### Scenario: Worst case for a queued command
- **WHEN** a command is queued behind a worst-case command on the same shade
- **THEN** it finishes within `LOCK_WAIT + T_EXEC` of being issued

### Requirement: Each movement command stays within a radio budget
Each movement command SHALL draw every frame sent, including the re-send after the travel time, and every read attempt (including read retries) from one per-command budget of `RADIO_BUDGET` operations, a named constant, shared with position-readback (#10). When the budget is spent, the quirk SHALL send no further frame or read for that command; delivery SHALL return `Status.FAILURE` and tracking SHALL stop. Delivery alone SHALL never need more than `DELIVERY_MAX_OPS` (= `SEND_ATTEMPTS`), and readback never more than `TRACKING_NEEDED_OPS` (its reads, one re-send frame and the deferred re-read), both derived from their constants and together within `RADIO_BUDGET`.

#### Scenario: Worst case stays inside the budget
- **WHEN** every frame of a command is lost
- **THEN** the frames sent equal `DELIVERY_MAX_OPS`, counted by the budget, and the rest is left for tracking

#### Scenario: Spent budget stops traffic
- **WHEN** a command's budget is exhausted before a frame lands
- **THEN** no further frame or read is sent for that command and it returns `Status.FAILURE`

### Requirement: Normal operation does not log at WARNING
Lost frames sent again, the re-send after the travel time, read retries, and commands without a baseline SHALL log at DEBUG. Only a command whose end of travel is never seen, or a condition that should never happen, MAY log above INFO (§3c).

#### Scenario: A lost frame, a re-send and a read retry
- **WHEN** a command's first frame is lost, the motor ignores the next, a read at the arrival estimate is retried, and the re-sent frame lands
- **THEN** no record at WARNING or above is emitted by the quirk's logger

### Requirement: The firmware's second reply to a movement is not a failure
The radio answers every Window Covering command it handles with two Default Responses carrying the same TSN, SUCCESS and then UNSUP_CLUSTER_COMMAND (0x81), and zigpy returns whichever arrives first (firmware analysis §3; session A, 2026-10-06). An open, close or go-to always goes out as a standard frame, which the radio forwards to the motor (see "Commands the radio mangles are refused unsent" for manufacturer-specific ones). For such a frame, the quirk SHALL treat a Default Response UNSUP_CLUSTER_COMMAND as an answer to the frame: it SHALL NOT count it as a failure and SHALL NOT re-send because of it, and the command SHALL report it as `Status.SUCCESS`. ZHA's cover then takes its stock success path; it raises on any other status (`zha/application/platforms/cover/__init__.py:637-640`, `:663-666`, `:692-697`). Neither reply carries the motor's state, so a movement's SUCCESS reports the radio's acceptance of a frame, not movement, and SHALL be documented so. Whether the shade moved is judged after the travel time ("A movement that shows no travel by its travel time is re-sent once"), whatever the replies said. A standard Stop's reply is mapped the same way ("Stop is passed through once, never synthesised, and its second reply is not an error").

#### Scenario: A movement whichever reply wins
- **WHEN** the motor sends the double reply in either order, with or without a baseline, and an open, close or go-to is commanded
- **THEN** exactly one frame is sent and the command returns a Default Response with `Status.SUCCESS`

#### Scenario: Through the real ZHA cover entity
- **WHEN** in the real-ZHA harness the motor sends UNSUP_CLUSTER_COMMAND before SUCCESS and `cover.open_cover`, `cover.close_cover` or `cover.set_cover_position` is called
- **THEN** the service call raises nothing, one frame is sent, and the cover shows `opening` or `closing`

#### Scenario: A lone 0x81 reports acceptance, not movement
- **WHEN** the shade has no baseline, the SUCCESS reply is lost so only the 0x81 arrives, the motor does not move, and a go-to is commanded
- **THEN** one frame is sent, no position is read before the command returns SUCCESS, which the code documents as the radio's acceptance of a frame, not movement, and one re-send follows after the travel time

#### Scenario: The replies never decide movement
- **WHEN** the motor sends SUCCESS first but ignores the frame
- **THEN** the command returns SUCCESS and the frame is re-sent once after the travel time

### Requirement: Commands the radio mangles are refused unsent
The radio turns `go_to_lift_value` (0x04), `go_to_tilt_value` (0x07) and `go_to_tilt_percentage` (0x08) into malformed serial frames that can repeat the previous command or corrupt the next (firmware analysis §3 note 3). It also refuses every manufacturer-specific Window Covering frame with a genuine 0x81 without forwarding it (firmware analysis §2), so a manufacturer-specific `up_open`, `down_close` or `go_to_lift_percentage` can never take effect. The quirk SHALL never send any of these, whatever path they come by: a cluster method, `command()`, or a raw `request()`. It SHALL answer each with the Default Response a device gives for a command it does not support, `Status.UNSUP_CLUSTER_COMMAND` with the command's ID, which ZHA reports as for any unsupported command (its cluster-command service raises `Failed to issue cluster command with status: …`, `zha/zigbee/device.py:1485-1487`). A refusal SHALL NOT wait for or take the shade's lock, cancel or start tracking, or change the baseline. A manufacturer-specific Stop is not refused: it keeps Stop's pass-through, and the radio's 0x81 reaches the caller unchanged.

#### Scenario: Refused through the cluster
- **WHEN** `go_to_lift_value`, `go_to_tilt_value` or `go_to_tilt_percentage` is called on the cluster while another command holds the shade
- **THEN** it returns at once a Default Response with `Status.UNSUP_CLUSTER_COMMAND`, no frame leaves, no tracking hook runs and the baseline is unchanged

#### Scenario: A manufacturer-specific movement is refused on every path
- **WHEN** `up_open`, `down_close` or `go_to_lift_percentage` (lift 80 or 255) is commanded with a manufacturer code, with or without a baseline, while another command holds the shade
- **THEN** it returns at once a Default Response with `Status.UNSUP_CLUSTER_COMMAND`, no frame leaves, no tracking hook runs and the baseline is unchanged

#### Scenario: A manufacturer-specific Stop passes through
- **WHEN** Stop is commanded with a manufacturer code
- **THEN** one frame is sent and the radio's UNSUP_CLUSTER_COMMAND reaches the caller

#### Scenario: Refused on a raw request
- **WHEN** one of those commands, or a manufacturer-specific movement, is sent with `request()` directly
- **THEN** it returns a Default Response with `Status.UNSUP_CLUSTER_COMMAND` and no frame leaves

#### Scenario: Refused through ZHA's cluster-command service
- **WHEN** in the real-ZHA harness `zha.issue_zigbee_cluster_command` sends command 0x04, 0x07 or 0x08 to the shade's Window Covering cluster
- **THEN** the service call fails with an error naming `UNSUP_CLUSTER_COMMAND`, and no frame is sent to the shade

### Requirement: A movement is sent once and returns with the radio's answer
For every command with a target lift, the quirk SHALL send the wire frame once and return the radio's answer as "The firmware's second reply to a movement is not a failure" reports it, without reading the position first or before returning (#51). A frame lost on the air (a delivery exception or timeout) SHALL be sent once more, `SEND_RETRY_DELAY` later; at most `SEND_ATTEMPTS` frames go out before the command returns. Whether the motor acted SHALL be judged afterwards by `position-readback`, once travel should be over: the radio answers a read during travel from its copy of the lift, which changes only when the motor reports a position at the end of travel, so a read equal to the start lift during travel SHALL NOT count as evidence that the shade is not moving, SHALL NOT cause a re-send, and SHALL NOT make the command fail.

The baseline is the raw lift last received from the shade, by a read or a report, since the cluster was created at Home Assistant startup or ZHA reload. A lift restored from zigpy's database SHALL NOT be a baseline. Sending a movement SHALL retire the baseline: a lift received afterwards SHALL become the baseline only when it equals the command's target, or when position-readback ends travel on two equal readings after seeing the shade move at least `MOVED_TOLERANCE` from its baseline. Equal readings near the target with no movement seen end tracking for display only, since the shade may yet start late; after such an end, or once tracking gives up, only a lift of the exact target (by a report, the deferred re-read or a refresh) SHALL restore a baseline. A cancelled tracker restores none, and a lift read during travel is never one (#27).

#### Scenario: One frame, no read, an immediate answer
- **WHEN** a go-to-lift command is issued to a healthy shade 40 points from the target
- **THEN** exactly one frame is sent, no read precedes the command's return, and it returns SUCCESS within the radio's reply latency

#### Scenario: Reads during travel never count against the command
- **WHEN** a refresh reads the lift 4 s into the travel and the radio answers the start lift
- **THEN** nothing is re-sent, and the shade's end-of-travel report shows the target

#### Scenario: A lost frame is sent once more
- **WHEN** the first frame raises `DeliveryError`
- **THEN** the identical frame is sent again `SEND_RETRY_DELAY` later and the command returns its SUCCESS

### Requirement: A movement that shows no travel by its travel time is re-sent once
When the command returned SUCCESS, `position-readback` SHALL judge its first lift seen after the travel time (the shade's report, or the read at the estimated arrival): if that lift is more than `AT_TARGET_TOLERANCE` from the target and shows no travel toward the target from the baseline (with no baseline, any such lift), the quirk SHALL send the identical frame once more, as one frame that is never retried, charged to the command's radio budget, and readback SHALL start again from that lift (Part 1 §3e; Part 3 §2j). Re-sending the same target is harmless: a duplicate go-to moves the shade once (#51). The quirk SHALL NOT re-send more than once per command, and SHALL NOT re-send after a command that did not return SUCCESS. A Stop SHALL cancel everything pending for the shade: it moves the shade's generation on, and a lost frame's retry and the re-send SHALL each check the generation immediately before sending, so neither goes out after a Stop, even when the readback already holds the re-send. A re-send happens after the command has returned, so its outcome SHALL only be logged.

#### Scenario: An ignored first frame is re-sent once
- **WHEN** the motor acknowledges the first frame but does not act on it, with or without end-of-travel reports
- **THEN** after the estimated travel time one read shows the start lift, the identical frame is sent once more, and the shade reaches the target

#### Scenario: A shade slower than the estimate gets one harmless re-send
- **WHEN** the shade's travel takes longer than the arrival estimate, so the read at the estimate returns the start lift
- **THEN** the identical frame is re-sent once, the shade stops once at the target, and the command never fails

#### Scenario: A shade that never moves
- **WHEN** the motor acknowledges every frame and never moves
- **THEN** the command returns SUCCESS, exactly one re-send follows after the travel time, and readback ends with one WARNING naming the shade, with no error raised to Home Assistant

#### Scenario: Stop drops the re-send
- **WHEN** a go-to is followed by Stop before its travel time is over, whether the motor was moving or had ignored the frame
- **THEN** no re-send follows, and the cover shows where the shade halted

#### Scenario: Stop while a lost frame waits for its retry
- **WHEN** a go-to's frame is lost and Stop is sent before its retry
- **THEN** the retry is never sent and the go-to returns FAILURE

#### Scenario: Stop after the readback took the re-send
- **WHEN** the readback holds the re-send and Stop is sent before it is used
- **THEN** the re-send sends nothing

#### Scenario: The re-send is one frame
- **WHEN** the re-send's frame is lost
- **THEN** it is not sent again, and one frame is charged to the budget

#### Scenario: Without a baseline only a lift at the target is arrival
- **WHEN** there is no baseline and the motor ignores the first frame
- **THEN** the lift seen after the travel time, away from the target, draws the one re-send

### Requirement: Every movement takes one path
A movement with no baseline, or with the baseline already within `AT_TARGET_TOLERANCE` of the target, SHALL be sent and judged exactly as any other movement: one frame, and the readback's judgement after the travel time (F6). It SHALL NOT read the lift first.

#### Scenario: No baseline, or a cache at the target
- **WHEN** a go-to is issued with no baseline, with the baseline equal to the target, or within `AT_TARGET_TOLERANCE` of it
- **THEN** one frame is sent and the cover ends at the target

#### Scenario: A lift restored after a restart is no baseline
- **WHEN** no closed limit is set, the shade was read at lift 40, its remote moved it to 20 while Home Assistant was down, and the motor ignores the first frame of an open after the restart
- **THEN** the read after the travel time shows 20, the open is re-sent once, and the shade travels to lift 0

#### Scenario: A command during travel is not judged by the old baseline
- **WHEN** a go-to is sent before the previous movement's travel has been seen to end, and the motor ignores it
- **THEN** it has no baseline, is re-sent once after the travel time, and the shade stops at the new target

#### Scenario: A still shade near its target is no baseline
- **WHEN** a go-to from lift 49 to 52 is followed by readings of 49 until tracking ends with no report, the shade then starts late and reaches 52, and the motor ignores the first frame of a go-to 90
- **THEN** that go-to is re-sent once and the shade stops at 90

### Requirement: A command whose frames are lost fails through ZHA's standard path
When `SEND_ATTEMPTS` frames are all lost, or the radio budget is spent before a frame goes out, the quirk SHALL return a Default Response whose status is `Status.FAILURE`, the reply ZHA's cover handles on its own non-SUCCESS path (owner decision 2026-10-05: match stock Home Assistant behaviour). It SHALL NOT raise a custom exception or add custom error text (F5; §2k). Delivery SHALL NOT write the attribute cache or notify its listeners. The quirk SHALL log the shade's IEEE address at DEBUG.

#### Scenario: Both frames lost
- **WHEN** both frames raise `DeliveryError`
- **THEN** the command returns a Default Response with `Status.FAILURE`, and the readback that follows reads but never re-sends

#### Scenario: Through the real ZHA cover entity
- **WHEN** `cover.close_cover` is called on the real ZHA cover entity and every frame is lost
- **THEN** the service call raises ZHA's standard `HomeAssistantError` (`Failed to close cover: …`), and no state the cover publishes is `opening` or `closing`

#### Scenario: Lost acknowledgements
- **WHEN** both frames reach the motor but their replies are lost
- **THEN** the command returns FAILURE, and the readback shows the position the shade travelled to

### Requirement: Commands go out as ZHA sends them
The motor scales positions between the limits set with its remote and stops every Zigbee movement at them. `go_to_lift_percentage(100)` and raw `down_close` stop at the remote-set lower limit, which the shade then reports as lift 100 (#54; Part 1 §3a). U SHALL therefore send `up_open` (0x00), `down_close` (0x01) and `go_to_lift_percentage` (0x05), with a lift given positionally or as `percentage_lift_value=`, unchanged: the same command ID and the same lift ZHA's cover sends. There is no scaling, no substitution and no closed limit of U's own. U SHALL NOT use the released vendor quirk's swap of `up_open` and `down_close`: raw `down_close` lowers these units (#34) and raw `up_open` raised the Office Shade (#51; Part 1 §3c). Delivery's target lift SHALL be 0 for `up_open`, 100 for `down_close` and the command's lift for a go-to. A go-to without a valid lift (none, or outside 0-100) SHALL be sent once, unverified, with no target. U SHALL NOT alter a lift to correct a command ID or a command ID to correct a lift (F18).

#### Scenario: Open, close and a position as ZHA sends them
- **WHEN** `up_open`, `down_close` and `go_to_lift_percentage(37)` (positional and keyword) are commanded
- **THEN** the frames are `up_open` with no payload, `down_close` with no payload and `go_to_lift_percentage` with lift 37, and no other movement frame is sent

#### Scenario: Close stops at the remote's lower limit
- **WHEN** in the real-ZHA harness `cover.close_cover` is called and the simulated motor runs to its lower limit
- **THEN** the wire carried raw `down_close` (0x01), the shade reports lift 100, and the `cover.*` state is closed with position 0

#### Scenario: The slider reaches every position
- **WHEN** in the real-ZHA harness `cover.set_cover_position` is called with 0, 50 and 100
- **THEN** the frames are `go_to_lift_percentage` 100, 50 and 0, and the cover ends at each position

#### Scenario: No inverted lift
- **WHEN** `go_to_lift_percentage(10)` is commanded
- **THEN** the frame carries lift 10, not 90

### Requirement: Stop is passed through once, never synthesised, and its second reply is not an error
U SHALL send `stop` (0x02) exactly once, unchanged: no lock, no re-send, no tracking hook; the only read that follows is the one `STOP_SETTLE_S` later when the shade does not report where it halted ("Commands without a target lift pass through once"). It SHALL NOT synthesise a stop from a position read or a go-to (Part 3 §2l, F16). Stop SHALL drop a pending re-send of the previous movement (#51). The motor halts on a standard Stop (#51; Part 1 §3d). The radio answers it SUCCESS and then UNSUP_CLUSTER_COMMAND (0x81) with one TSN, and zigpy returns whichever arrives first (firmware analysis §3). For a standard Stop, U SHALL report a Default Response UNSUP_CLUSTER_COMMAND as `Status.SUCCESS`, as for a movement, so that ZHA's cover takes its stock success path (`zha/application/platforms/cover/__init__.py:733-735`). Any other reply or exception SHALL reach the caller unchanged. A manufacturer-specific Stop, which the radio refuses with a genuine 0x81 and does not forward (firmware analysis §2), SHALL be passed through with its reply unchanged.

#### Scenario: Stop is sent once
- **WHEN** `stop` is commanded
- **THEN** exactly one `stop` frame is sent, and no go-to follows it

#### Scenario: Stop under the double reply
- **WHEN** the motor sends the double reply in either order, or only the 0x81, and Stop is sent
- **THEN** exactly one frame is sent and the caller receives `Status.SUCCESS`

#### Scenario: Stop through the real ZHA cover entity
- **WHEN** in the real-ZHA harness a go-to is travelling, `cover.stop_cover` is called, and the motor answers with the double reply in either order or with the 0x81 alone
- **THEN** the call raises nothing, one Stop frame is sent, the motor halts, and the cover shows where it halted once the shade reports

#### Scenario: A manufacturer-specific Stop's refusal is not hidden
- **WHEN** Stop is commanded with a manufacturer code
- **THEN** one frame is sent and the radio's UNSUP_CLUSTER_COMMAND reaches the caller

### Requirement: U is one v2 quirk with a quirk ID and the vendor battery reading
U SHALL be registered as a single quirks v2 quirk (`zhaquirks.builder.QuirkBuilder`) for "Smartwings" / "WM25/L-Z". It SHALL replace the WindowCovering cluster with its own and keep the released vendor quirk's doubled battery percentage (`DoublingPowerConfigurationCluster`). It SHALL declare the quirk ID `smartwings.wm25lz` with `exposes_feature()`, which ZHA puts in the device's `exposes_features`. It SHALL add no cluster and no entity. The quirk ID is the only thing the integration reads to identify U (`integration-core`). It changes no ZHA discovery, since no ZHA entity match names it.

The doubling is the correct conversion, and SHALL be kept while the motor's byte is whole percent (issue #45). That unit is inferred, not measured. The radio copies the motor's battery byte into BatteryPercentageRemaining unchanged (firmware analysis §6), and the Office Shade's cached 168 under the doubling means the radio sent 84. ZCL counts that attribute in half percent (200 = 100 %). `DoublingPowerConfigurationCluster` doubles every value read or reported, so 84 is cached as 168, and ZHA's battery sensor shows half the cached value (`zha/application/platforms/sensor/__init__.py:800-806`), 84 %. Home Assistant therefore shows the motor's own percentage; without the doubling it would show half of it. zigpy restores the cache without doubling it again. `POWER-BATTERY-UNITS` confirms the unit with a raw read.

#### Scenario: The v2 quirk wins over the vendor quirk
- **WHEN** U is supplied through `custom_quirks_path` and Home Assistant starts
- **THEN** the shade's WindowCovering cluster is U's, its endpoints have no cluster beyond the device's own, and ZHA's device lists `smartwings.wm25lz` in `exposes_features`

#### Scenario: Battery percentage matches the vendor quirk
- **WHEN** the shade reports `battery_percentage_remaining` = 42
- **THEN** the battery entity shows the same value the released vendor quirk shows for that report

#### Scenario: The battery shows the motor's whole percent
- **WHEN** with U loaded the shade reports `battery_percentage_remaining` = 84, or 100
- **THEN** the cached value is 168, or 200, and the battery entity shows 84 %, or 100 %

#### Scenario: No extra entity
- **WHEN** Home Assistant starts with U supplied
- **THEN** the shade's ZHA device has no `number` entity

