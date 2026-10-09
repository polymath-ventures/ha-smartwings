# How the WM25/L-Z behaves over Zigbee

Notes for Home Assistant and zha-device-handlers developers on how SmartWings WM25/L-Z roller-shade motors actually behave, and how this project's quirk deals with each behaviour. The measurements come from nine installed shades in one house, most of the detailed ones from a single shade. The firmware findings come from a flash dump of one radio module; see [firmware-analysis.md](evidence/firmware-analysis.md).

## Two chips

Each shade has two processors. The Zigbee radio is a Silicon Labs EFR32MG21 running EmberZNet 6.9.1. It talks to a separate motor controller over a 9600-baud serial link (`LEN CMD DATA… XOR`, not Tuya's MCU protocol). The radio is mostly a translator: it turns a few ZCL commands into serial frames, and turns the motor's position and battery messages into attribute values. Everything about limits, direction and timing lives in the motor controller, whose firmware we don't have.

## Identity

| Field | Value |
|---|---|
| Manufacturer / model | `Smartwings` / `WM25/L-Z` |
| Manufacturer code | 0x1002 (the Silicon Labs SDK default) |
| Node type | End device, receiver off when idle; polls its parent about once a second |
| Endpoint 1 | Profile 0x0104, device type 0x0202 (Window Covering) |
| Server clusters | 0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102 |
| Client clusters | 0x0003, 0x0019 (OTA) |
| OTA image | Image type 0, file version 2 |

Groups, Scenes and Identify have attribute tables but no command handlers: every command to them is answered 0x81. The shade can't join a group.

No manufacturer-specific attributes, commands or clusters exist, either in discovery or in the firmware.

## What the attributes claim

| Attribute | Value | What it really means |
|---|---|---|
| `config_status` (0x0007) | 3 | Operational and online, open-loop lift, no reversal. Compiled in; nothing ever changes it. |
| `installed_open_limit_lift` (0x0010) | 0 | Spec default. Not the real limit. |
| `installed_closed_limit_lift` (0x0011) | 65535 | Spec default. Not the real limit. |
| `window_covering_mode` (0x0017) | 0x14 | Compiled default. Writable, but a write is kept in RAM only, nothing reads it, and it reverts at restart. |
| `current_position_lift_percentage` (0x0008) | 0–100 | Real, but see "Position" below. |

So the hub can't learn the limits or the direction from these attributes, and can't change anything by writing them.

## Every command gets two replies

The radio answers each Window Covering command it handles with a Default Response SUCCESS, then a second Default Response, UNSUP_CLUSTER_COMMAND (0x81), with the same TSN. It's a firmware bug: each handler sends its own SUCCESS and then tells the framework the command wasn't handled. With Disable Default Response set, only the 0x81 is sent.

zigpy keeps whichever reply arrives first. Usually that's SUCCESS, but sometimes the 0x81 wins, and ZHA's cover then raises "Failed to …" even though the shade moves. It has been seen on Stop, and other users report it on open and close when commanding many shades at once.

Neither reply says anything about the motor. The radio sends SUCCESS before it writes the serial frame, writes it once, and never hears back from the motor.

**Quirk:** for a standard open, close, go-to or Stop, a 0x81 means the radio took the frame, so the quirk reports SUCCESS to ZHA.

## Commands

| Command | What the radio does |
|---|---|
| 0x00 Up/Open | Forwards it. Raises the shade. |
| 0x01 Down/Close | Forwards it. Lowers the shade. |
| 0x02 Stop | Forwards it. The motor halts. |
| 0x05 Go to Lift Percentage | Forwards the percentage byte unchanged, with no range check. |
| 0x04 Go to Lift Value, 0x07 / 0x08 tilt | Sends a malformed serial frame built from leftover buffer bytes. It can repeat the previous command or corrupt the next one. |
| 0x03, 0x06, any manufacturer-specific command | Rejected with 0x81. Nothing is forwarded. |

Discovery lists 0x00, 0x01, 0x02, 0x04, 0x05, 0x07 and 0x08 as supported, tilt included, even though the shade is lift-only.

Sending the same go-to twice moves the shade once.

**Quirk:** sends open, close and go-to exactly as ZHA does. Refuses 0x04, 0x07, 0x08 and manufacturer-specific moves before anything is sent, with UNSUP_CLUSTER_COMMAND.

## Direction, and the released quirk's swap

On these shades, `up_open` raises and `down_close` lowers, as the spec says. The quirk for this model in zha-quirks swaps the two, which is wrong for these units.

A SmartWings setup guide is reported to include a step that reverses open and close. If a motor ever were reversed that way, the hub couldn't tell: the radio never sets the reversal bits and receives no direction from the motor.

**Quirk:** no swap.

## Limits

Top and bottom limits are programmed with the SmartWings 433 MHz remote and stored in the motor. The motor enforces them for Zigbee commands as well as for the remote. Lift percentages map between them: 0 is the top limit, 100 the bottom limit, 50 halfway.

The hub can neither read nor set the limits. The limit attributes hold spec defaults, nothing on the serial link carries a limit, and no command or writable attribute sets one. The calibration bit in `window_covering_mode` does nothing.

**Quirk:** nothing to do. A shade that stops in the wrong place is fixed with its remote.

## Position

ZCL lift runs from 0 (open) to 100 (closed). Home Assistant's position is the other way round, and ZHA converts with `100 - lift`. The shades follow the ZCL convention.

The motor sends its position to the radio only when travel ends: at its target, where it stalls, or after a Stop. Two things follow.

1. **A read during travel returns the position from before the move.** In one measured go-to from 0 to 50, every read for 15 s returned 0; from 18 s on they returned 50, with nothing in between.
2. **The shade reports its position when travel ends.** The radio pushes a Report Attributes for 0x0008 straight to the coordinator, whatever bindings exist. ZHA picks it up like any other report.

Configure Reporting and Read Reporting Configuration are both rejected with 0x81, so ZHA's reporting setup at pairing never takes. The end-of-travel report is the radio's own.

Not yet confirmed: whether a move made with the remote produces the same end-of-travel report.

**Quirk:** after each move it waits for the end-of-travel report. If none comes, it reads the position once the shade should have arrived. There is no polling.

## The first command after idle is sometimes ignored

Sometimes a shade does nothing after accepting a command, and the same command sent again works. Reads can be lost the same way. How often this happens isn't known: the early counts were taken with reads during travel, which can't see movement.

The cause isn't known either. The radio polls its parent every second, so a frame shouldn't sit long on the Zigbee side. One plausible explanation is that the motor controller is asleep and misses the serial frame, which the radio never retries. That is unproven.

**Quirk:** if the shade hasn't moved toward the target by the time it should have arrived, the quirk re-sends the same command once. A frame or read lost on the air is retried once.

## Stop

The motor halts on a standard Stop, measured twice. Only the reply is wrong (the double reply above). The shade reports where it halted shortly after.

A "go to where you are now" substitute doesn't work, because a read during travel is stale. It just becomes another move.

**Quirk:** sends Stop as-is, reports SUCCESS, cancels any pending re-send, waits 3 s for the shade's report, and reads the position once if none comes.

## Battery

The radio copies the motor's battery byte into `battery_percentage_remaining` (0x0021) unchanged. That byte appears to be whole percent, while ZCL expects half-percent units. `battery_voltage` (0x0020) is never set.

**Quirk:** keeps the released quirk's doubling, so Home Assistant shows the right percentage.

## Timings

| Quantity | Value |
|---|---|
| Attribute read, when answered | 0.8–1.9 s |
| Full travel | 30–70 s |
| End-of-travel report, short moves | 2.5–6 s after the command |

## Other things seen once

1. One shade stalled partway on `open` three times, while a go-to to the top worked first time. Its sibling shades opened normally.
2. One shade kept answering reads but ignored repeated identical moves. A small move in the opposite direction freed it, and the next command then took about 100 s to start.

Neither has been reproduced or explained.

## What a radio firmware fix could do

1. One correct reply per command.
2. Accept Configure Reporting.
3. Fix or remove the 0x04, 0x07 and 0x08 handlers.
4. Report battery in half-percent units.

The shade has an OTA client, so a fixed image could be delivered through ZHA without removing any shade.

Two things would need a different motor, not new radio firmware. The motor sends nothing while it travels, so the position can't be reported mid-move. And it tells the radio nothing when its limits are set or its direction is reversed with the remote, so neither can be put into `installed_*_limit_lift` or `config_status`. SmartWings' support has reportedly confirmed that the motor reports its position only when it stops.
