## ADDED Requirements

### Requirement: Capture stores the shade's live raw position as its closed limit
The integration SHALL provide the action `smartwings.capture_closed_limit`, which targets exactly one cover entity belonging to a SmartWings WM25/L-Z under ZHA. The action SHALL read the motor's current lift percentage (ZCL attribute 0x0102/0x0008) live over the air, bypassing zigpy's attribute cache. It SHALL NOT use the cover entity's `current_position`, which is rescaled when a closed limit is set (Part 3 §2h-1). It SHALL convert the reading to raw Home Assistant cover-position space (0 = mechanically closed, 100 = open) with the plain ZCL→HA inversion, stored = 100 − raw lift, held in exactly one integration function (F1). It SHALL NOT use, import or mirror the quirk's rescaling, and the integration SHALL NOT import quirk code. It SHALL store the result as the shade's closed limit through the change operation shared with `stops-at-control` (zigpy's `cluster.update_attribute` on cluster `0xFC01`, attribute `0x0000`) and then refresh ZHA's "Stops at" control, so the control shows the new value at once (Part 3 §2c, §3e, ADR 0001).

#### Scenario: Shade at its remote-set stop
- **WHEN** the shade sits stationary where its remote left it, the motor answers lift 84, and the user runs `smartwings.capture_closed_limit` on that cover
- **THEN** the shade's closed limit is stored as 16 in raw HA position space, and the "Stops at" control shows 16

#### Scenario: Cached value differs from the motor
- **WHEN** zigpy's cache holds lift 0 for the shade, the motor answers a live read with lift 84, and capture runs
- **THEN** the stored closed limit is 16, taken from the live read and not from the cache

#### Scenario: Cover already rescaled by an existing stop
- **WHEN** the shade has a closed limit of 20, so its cover entity reports a rescaled `current_position`, the motor answers lift 84, and capture runs
- **THEN** the stored closed limit is 16, derived from the raw lift and not from the cover entity's scaled position

### Requirement: Capture reports the stored value only after a store
The action SHALL report success only after the store path returns without raising (F8): after the write, and after ZHA's control was seen to show it. On success it SHALL return an action response containing the cover's entity id and the stored closed limit, and ZHA's "Stops at" control SHALL show the stored value (Part 3 §2c). Like stock Home Assistant actions, it SHALL report only through its response and SHALL create no persistent notification (owner decision, 2026-10-06).

#### Scenario: Successful capture is reported
- **WHEN** capture stores 16
- **THEN** the action response contains the entity id and 16, the "Stops at" control shows 16, and no persistent notification is created


### Requirement: Capture requires the shade to be stationary
The action SHALL take two live position reads separated by a fixed settle interval. It SHALL proceed only when both are readable and equal. Unequal readings SHALL fail the action with a "shade is still moving" reason telling the user to wait until it stops and capture again, and nothing is stored.

#### Scenario: Shade still travelling
- **WHEN** the first live read returns lift 70 and the second returns lift 76
- **THEN** the action raises `HomeAssistantError` saying the shade is still moving, and the stored closed limit is unchanged

#### Scenario: Shade stationary
- **WHEN** both live reads return lift 84
- **THEN** the action proceeds to validation and store with lift 84

