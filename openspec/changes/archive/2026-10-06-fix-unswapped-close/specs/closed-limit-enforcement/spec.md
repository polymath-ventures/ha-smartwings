## MODIFIED Requirements

### Requirement: Stock behaviour when no closed limit is set

With no closed limit set, U SHALL send every close (`down_close`, 0x01) as `down_close`
unchanged, with no payload, so that it runs to the end of travel. Raw `down_close` is known to
lower these units (Part 1 §3c: the box's v18 quirk sends it unswapped with no closed limit in
force, and closes from Home Assistant work; issue #34), while the released vendor quirk's swap
sends a close as `up_open` (0x00), whose direction on these units is unobserved; that swap
SHALL NOT be used. For every command other than an open (which
follows "Every open is an absolute go-to 0") and a close, U SHALL send exactly the frame the
released vendor quirk (`zhaquirks.smartwings.wm25lz`, zha-quirks 2.3.x) sends. U SHALL NOT
change the direction or end point of any command in this state; it MAY add the delivery
verification and re-sends of `command-delivery` (Part 3 §3a, §2e). An absent closed limit SHALL
never be replaced by a default (F15).

#### Scenario: Close with no stop is an unswapped down_close
- **WHEN** no closed limit is set and `down_close` is commanded
- **THEN** every movement frame sent is `down_close` (command ID 0x01) with no payload, and no `up_open` frame is sent

#### Scenario: Positions with no stop pass through unchanged
- **WHEN** no closed limit is set and `go_to_lift_percentage(37)` is commanded
- **THEN** the frame is `go_to_lift_percentage` with lift 37, identical to the released quirk's

#### Scenario: Out-of-range stored value behaves as unset
- **WHEN** the stored closed limit is outside the contract's valid range
- **THEN** a close is `down_close`, an open is `go_to_lift_percentage(0)`, every other frame is identical to the released quirk's, and the displayed position is the raw lift

### Requirement: Lift values and command IDs are corrected independently

U SHALL never alter a lift value to compensate for a command-ID behaviour, and never alter a
command ID to compensate for a lift-value behaviour. The only command-ID substitution is the
translation of commands into `go_to_lift_percentage`; the only lift-value transform is
`LiftScale` (Part 3 F18).

#### Scenario: No inverted lift in the unset state
- **WHEN** no closed limit is set and `go_to_lift_percentage(10)` is commanded
- **THEN** the frame carries lift 10, not 90

#### Scenario: No run-to-limit frame in the set state
- **WHEN** a closed limit is set and any of `up_open`, `down_close` or `go_to_lift_percentage` is commanded
- **THEN** every frame sent is `go_to_lift_percentage`
