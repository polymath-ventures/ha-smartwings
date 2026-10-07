## ADDED Requirements

### Requirement: Exactly one "Stops at" control per shade, and it is ZHA's
The integration SHALL create no `number` entity. Each WM25/L-Z shade with U loaded SHALL have exactly one "Stops at" control: the one ZHA creates from U on the shade's own device, with entity id `number.<shade>_stops_at` (Part 3 §1c, §3d; ADR 0001).

#### Scenario: One control on the shade's device
- **WHEN** Home Assistant starts with U in `custom_quirks_path` and the integration set up (harness #5)
- **THEN** the shade's device has exactly one closed-limit `number` entity, it belongs to ZHA, and no extra device exists in the registry

#### Scenario: Two shades have independent controls
- **WHEN** two shades are paired and a stop of 14 is set on one
- **THEN** the other shade's control stays `unknown` and its closes are unaffected (Part 3 §2a)

### Requirement: The control shows the raw closed limit honestly
The control SHALL show the stored closed limit in raw HA cover-position space (percent of full travel), which is the value capture stores, not the rescaled cover-slider value; unset SHALL show `unknown` (ADR 0001 decision 3, owner decision 2026-10-05).

#### Scenario: Stored value is shown as stored
- **WHEN** a stop of 14 is set and the cover rests at the stop
- **THEN** the control shows 14 while the cover reports position 0

#### Scenario: Unset shows no number
- **WHEN** a shade has no stop
- **THEN** the control's state is `unknown`

### Requirement: Changing a set stop goes through a confirmed dialog
Once a stop is set, a change SHALL require confirmation (owner decision, 2026-10-05). ZHA's control SHALL accept a first set and refuse a different value (U's rule, #7). The integration's options flow SHALL provide a "Change stop" dialog that lists shades with U active and a stop set, takes a new value bounded by `CLOSED_LIMIT_MIN..CLOSED_LIMIT_MAX`, shows "<shade>: <old> → <new>. Change it?", and on confirm writes the value through zigpy's public cluster API and refreshes the control. Cancel or abort SHALL write nothing.

#### Scenario: First set is accepted directly
- **WHEN** a shade has no stop and "Stops at" is set to 14 through `number.set_value`
- **THEN** the stop is 14 and no frame is sent

#### Scenario: A direct change of a set stop is refused
- **WHEN** the stop is 14 and "Stops at" is set to 20 through `number.set_value`
- **THEN** the call fails with an error and the stop stays 14

#### Scenario: The Change-stop dialog changes the stop on confirm
- **WHEN** the user opens Configure → Change stop, picks the shade, enters 20 and confirms
- **THEN** the stop is 20, the control shows 20, and the next close stops at the new stop

#### Scenario: Cancelling the dialog changes nothing
- **WHEN** the user enters 20 and cancels at the confirmation step
- **THEN** the stop stays 14 and nothing is written

#### Scenario: The dialog rejects out-of-range values
- **WHEN** the user enters 96 or -1 in the dialog
- **THEN** the dialog shows a range error naming `CLOSED_LIMIT_MIN` and `CLOSED_LIMIT_MAX` and nothing is written (Part 3 §2b, §5b item 7, F7)

#### Scenario: Shades without U are not offered
- **WHEN** a shade's quirk is not U
- **THEN** the dialog does not list it (Part 3 §2m)

### Requirement: Store operations are shared and follow every write with a refresh
The integration SHALL provide change, clear and refresh operations that resolve the shade's live closed-limit cluster (`0xFC01`, attribute `0x0000`) each time, use only zigpy's public cluster API, and raise an error naming the shade when the cluster is missing or the call fails (F8). Every change or clear SHALL be followed by a refresh of ZHA's control, because ZHA does not react to a clear (ADR 0001). Because Home Assistant's `homeassistant.update_entity` logs a failed entity update and returns normally, the operation SHALL then check that the control shows the stored value (`unknown` for none) and otherwise raise Home Assistant's standard error saying the stop was stored but the control could not be refreshed. Capture and clear (#13) SHALL use these operations.

#### Scenario: Clear is visible at once
- **WHEN** a stop of 14 is cleared through the clear operation
- **THEN** the control shows `unknown` without a restart and the next close is stock

#### Scenario: A failed store fails visibly
- **WHEN** the closed-limit cluster is missing or the write raises
- **THEN** the operation raises an error naming the shade and the previous stop is unchanged

#### Scenario: A refresh that does not take is reported
- **WHEN** a stop of 14 is cleared and refreshing ZHA's control leaves it showing 14
- **THEN** the operation raises an error naming the shade and saying the stop was stored but the control could not be refreshed

### Requirement: In force across restart and ZHA reload
A stop SHALL be in force before the first command after a full Home Assistant restart and after a ZHA config-entry reload, with no action by the integration (Part 3 §2f, §5b items 3 and 4).

#### Scenario: Restart keeps the stop
- **WHEN** the stop is 14 and Home Assistant restarts
- **THEN** the control shows 14 and the first `cover.close_cover` frame is the limited go-to

#### Scenario: ZHA reload keeps the stop
- **WHEN** the stop is 14 and ZHA's config entry is reloaded
- **THEN** the control shows 14 and the first `cover.close_cover` frame is the limited go-to

### Requirement: Clearing restores stock behaviour
After a clear, the shade SHALL behave exactly as if no stop had been set (Part 3 §2d, §5b item 6).

#### Scenario: Clear then close
- **WHEN** the stop is cleared and `cover.close_cover` is called
- **THEN** the frame is byte-identical to the released vendor quirk's close

### Requirement: No stop outlives the integration or its visible control
Removing the integration SHALL clear the stop on every shade with U active (F9). If ZHA's "Stops at" control for a shade is removed from the entity registry while a stop is set, the integration SHALL clear the stop. When the clear cannot be made at once (ZHA not loaded, U not active, or the write fails), the integration SHALL record the owed clear by the shade's IEEE in its own Home Assistant store, with the stored value it is owed for (or "not known" when ZHA could not be read), SHALL apply it at the next discovery that reaches the shade's closed-limit cluster, and SHALL drop it once the stop is confirmed cleared, when no value is stored, when the stored value differs from the one owed, when the shade is no longer in ZHA, or when the integration is removed. Any write of a stop through the integration SHALL cancel the shade's owed clear. Saves of the owed clears SHALL be finished before the integration's removal deletes the store. A "not known" debt is safe: while ZHA is down nothing can write the stop, and the debt is applied by the discovery that brings ZHA back and recreates the control, so no direct write on ZHA's control can come between. If it is disabled while a stop is set, the integration SHALL keep the stop and raise a Repairs issue for that shade (Home Assistant's issue registry, not fixable, severity WARNING, as #11's `quirk_not_loaded` issue does; owner decision 2026-10-06: match stock Home Assistant) naming the shade and the value, until the control is re-enabled or the stop is cleared (Part 3 §2f).

#### Scenario: Integration removed
- **WHEN** two shades have stops and the `smartwings` config entry is deleted
- **THEN** both stops are cleared, including after a restart with U loaded

#### Scenario: Control removed
- **WHEN** the stop is 14 and the shade's "Stops at" entity is removed from the entity registry
- **THEN** the stop is cleared and the next close is stock

#### Scenario: Control removed while ZHA is down
- **WHEN** the stop is 14, ZHA is not loaded, and the shade's "Stops at" entity is removed
- **THEN** the clear is kept across restarts and applied when ZHA is back, and the database row is gone after a restart

#### Scenario: A failed clear is retried
- **WHEN** the control is removed and the clear's write fails
- **THEN** the stop stays, the clear stays owed, and the next discovery clears it

#### Scenario: A later change is not undone by an owed clear
- **WHEN** a clear of 14 is owed and the user then changes the stop to 20 through Configure
- **THEN** the owed clear is cancelled and the stop stays 20 after the next discovery

#### Scenario: An owed clear clears only the stop it was owed for
- **WHEN** a clear of 14 is owed and the stored value is now 30
- **THEN** the next discovery leaves 30 and drops the owed clear

#### Scenario: Removal while an owed clear is being saved
- **WHEN** the integration is removed while a save of its owed clears is in flight
- **THEN** no store remains afterwards and adding the integration again replays nothing

#### Scenario: Known limit — integration removed while ZHA is down
- **WHEN** the `smartwings` config entry is deleted while ZHA is not loaded
- **THEN** no stop can be cleared (Home Assistant cannot refuse or defer a removal, and without ZHA there is no device to clear; writing zigpy's database directly is ruled out), the stops stay in force and shown while U is loaded, and one WARNING names ZHA and every registered shade. Part 3 §2f / F9 cannot be met in this case. A second accepted gap: if U itself is removed while a stop is set, zigpy keeps the database row, which is in force again if U is reinstalled

#### Scenario: Control disabled
- **WHEN** the stop is 14 and the shade's "Stops at" entity is disabled
- **THEN** the stop stays in force and one Repairs issue says the shade still stops at 14 and how to see, change or clear it

#### Scenario: Control re-enabled
- **WHEN** a disabled control is re-enabled
- **THEN** the Repairs issue for that shade is deleted

### Requirement: Stable entity id
The control's entity id SHALL be ZHA's, `number.<shade>_stops_at`, and the integration SHALL never rename it; a user-chosen id SHALL survive restarts (F11, ADR 0001 revising Part 3 §2b).

#### Scenario: New control id
- **WHEN** a shade is paired with U
- **THEN** its control's entity id ends in `_stops_at`

#### Scenario: User rename survives restart
- **WHEN** the user renames the control to `number.office_stop` and Home Assistant restarts
- **THEN** the id is still `number.office_stop`

### Requirement: No default creates a stop
Nothing in the integration SHALL write a stop except a confirmed change, a capture or an explicit clear (F15, Part 3 §2e).

#### Scenario: Fresh install
- **WHEN** the integration is installed on shades that never had a stop and Home Assistant restarts three times
- **THEN** every control shows `unknown` and nothing was written