### Requirement: Every capture failure is visible and stores nothing
The action SHALL raise `HomeAssistantError` (or its subclass `ServiceValidationError` for a bad target or request) whose message names the cover or shade and states the reason, and SHALL leave the stored closed limit unchanged, in each of these cases (Part 3 §2c, F8):
- the target is not an existing cover entity;
- the cover does not belong to a WM25/L-Z device under ZHA;
- ZHA is not running;
- the SmartWings quirk is not active for that shade, as determined by the integration core through the closed-limit contract (Part 3 §2m);
- a live read fails or returns no usable value (no record, an error status, or 255 "unknown") after the read-retry policy;
- the shade is still moving;
- the converted value is outside the contract's valid range (F7);
- another writer (the Change-stop dialog, a clear, an owed clear) changed the stored stop after capture first looked at it: capture writes only if the stop is still the one it saw (compare-and-set, under the store's per-shade write lock);
- ZHA's "Stops at" control is no longer in the entity registry (removed) when capture would write: a stop would then be in force where nothing shows it (Part 3 §2f, F9), and any clear owed for the removal stays owed. A disabled control does not refuse a capture; the stop is stored and #12's Repairs issue names it;
- the integration's config entry was unloaded or removed while capture waited (its write is refused, so it cannot put back a stop the removal cleared, F9);
- the store path raises.

The one exception is the shared store's refresh check: if the write landed but ZHA's "Stops at" control does not show the new value, the action fails with the store's standard error, which says the closed limit **is stored** but the control could not be refreshed (as for every store write, `stops-at-control`).

An unexpected exception raised inside any check SHALL fail the action with that exception, never let it proceed; it is not caught and relabelled (no catch-all handler). An unreadable-position failure SHALL tell the user to try again and, if the shade stays unresponsive, to move it with its remote first (Part 1 §3h).

#### Scenario: Not a SmartWings shade
- **WHEN** capture targets a ZHA cover whose device is not manufacturer "Smartwings", model "WM25/L-Z"
- **THEN** the action raises `HomeAssistantError` saying the cover is not a WM25/L-Z, and no store occurs

#### Scenario: Quirk not active
- **WHEN** capture targets a WM25/L-Z whose loaded quirk does not honour the closed-limit contract
- **THEN** the action raises `HomeAssistantError` naming the shade and the `custom_quirks_path` remedy, and no store occurs

#### Scenario: Position unreadable
- **WHEN** every live read attempt for the shade times out
- **THEN** the action raises `HomeAssistantError` saying the position could not be read and suggesting a retry, or moving the shade with its remote if it stays unresponsive, and no store occurs

#### Scenario: Motor reports unknown position
- **WHEN** the live read returns lift 255
- **THEN** the action raises `HomeAssistantError` saying the position is unknown, and no store occurs

#### Scenario: Value outside the honoured range
- **WHEN** the converted raw HA position is outside the contract's minimum and maximum
- **THEN** the action raises `HomeAssistantError` stating the value and the valid range, and no store occurs

#### Scenario: Store fails
- **WHEN** the store path raises an exception
- **THEN** the action raises `HomeAssistantError` naming the shade, and the previously stored closed limit is unchanged

#### Scenario: Control removed during the capture
- **WHEN** the shade stops at 14, its "Stops at" control is removed while capture waits between its reads, and the clear owed for the removal fails
- **THEN** the action raises `HomeAssistantError` naming the shade and the missing control, the stop is still 14, and the clear is still owed

#### Scenario: Stop changed by another writer during the capture
- **WHEN** the user confirms Configure → Change stop 14 → 20 while capture waits between its reads
- **THEN** the dialog stores 20, capture raises `HomeAssistantError` naming the shade and saying the stop changed meanwhile, and the stop is 20

#### Scenario: Control does not follow the write
- **WHEN** capture writes 16 over 14 but ZHA's control keeps showing 14 after the refresh
- **THEN** the action raises the store's error naming the shade and saying the closed limit is stored, and the stored stop is 16

#### Scenario: A check itself errors
- **WHEN** the quirk-active check raises an unexpected exception
- **THEN** the action fails with that exception, nothing is read, and no store occurs

### Requirement: Capture over an existing stop requires explicit replacement
When the shade already has a closed limit, the action SHALL refuse unless it is called with `replace_existing: true`. The refusal SHALL raise `HomeAssistantError` naming the shade and its current closed limit and pointing to the `replace_existing` field and the integration's Configure → Change stop dialog; it SHALL read nothing and store nothing. With `replace_existing: true` the action SHALL proceed and report the new value (owner decision, 2026-10-05).

#### Scenario: Capture refuses to overwrite silently
- **WHEN** the shade stops at 14 and capture runs without `replace_existing`
- **THEN** the action raises an error naming the shade, the value 14, `replace_existing` and Change stop, no read is sent, and the stop is still 14

#### Scenario: Explicit replacement
- **WHEN** the shade stops at 14, the motor answers lift 80, and capture runs with `replace_existing: true`
- **THEN** the stop is stored as 20, and the action response and the "Stops at" control show 20

#### Scenario: First capture needs no flag
- **WHEN** the shade has no stop and capture runs without `replace_existing`
- **THEN** capture proceeds normally

### Requirement: Capture sends no movement commands
Capture SHALL send only attribute reads to the motor. It SHALL never send a WindowCovering command.

#### Scenario: Frames on the wire during capture
- **WHEN** a successful capture runs in the harness
- **THEN** the captured frames contain only Read Attributes requests for 0x0102/0x0008 and no WindowCovering cluster command

### Requirement: Clear removes the closed limit and restores stock behaviour
The integration SHALL provide the action `smartwings.clear_closed_limit`, which targets exactly one cover entity belonging to a WM25/L-Z under ZHA. It SHALL remove that shade's closed limit through the clear operation shared with `stops-at-control` (zigpy's `update_attribute(attr, None)`, which also deletes the database row), leaving the contract's unset state, and SHALL then refresh ZHA's "Stops at" control. Afterwards the shade SHALL behave exactly as if no closed limit had ever been set (Part 3 §2d, §3a). Clear SHALL send nothing over the air. It SHALL be idempotent: clearing a shade with no closed limit succeeds and changes nothing. Like every store write, a clear whose write landed but whose control does not show `unknown` fails with the store's error saying the stop was cleared (stored) but the control could not be refreshed. When ZHA is not running, or the quirk is not active for the shade, there is no closed-limit cluster to clear: clear SHALL fail with `HomeAssistantError` naming the shade (and, for the quirk, the `custom_quirks_path` remedy), as the shared clear operation does. Clear and capture SHALL run one at a time per shade.

