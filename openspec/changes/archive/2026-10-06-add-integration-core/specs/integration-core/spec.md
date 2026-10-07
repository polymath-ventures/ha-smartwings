## ADDED Requirements

### Requirement: Single config entry depending on ZHA
The integration SHALL use the domain `smartwings`, SHALL allow at most one config entry, and SHALL declare `zha` as a manifest dependency. The config flow SHALL abort with a translated reason when a `smartwings` entry already exists or when no ZHA config entry is set up. Every user-facing string SHALL exist in `strings.json`, and `translations/en.json` SHALL equal it.

#### Scenario: First setup
- **WHEN** the user adds the SmartWings integration while ZHA is set up and no `smartwings` entry exists
- **THEN** exactly one `smartwings` config entry is created, with no options to fill in

#### Scenario: Second setup attempt
- **WHEN** the user tries to add SmartWings while a `smartwings` entry already exists
- **THEN** Home Assistant aborts the flow with its own translated `single_instance_allowed` reason (`single_config_entry` in the manifest) and no second entry exists

#### Scenario: ZHA absent
- **WHEN** the user tries to add SmartWings and no ZHA config entry is set up
- **THEN** the flow aborts with a translated reason saying ZHA must be set up first

#### Scenario: ZHA not ready at entry setup
- **WHEN** the `smartwings` entry is set up while ZHA's gateway is not available
- **THEN** setup raises `ConfigEntryNotReady`, so Home Assistant retries, and no shade is reported as missing its quirk

#### Scenario: Translations in sync
- **WHEN** the test suite runs
- **THEN** a test fails if `translations/en.json` differs from `strings.json`

### Requirement: Shade discovery through ZHA
The integration SHALL treat as a shade every device in ZHA's gateway whose zigpy manufacturer is `Smartwings` and model is `WM25/L-Z`, and only those. For each shade it SHALL record the IEEE, the Home Assistant device registry entry that ZHA owns, and the entity id of that device's `cover` entity. It SHALL NOT create a device of its own for a shade. It SHALL re-run discovery at entry setup and whenever ZHA signals that it has (re)built its entities (`SIGNAL_ADD_ENTITIES`). It SHALL stop tracking a shade whose device is removed from the device registry.

#### Scenario: Shades and other devices
- **WHEN** ZHA's database holds one WM25/L-Z and one non-SmartWings device, and the entry is set up
- **THEN** exactly one shade is tracked, linked to the WM25/L-Z's existing ZHA device entry and its `cover.*` entity id, and the device registry contains no new device

#### Scenario: Shade paired after setup
- **WHEN** a new WM25/L-Z joins and ZHA signals that it has added entities
- **THEN** the new shade is tracked without reloading the `smartwings` entry

#### Scenario: Shade removed
- **WHEN** a tracked shade's device is removed from ZHA
- **THEN** the shade is no longer tracked, and it no longer appears in the missing-quirk Repairs issue

### Requirement: Quirk activity is decided only by the data contract
The integration SHALL decide that U is active for a shade if and only if endpoint 1 of the shade's live device carries an in-cluster with id `0xFC01` that declares attribute `0x0000` exactly as the `closed-limit-contract` capability defines it: type `uint8` and manufacturer code `0x1002` (ADR 0001). It SHALL NOT use any Python class name, module path, cluster class name or quirk registry entry to make this decision (Part 3 §1c, REV 7c). It SHALL re-evaluate against the device's current cluster objects at every discovery run and SHALL NOT hold cluster references across a ZHA reload. Missing or malformed device structure SHALL yield "not active". An unexpected error SHALL propagate rather than be caught by a catch-all handler, as the `closed-limit-contract` capability requires. No failure SHALL yield "active" (F13).

#### Scenario: Released vendor quirk loaded
- **WHEN** ZHA resolved a shade with the released `zhaquirks.smartwings.wm25lz` quirk
- **THEN** U is not active for that shade

#### Scenario: U loaded
- **WHEN** ZHA resolved a shade with U
- **THEN** U is active for that shade

#### Scenario: Class name without contract
- **WHEN** a shade's WindowCovering cluster class is named like an earlier handler (for example `ReadbackWindowCoveringCluster`) but no `0xFC01` cluster declares the contract attribute
- **THEN** U is not active for that shade

#### Scenario: Contract attribute under a different Python name
- **WHEN** a shade's `0xFC01` cluster declares the contract attribute ID, type and manufacturer code under a different attribute name than #7 uses
- **THEN** U is active for that shade

#### Scenario: Same ID, wrong type
- **WHEN** a shade's `0xFC01` cluster declares attribute `0x0000` with a different type or without manufacturer code `0x1002`
- **THEN** U is not active for that shade

#### Scenario: Unsupported mark does not change the decision
- **WHEN** zigpy has marked the contract attribute unsupported after an over-the-air reply
- **THEN** U is still active for that shade, because the decision reads the declaration, not the cached value (F10)

#### Scenario: Malformed device data
- **WHEN** the shade's device has no endpoint 1, no cluster `0xFC01`, no attribute definitions, or a definition that is not an attribute definition
- **THEN** U is not active for that shade, and nothing is raised

#### Scenario: Evaluation raises unexpectedly
- **WHEN** looking up a shade's endpoints, clusters or attribute definitions raises an unexpected exception
- **THEN** the exception propagates; it is not caught and turned into "active" or "not active"

### Requirement: The contract terms are mirrored without a code dependency on U
The integration SHALL hold its own copy of the closed-limit contract terms: endpoint, cluster, attribute ID, type, manufacturer code, coordinate space, `CLOSED_LIMIT_MIN`, `CLOSED_LIMIT_MAX` and the unset representation. It SHALL NOT import U's module at runtime. A test SHALL fail if any mirrored term differs from the terms in U's source in this repository.

