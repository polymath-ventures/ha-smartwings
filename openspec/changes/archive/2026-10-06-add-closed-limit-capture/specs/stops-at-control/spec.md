## ADDED Requirements

### Requirement: Writes of a stop are serialised per shade and compare-and-set
Every write of a shade's closed limit by the integration (the Change-stop dialog, capture, clear, the removal sweep and owed clears) SHALL run under one per-shade write lock held by the shared store operations, so no two writes of the same shade interleave. A writer that decided on the stop it saw SHALL pass that stop to the store, which under the lock SHALL refuse with Home Assistant's standard error naming the shade, and write nothing, when the stored stop has changed since. The Change-stop dialog SHALL pass the stop it showed; an owed clear SHALL pass the stop it is owed for. When that clear is refused because the stored stop is no longer the one owed (a write through the integration cancelled the debt, or another write changed the stop), the debt SHALL be dropped and logged at DEBUG, as a discovery drops it; only a failed write SHALL keep the debt and log an ERROR. Every write SHALL also be refused, under the lock, once the integration's config entry is neither loaded nor setting up (unloaded or removed while the writer waited), except the clears of the removal sweep itself.

#### Scenario: A change waits for a write in flight and finds the stop changed
- **WHEN** the dialog confirms 14 → 20 while another writer holds the shade's write lock and stores 16
- **THEN** the dialog's write runs after it, finds 16 instead of 14, stores nothing and fails, and the stop is 16

#### Scenario: An owed clear finding another stop is dropped
- **WHEN** a clear owed for 14 waits on the write lock while something outside the integration writes 30
- **THEN** the clear writes nothing, the debt is dropped, 30 stays, and nothing is logged above DEBUG

#### Scenario: No write after the integration is removed
- **WHEN** the integration is removed while a capture waits between its reads, with ZHA still running
- **THEN** the removal sweep clears the stops, the capture's write is refused naming the shade, and no stop is put back

#### Scenario: An owed clear does not undo a later write
- **WHEN** a clear owed for 14 is waiting while a capture through the integration stores 16
- **THEN** the debt is cancelled, the owed clear finds 16, clears nothing, and logs nothing above DEBUG

### Requirement: A change refuses while the control is missing
The store's change operation SHALL, under the shade's write lock and before writing, refuse with Home Assistant's standard error naming the shade, and write nothing, when ZHA's "Stops at" control for the shade is not in the entity registry (removed, or not created) while its closed-limit cluster is reachable: a stop would then be in force where nothing shows it (Part 3 §2f, F9). Every writer that sets a stop (the Change-stop dialog, capture) SHALL go through this check. A disabled control SHALL NOT refuse a change; the disabled-control Repairs issue names the stop then. A clear SHALL NOT be refused for a missing control, since clearing removes the stop.

#### Scenario: The dialog cannot change a stop whose control is gone
- **WHEN** the shade stops at 14, its control was removed and the clear owed for it failed, and the user confirms 14 → 20 in Configure
- **THEN** the dialog aborts with an error naming the shade and the missing "Stops at" control, the stop stays 14, and the clear stays owed

#### Scenario: A clear needs no control
- **WHEN** the shade's control was removed and its stop is cleared through the store
- **THEN** the clear succeeds and the stop is unset

## MODIFIED Requirements

### Requirement: No stop outlives the integration or its visible control
Removing the integration SHALL clear the stop on every shade with U active (F9). If ZHA's "Stops at" control for a shade is removed from the entity registry while a stop is set, the integration SHALL clear the stop. When the clear cannot be made at once (ZHA not loaded, U not active, or the write fails), the integration SHALL record the owed clear by the shade's IEEE in its own Home Assistant store, with the stored value it is owed for (or "not known" when ZHA could not be read), SHALL apply it at the next discovery that reaches the shade's closed-limit cluster, and SHALL drop it once the stop is confirmed cleared, when no value is stored, when the stored value differs from the one owed, when the shade is no longer in ZHA, or when the integration is removed. Any write of a stop through the integration SHALL cancel the shade's owed clear. A change of a stop SHALL be refused while the shade's control is missing from the entity registry (see "A change refuses while the control is missing"), so only a clear, or a change once ZHA has recreated the control, can cancel a debt. Saves of the owed clears SHALL be finished before the integration's removal deletes the store. A "not known" debt is safe: while ZHA is down nothing can write the stop, and the debt is applied by the discovery that brings ZHA back and recreates the control, so no direct write on ZHA's control can come between. If it is disabled while a stop is set, the integration SHALL keep the stop and raise a Repairs issue for that shade (Home Assistant's issue registry, not fixable, severity WARNING, as #11's `quirk_not_loaded` issue does; owner decision 2026-10-06: match stock Home Assistant) naming the shade and the value, until the control is re-enabled or the stop is cleared (Part 3 §2f).

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
- **WHEN** a clear of 14 is owed, ZHA has recreated the control but the clear failed again, and the user then changes the stop to 20 through Configure
- **THEN** the owed clear is cancelled and the stop stays 20 after the next discovery

#### Scenario: A change while the control is missing keeps the debt
- **WHEN** a clear of 14 is owed because the control was removed, and the user confirms a change to 20 through Configure
- **THEN** the dialog aborts with the store's error naming the shade and the missing control, the stop stays 14, and the next discovery clears it

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
