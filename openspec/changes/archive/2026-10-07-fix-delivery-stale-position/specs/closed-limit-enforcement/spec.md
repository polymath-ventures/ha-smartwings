## MODIFIED Requirements

### Requirement: Translated commands are delivered through the delivery layer

U SHALL translate every command that can move the shade (`up_open`, `down_close`,
`go_to_lift_percentage`) exactly once, while holding `command-delivery`'s
per-shade lock, so the closed limit that shapes its frame is the one in force when it is sent;
a command queued behind another is translated only when its turn comes. The translated
`WireCommand(command_id, args, target_lift)` carries `target_lift` in raw lift and is sent
under that lock, and judged afterwards by `position-readback`; one with no target (a
`go_to_lift_percentage` without a valid lift, with no closed limit set) is sent once,
unverified, still under the lock. A movement's single re-send after its travel time
(`command-delivery`) SHALL NOT go out once the closed limit has been set, changed or cleared
since the frame was translated. `stop` and
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

#### Scenario: A stop set after a frame was sent drops its re-send
- **WHEN** a go-to is sent with no limit set, the motor ignores it, and the limit is set before its travel time is over
- **THEN** the go-to is not re-sent

#### Scenario: Baseline stays raw under rescaling
- **WHEN** the limit is 14, a read returned raw lift 84 (cache holds scaled 100), and a go-to command is issued
- **THEN** `_cached_lift_raw()` returns 84 to delivery, not 100

#### Scenario: End to end through the real ZHA cover entity
- **WHEN** in the real-ZHA harness the closed limit is set to 14, `cover.close_cover` is called on the real cover entity, and the simulated motor reports arrival at raw lift 84
- **THEN** the wire carried `go_to_lift_percentage(84)`, and the `cover.*` state is closed with position 0