#### Scenario: Contract drift
- **WHEN** U's contract attribute ID, type, range or unset representation changes in this repository and the integration's mirror does not
- **THEN** the contract-mirror test fails

#### Scenario: No runtime import of U
- **WHEN** the integration is set up
- **THEN** no module of U and no `zhaquirks` quirk module is imported by the integration, and nothing is added to `zhaquirks.legacy.PENDING_LEGACY_QUIRKS` or ZHA's quirk registry by it

### Requirement: Per-shade status is published and no control exists without U
The integration SHALL publish, for each tracked shade, whether U is active, and SHALL notify subscribers when that changes. It SHALL create no per-shade entity of its own. Because ZHA creates the "Stops at" control only from U, a shade without U SHALL have no "Stops at" control at all, and the integration's dialog and actions SHALL refuse it, so the user never sees a stop that is not in force (Part 3 §2m as revised by ADR 0001).

#### Scenario: U absent after restart
- **WHEN** Home Assistant restarts with only the integration installed (U not in `custom_quirks_path` and not in zha-quirks)
- **THEN** the shade's status is not active and the shade has no "Stops at" control

#### Scenario: U appears after ZHA reload
- **WHEN** U becomes the loaded quirk for a shade and ZHA signals that it has rebuilt its entities
- **THEN** that shade's status changes to active and ZHA's "Stops at" control exists, without reloading the `smartwings` entry

#### Scenario: ZHA mid-reload
- **WHEN** ZHA's gateway is unavailable because ZHA is reloading
- **THEN** the shade's status is gateway-unavailable, and no shade is reported as missing its quirk until discovery runs against the rebuilt gateway

### Requirement: Missing-quirk Repairs issue
While U is not active for one or more tracked shades, the integration SHALL maintain exactly one Repairs issue in Home Assistant's issue registry, with a fixed issue id and translation key `quirk_not_loaded`, not fixable, severity ERROR (the stop is not in force now), and its text in `strings.json` under `issues`. This is the stock Home Assistant mechanism for asking the user to fix their setup (owner decision 2026-10-06: match stock Home Assistant). It SHALL name each affected shade by its device name (the user's name if set), followed by its IEEE. It SHALL state that those shades' stops are not in force and that a close runs to the bottom of travel. It SHALL state the remedy: install the SmartWings quirk through ZHA's `custom_quirks_path`, then restart. It SHALL update the issue only when the affected set or its text changes (including a shade's rename), SHALL delete it when the set becomes empty and when the entry is unloaded or removed, SHALL reconcile it with every completed discovery (an empty one included, so no issue or inactive issue record outlives the last affected shade), and SHALL log the affected set once per change at WARNING (Part 3 §2m, §3f, F12).

#### Scenario: Setup order with only the integration
- **WHEN** a real Home Assistant with real ZHA restarts with only the integration installed and one WM25/L-Z in zigpy's database
- **THEN** exactly one Repairs issue exists, it names that shade and the `custom_quirks_path` remedy, and the shade has no "Stops at" control (Part 3 §5b item 1)

#### Scenario: Setup order with U in custom_quirks_path
- **WHEN** a real Home Assistant with real ZHA restarts with U supplied through `custom_quirks_path`
- **THEN** no missing-quirk Repairs issue exists and the shade's status is active

#### Scenario: Set shrinks
- **WHEN** two shades are named in the issue and one of them stops being affected (it is removed from ZHA, or U becomes active for it)
- **THEN** the issue names only the other shade

#### Scenario: Shade renamed
- **WHEN** the user renames an affected shade's device
- **THEN** the issue names it by its new name, without a rediscovery; a rename that leaves the text unchanged changes nothing

#### Scenario: Set empties
- **WHEN** U becomes active for every tracked shade
- **THEN** the issue is deleted

#### Scenario: Last shade gone while ZHA is down
- **WHEN** the only affected shade is removed while ZHA is not loaded, and ZHA then loads with no shades
- **THEN** the issue is deleted once discovery runs against the rebuilt gateway

#### Scenario: No repeat on unchanged set
- **WHEN** discovery runs again and the affected set is unchanged
- **THEN** the issue is not changed and no new WARNING is logged

### Requirement: Unload and teardown
Unloading the `smartwings` entry SHALL disconnect every listener the integration registered, stop tracking every shade, and delete the missing-quirk Repairs issue. Unloading SHALL NOT change any ZHA device, entity, or quirk state.

#### Scenario: Entry unloaded
- **WHEN** the `smartwings` entry is unloaded while the issue is raised
- **THEN** the issue is deleted, a later ZHA rebuild signal triggers no SmartWings discovery, and the shade's ZHA cover entity is unaffected

#### Scenario: Reload of the entry
- **WHEN** the `smartwings` entry is reloaded
- **THEN** discovery and status are rebuilt from ZHA's current state with no duplicate listeners or Repairs issues

### Requirement: No dependence on the old install
The integration SHALL NOT read, write, adopt or migrate any artifact of the previous SmartWings install: `input_number.smartwings_*_closed_position` helpers, `automation.smartwings_*`, `script.smartwings_*` or `smartwings_calibration.json`. Its behaviour SHALL be identical whether or not those artifacts exist (Part 3 §3i).

#### Scenario: Leftover helpers present
- **WHEN** the integration is set up in a Home Assistant that still has the old `input_number.smartwings_*_closed_position` helpers and `smartwings_calibration.json`
- **THEN** discovery, status and the Repairs issue are the same as without them, and neither artifact is read or modified
