## MODIFIED Requirements

### Requirement: Close and positions honour the closed limit

With a closed limit set, U SHALL translate every movement command so that the raw lift sent
over the air never exceeds the close target `A`:
- `down_close` (0x01) SHALL be sent as `go_to_lift_percentage(A)`.
- `go_to_lift_percentage(p)`, with `p` given positionally or as `percentage_lift_value=`, SHALL
  be treated as scaled lift and sent as `go_to_lift_percentage(raw_lift(p))`; one without a
  valid lift SHALL be refused with an error naming the shade, because it cannot be bounded.
- `go_to_lift_value` (0x04) is never sent, with or without a closed limit: it is refused under
  `command-delivery`'s "Commands the radio mangles are refused unsent". Its units would be
  relative to installed limits the device reports as unset (Part 1 §2), so it could not be
  bounded either.
No caller (dashboard, voice, scene, script, automation, bridge, direct service call or ZHA's
cluster-management panel) SHALL be able to cause a frame that moves the shade past its stop
(Part 3 §1a-2, §2g).

#### Scenario: Close with a stop set
- **WHEN** the closed limit is 14 and `down_close` is commanded
- **THEN** exactly one movement frame per delivery attempt is `go_to_lift_percentage` with raw lift 84, and no `down_close` or `up_open` frame is sent

#### Scenario: Position at, above and below the old raw stop
- **WHEN** the closed limit is 14 and `go_to_lift_percentage` is commanded with scaled lift 0, 50, 99 and 100, each in positional and keyword form
- **THEN** the frames carry raw lift 0, 41, 81 and 84 respectively, and no frame exceeds raw lift 84

#### Scenario: A go-to without a valid lift with a stop set
- **WHEN** the closed limit is set and `go_to_lift_percentage` is commanded with lift 255 or with no lift
- **THEN** no frame is sent and the call raises an error naming the shade

#### Scenario: go_to_lift_value with a stop set
- **WHEN** the closed limit is set and `go_to_lift_value` is commanded
- **THEN** no frame is sent and the call returns a Default Response with `Status.UNSUP_CLUSTER_COMMAND`

#### Scenario: Open is unaffected by the stop
- **WHEN** the closed limit is 14 and the shade is commanded to any scaled lift
- **THEN** the shade can still reach raw lift 0 (fully open)

### Requirement: Stock behaviour when no closed limit is set

With no closed limit set, U SHALL send every close (`down_close`, 0x01) as `down_close`
unchanged, with no payload, so that it runs to the end of travel. Raw `down_close` is known to
lower these units (Part 1 §3c: the box's v18 quirk sends it unswapped with no closed limit in
force, and closes from Home Assistant work; issue #34), while the released vendor quirk's swap
sends a close as `up_open` (0x00), whose direction on these units is unobserved; that swap
SHALL NOT be used. For every command other than an open (which
follows "Every open is an absolute go-to 0"), a close, and the commands `command-delivery`
refuses unsent (`go_to_lift_value`, `go_to_tilt_value`, `go_to_tilt_percentage`, which the
radio turns into malformed serial frames), U SHALL send exactly the frame the
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

#### Scenario: Mangled commands with no stop
- **WHEN** no closed limit is set and `go_to_lift_value`, `go_to_tilt_value` or `go_to_tilt_percentage` is commanded
- **THEN** no frame is sent and the call returns a Default Response with `Status.UNSUP_CLUSTER_COMMAND`

### Requirement: Translated commands are delivered through the delivery layer

U SHALL translate every command that can move the shade (`up_open`, `down_close`,
`go_to_lift_percentage`) exactly once, while holding `command-delivery`'s
per-shade lock, so the closed limit that shapes its frame is the one in force when it is sent;
a command queued behind another is translated only when its turn comes. The translated
`WireCommand(command_id, args, target_lift)` carries `target_lift` in raw lift and is delivered
and verified under that lock; one with no target (a `go_to_lift_percentage` without a valid
lift, with no closed limit set) is sent once, unverified, still under the lock. `stop` and
every other command not refused unsent are translated and sent once, unverified, without
waiting for the lock. Every command that takes
the lock becomes the newest, so a command it waited behind does not start tracking afterwards.
`_cancel_tracking()` runs before the lock wait, so a movement then refused at translation
(a go-to without a valid lift with a closed limit set, which ZHA never sends) sends nothing and
starts no tracking, and the position shown stays as last read until the next refresh; this
cost is accepted so that a new command supersedes tracking at once. U SHALL provide delivery's
baseline by overriding `_cached_lift_raw()` to return the raw lift last received from the
device while `command-delivery` counts it as the baseline, and `None` otherwise, with or without
a closed limit set; no other baseline accessor SHALL exist.

#### Scenario: Close target reaches delivery in raw lift
- **WHEN** the limit is 14 and `down_close` is commanded
- **THEN** delivery receives `WireCommand(go_to_lift_percentage, (84,), 84)` with the shade's lock held

#### Scenario: A stop set while a command waits is honoured
- **WHEN** no limit is set, a `down_close` or a `go_to_lift_percentage(255)` is queued behind another command on the shade, and the limit is set to 14 before it gets the lock
- **THEN** the close is sent as `go_to_lift_percentage(84)` and the go-to is refused unsent

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

The doubling is the correct conversion, and SHALL be kept while the motor's byte is whole
percent (issue #45). That unit is inferred, not measured: the radio copies the motor's battery
byte into BatteryPercentageRemaining unchanged (firmware analysis §6), and the Office Shade's
cached 168 under the doubling means the radio sent 84; ZCL counts that attribute in half percent (200 = 100 %);
`DoublingPowerConfigurationCluster` doubles every value read or reported, so 84 is cached as
168; and ZHA's battery sensor shows half the cached value
(`zha/application/platforms/sensor/__init__.py:800-806`), 84 %. Home Assistant therefore shows
the motor's own percentage; without the doubling it would show half of it. zigpy restores the
cache without doubling it again. `POWER-BATTERY-UNITS` confirms the unit with a raw read.

#### Scenario: Battery percentage matches the vendor quirk
- **WHEN** the shade reports `battery_percentage_remaining` = 42
- **THEN** the battery entity shows the same value the released vendor quirk shows for that report

#### Scenario: The battery shows the motor's whole percent
- **WHEN** with U loaded the shade reports `battery_percentage_remaining` = 84, or 100
- **THEN** the cached value is 168, or 200, and the battery entity shows 84 %, or 100 %

#### Scenario: A cleared stop rescales without a write through the cluster
- **WHEN** the limit is 14, the cover shows scaled positions, and the stop is cleared with zigpy's `update_attribute(attr, None)`
- **THEN** the displayed position returns to the raw scale at once and no frame is sent

#### Scenario: The v2 quirk wins over the vendor quirk
- **WHEN** U is supplied through `custom_quirks_path` and Home Assistant starts
- **THEN** the shade's WindowCovering cluster is the enforcement subclass and the closed-limit cluster is present
