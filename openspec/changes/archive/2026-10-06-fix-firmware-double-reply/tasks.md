## 1. Harness

- [x] 1.1 Failing tests: with `double_reply`, every Window Covering command the firmware handles draws SUCCESS and UNSUP_CLUSTER_COMMAND with the frame's TSN, in either order; IDs 3, 6 and unknown ones draw only the 0x81; zigpy returns the first.
- [x] 1.2 `MotorSim.double_reply` and `MotorSim.replies()`; the radio stub schedules every reply.

## 2. The second reply

- [x] 2.1 Failing tests (quirk and real ZHA): open, close and go-to, verified and blind, succeed with one frame per attempt whichever reply wins; a go-to without a valid lift too.
- [x] 2.2 `_movement_reply()` reports the 0x81 to a movement frame as SUCCESS; `_success()` returns SUCCESS whenever travel was seen.
- [x] 2.3 Stop: tests record what HA shows today for each order; behaviour unchanged.
- [x] 2.4 Failing tests, then the fix: a manufacturer-specific open, close or go-to is refused unsent on the verified, blind and targetless paths and on a raw request; a manufacturer-specific Stop passes through. The harness motor refuses manufacturer-specific frames with 0x81 alone, unacted on.

## 3. Mangled commands

- [x] 3.1 Failing tests: 0x04, 0x07 and 0x08 are refused with UNSUP_CLUSTER_COMMAND, no frame leaves, through the cluster, a raw request and ZHA's cluster-command service; no lock, hook or baseline change.
- [x] 3.2 `REFUSED_COMMANDS`, refused in `request()`; `go_to_lift_value` removed from the movement commands; superseded tests updated.

## 4. Battery

- [x] 4.1 End-to-end test: a whole-percent report of 84 shows 84 % (cached 168); the reasoning recorded in the proposal and the spec.

## 5. Docs

- [x] 5.1 Quirk docstrings; bundled copy regenerated.
- [x] 5.2 README Known limitations: Stop, refused commands.