#### Scenario: Clear then close
- **WHEN** a shade has closed limit 16, the user runs `smartwings.clear_closed_limit` on its cover, then calls `cover.close_cover`
- **THEN** the stored closed limit is unset, the "Stops at" control shows no value, and the close frame is byte-identical to the released vendor quirk's

#### Scenario: Clear with nothing set
- **WHEN** clear runs on a shade with no closed limit
- **THEN** the action succeeds, the stop stays unset, and no frame is sent

#### Scenario: Clear on a non-SmartWings cover
- **WHEN** clear targets a cover that is not a WM25/L-Z
- **THEN** the action raises `HomeAssistantError`, and nothing changes

#### Scenario: Clear during a capture
- **WHEN** clear is called while a capture of the same shade is in flight
- **THEN** clear runs after the capture finishes, and the shade ends with no closed limit

#### Scenario: Clear store fails
- **WHEN** the store path raises during clear
- **THEN** the action raises `HomeAssistantError` naming the shade

#### Scenario: Clear with the quirk inactive
- **WHEN** clear targets a WM25/L-Z whose loaded quirk is the stock vendor quirk
- **THEN** the action raises `HomeAssistantError` naming the shade and the `custom_quirks_path` remedy, and sends no frame

### Requirement: Actions are described in protocol vocabulary
The actions SHALL be registered when the integration is set up (`async_setup`), as Home Assistant expects, and fail with `ServiceValidationError` while the integration's entry is not loaded. `services.yaml`, `strings.json` and `translations/en.json` SHALL describe both actions using the protocol term "closed limit", with the human label "Stops at". They SHALL contain no fleet-specific text and no coined terms (Part 3 §3h). The cover field SHALL use an entity selector restricted to the `cover` domain of the `zha` integration.

#### Scenario: Action metadata
- **WHEN** Home Assistant loads the integration
- **THEN** both actions are registered with a translated name and description, and each has one required cover field
