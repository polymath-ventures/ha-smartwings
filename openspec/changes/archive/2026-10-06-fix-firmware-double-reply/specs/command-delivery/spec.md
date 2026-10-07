## ADDED Requirements

### Requirement: The firmware's second reply to a movement is not a failure
The radio answers every Window Covering command it handles with two Default Responses carrying the same TSN, SUCCESS and then UNSUP_CLUSTER_COMMAND (0x81), and zigpy returns whichever arrives first (firmware analysis §3; session A, 2026-10-06). For an open, close or go-to, all of which go out as standard frames that the radio forwards to the motor (see "Commands the radio mangles are refused unsent" for manufacturer-specific ones), the quirk SHALL treat a Default Response UNSUP_CLUSTER_COMMAND to the frame as an answer to that frame: it SHALL NOT count it as a failure and SHALL NOT re-send because of it, and the command SHALL report it as `Status.SUCCESS`, so that ZHA's cover takes its stock success path (it raises on any other status: `zha/application/platforms/cover/__init__.py:637-640`, `:663-666`, `:692-697`). Neither reply carries the motor's state. The replies SHALL NOT decide a verified movement: it SHALL succeed, with a reply ZHA reads as SUCCESS, when travel toward the target is seen, and SHALL fail through ZHA's standard path when it is not, whatever the replies said. The blind path ("Commands that cannot be verified are sent at least twice") and a go-to without a valid lift read no position: their SUCCESS reports the radio's acceptance of a frame, not movement, exactly as before this mapping, and SHALL be documented as unverified. Every frame those paths send is `go_to_lift_percentage` or `down_close`, which the radio handles and answers SUCCESS then 0x81, so the mapping applies to them as to any open, close or go-to. Stop is excluded (see "Commands without a target lift pass through once").

#### Scenario: A verified movement whichever reply wins
- **WHEN** the shade has a baseline, the motor sends the double reply in either order, and an open, close or go-to is commanded
- **THEN** exactly one frame is sent, travel is seen, and the command returns a Default Response with `Status.SUCCESS`

#### Scenario: A blind movement whichever reply wins
- **WHEN** the shade has no baseline, the motor sends the double reply in either order, and an open, close or go-to is commanded
- **THEN** two identical frames are sent and the command returns a Default Response with `Status.SUCCESS`

#### Scenario: Through the real ZHA cover entity
- **WHEN** in the real-ZHA harness the motor sends UNSUP_CLUSTER_COMMAND before SUCCESS and `cover.open_cover`, `cover.close_cover` or `cover.set_cover_position` is called
- **THEN** the service call raises nothing, one frame is sent when a baseline exists (two when none does), and the cover shows `opening` or `closing`

#### Scenario: A lone 0x81 on the blind path reports acceptance, not movement
- **WHEN** the shade has no baseline, the SUCCESS reply is lost so only the 0x81 arrives, the motor does not move, and a go-to is commanded
- **THEN** two identical frames are sent, no position is read, and the command returns a Default Response with `Status.SUCCESS`, which the code documents as the radio's acceptance of a frame, not movement

#### Scenario: No travel still fails
- **WHEN** the motor sends SUCCESS first but never moves
- **THEN** the command returns a Default Response with `Status.FAILURE`

### Requirement: Commands the radio mangles are refused unsent
The radio turns `go_to_lift_value` (0x04), `go_to_tilt_value` (0x07) and `go_to_tilt_percentage` (0x08) into malformed serial frames that can repeat the previous command or corrupt the next (firmware analysis §3 note 3), and refuses every manufacturer-specific Window Covering frame with a genuine 0x81 without forwarding it (firmware analysis §2), so a manufacturer-specific `up_open`, `down_close` or `go_to_lift_percentage` can never take effect. The quirk SHALL never send any of these, whatever path they come by (a cluster method, `command()`, or a raw `request()`), with or without a closed limit set. It SHALL answer each with the Default Response a device gives for a command it does not support, `Status.UNSUP_CLUSTER_COMMAND` with the command's ID, which ZHA reports as for any unsupported command (its cluster-command service raises `Failed to issue cluster command with status: …`, `zha/zigbee/device.py:1485-1487`). A refusal SHALL NOT wait for or take the shade's lock, cancel or start tracking, or change the baseline. A manufacturer-specific Stop is not refused: it keeps Stop's pass-through, and the radio's 0x81 reaches the caller unchanged.

#### Scenario: Refused through the cluster
- **WHEN** `go_to_lift_value`, `go_to_tilt_value` or `go_to_tilt_percentage` is called on the cluster, with or without a closed limit, while another command holds the shade
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

## MODIFIED Requirements

### Requirement: Commands without a target lift pass through once
A command that the caller hands to delivery without a target lift (Stop, and any command other than open, close or go-to-lift that is not refused under "Commands the radio mangles are refused unsent") SHALL be sent exactly once, unverified. Its reply or exception SHALL be returned unchanged (§2l; §5a item 5). For Stop this includes the firmware's double reply: whichever reply zigpy matched first reaches the caller, so ZHA's cover shows no error when SUCCESS wins and raises `Failed to stop cover: <Status.UNSUP_CLUSTER_COMMAND: 129>` when the 0x81 wins (`cover/__init__.py:733-735`). Stop's user-facing behaviour is left so until `STOP-WHILE-MOVING` decides it.

#### Scenario: Stop rejected by the device
- **WHEN** Stop is sent and the device answers UNSUP_CLUSTER_COMMAND
- **THEN** exactly one frame is sent, no position read follows, and the device's status reaches the caller

#### Scenario: Stop under the double reply
- **WHEN** the motor sends the double reply and Stop is sent
- **THEN** exactly one frame is sent, and the caller receives SUCCESS when SUCCESS arrived first and UNSUP_CLUSTER_COMMAND when the 0x81 did

#### Scenario: What Home Assistant shows for Stop today
- **WHEN** in the real-ZHA harness `cover.stop_cover` is called with the motor sending the double reply
- **THEN** the call raises nothing when SUCCESS arrives first, and raises `Failed to stop cover: <Status.UNSUP_CLUSTER_COMMAND: 129>` when the 0x81 does
