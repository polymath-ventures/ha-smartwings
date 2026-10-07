## REMOVED Requirements

### Requirement: Coordinate spaces are named and converted in one module
**Reason**: U no longer converts positions. With no closed limit there is no scaled lift, and ZHA's own `100 - lift` is the only conversion between HA position and ZCL lift (#54).
**Migration**: `command-delivery`, "Commands go out as ZHA sends them"; `position-readback`, "Tracking reads through the read retry and caches what the shade sent".

### Requirement: Close and positions honour the closed limit
**Reason**: The motor stops `down_close` and `go_to_lift_percentage(100)` at the lower limit set with its remote (#54, Part 1 §3a reversed), so U bounds nothing.
**Migration**: `command-delivery`, "Commands go out as ZHA sends them". `go_to_lift_value` stays refused under "Commands the radio mangles are refused unsent".

### Requirement: Every open is an absolute go-to 0
**Reason**: Raw `up_open` raised the Office Shade to the top (#51), and both forms end at the upper limit set with the remote. The run-to-limit stall that motivated the go-to was seen on one unit on one day (Part 1 §3b) and was never reproduced. Stock ZHA sends `up_open` (design D1).
**Migration**: `command-delivery`, "Commands go out as ZHA sends them". The slider at 100 % is still a go-to 0.

### Requirement: Stock behaviour when no closed limit is set
**Reason**: There is no "set" state any more. The unswapped close it required, and the refusals, now hold always.
**Migration**: `command-delivery`, "Commands go out as ZHA sends them" and "Commands the radio mangles are refused unsent".

### Requirement: The displayed position is scaled to the closed limit
**Reason**: The shade reports lift 100 at its remote-set lower limit (#54), so the unscaled position already reads "closed" there.
**Migration**: `position-readback`, "Tracking reads through the read retry and caches what the shade sent". Unknown lifts (255) stay out of the cache.

### Requirement: Changing or clearing the closed limit rescales at once
**Reason**: There is no closed limit to change.
**Migration**: None.

### Requirement: Stop is passed through and never synthesised
**Reason**: Moved to `command-delivery`, now that Stop is known to halt the motor (#51) and its second reply is reported as SUCCESS.
**Migration**: `command-delivery`, "Stop is passed through once, never synthesised, and its second reply is not an error".

### Requirement: Lift values and command IDs are corrected independently
**Reason**: U corrects neither: commands and lifts go out as ZHA sends them (F18 holds trivially).
**Migration**: `command-delivery`, "Commands go out as ZHA sends them".

### Requirement: A failure to read the closed limit fails closed
**Reason**: There is no closed limit to read.
**Migration**: None.

### Requirement: Translated commands are delivered through the delivery layer
**Reason**: Commands are no longer translated. Movement delivery under the shade's lock, the baseline and the tracking hooks are already `command-delivery`'s requirements.
**Migration**: `command-delivery`, "Commands are serialised per shade without deadlock and independently across shades", "Delivery exposes tracking hooks around every movement command" and "A movement is sent once and returns with the radio's answer".

### Requirement: U is one v2 quirk that keeps the vendor quirk's behaviour
**Reason**: Moved to `command-delivery`, without the closed-limit cluster and with U's quirk ID.
**Migration**: `command-delivery`, "U is one v2 quirk with a quirk ID and the vendor battery reading".
