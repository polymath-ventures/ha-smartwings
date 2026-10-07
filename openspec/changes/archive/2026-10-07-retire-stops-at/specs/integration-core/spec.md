## ADDED Requirements

### Requirement: Quirk activity is decided by U's quirk ID
The integration SHALL decide that U is active for a shade if and only if the ZHA device that ZHA's gateway holds for it now lists U's quirk ID, `smartwings.wm25lz`, in its `exposes_features`. ZHA fills that set from the quirk it applied: a v1 quirk's `quirk_id` and a v2 quirk's declared features (`zha/zigbee/device.py:427-431`; `zhaquirks/builder/device.py:50-51`). The integration SHALL NOT use any Python class name, module path, cluster, cluster class name or quirk source file to make this decision (Part 3 §1c, REV 7c). It SHALL re-evaluate against the device ZHA holds at every discovery run, and SHALL NOT hold device references across a ZHA reload. An unexpected error SHALL propagate rather than be caught by a catch-all handler. No failure SHALL yield "active" (F13).

#### Scenario: Released vendor quirk loaded
- **WHEN** ZHA resolved a shade with the released `zhaquirks.smartwings.wm25lz` quirk
- **THEN** U is not active for that shade

#### Scenario: U loaded
- **WHEN** ZHA resolved a shade with U from `custom_quirks_path`
- **THEN** U is active for that shade

#### Scenario: A quirk without the ID
- **WHEN** ZHA resolved a shade with a v2 quirk for the WM25/L-Z that replaces the WindowCovering cluster with U's class but declares no quirk ID
- **THEN** U is not active for that shade

#### Scenario: The ID under any name
- **WHEN** U's classes and module are renamed but it still declares `smartwings.wm25lz`
- **THEN** U is active for that shade

### Requirement: The quirk ID is mirrored without a code dependency on U
The integration SHALL hold its own copy of U's quirk ID. It SHALL NOT import U's module at runtime. A test SHALL fail if the copy differs from the ID U declares in this repository.

#### Scenario: Quirk ID drift
- **WHEN** U's quirk ID changes in this repository and the integration's copy does not
- **THEN** the mirror test fails

#### Scenario: No runtime import of U
- **WHEN** the integration is set up
- **THEN** no module of U and no `zhaquirks` quirk module is imported by the integration, and nothing is added to `zhaquirks.legacy.PENDING_LEGACY_QUIRKS` or ZHA's quirk registry by it

## MODIFIED Requirements

### Requirement: Shade discovery through ZHA
The integration SHALL treat as a shade every device in ZHA's gateway whose zigpy manufacturer is `Smartwings` and model is `WM25/L-Z`, and only those. For each shade it SHALL record the IEEE, the Home Assistant device registry entry that ZHA owns, the device's display name, and whether U is active. It SHALL NOT create a device or an entity of its own. It SHALL re-run discovery at entry setup and whenever ZHA signals that it has (re)built its entities (`SIGNAL_ADD_ENTITIES`). It SHALL stop tracking a shade whose device is removed from the device registry. It SHALL notify its listeners (the installer and the missing-quirk issue) after every completed discovery and every change to the shades or to ZHA's availability.

#### Scenario: Shades and other devices
- **WHEN** ZHA's database holds one WM25/L-Z and one non-SmartWings device, and the entry is set up
- **THEN** exactly one shade is tracked, linked to the WM25/L-Z's existing ZHA device entry, and the device registry contains no new device

#### Scenario: Shade paired after setup
- **WHEN** a new WM25/L-Z joins and ZHA signals that it has added entities
- **THEN** the new shade is tracked without reloading the `smartwings` entry

#### Scenario: Shade removed
- **WHEN** a tracked shade's device is removed from ZHA
- **THEN** the shade is no longer tracked, and it no longer appears in the missing-quirk Repairs issue

#### Scenario: U appears after ZHA reload
- **WHEN** U becomes the loaded quirk for a shade and ZHA signals that it has rebuilt its entities
- **THEN** U is active for that shade, without reloading the `smartwings` entry

#### Scenario: ZHA mid-reload
- **WHEN** ZHA's gateway is unavailable because ZHA is reloading
- **THEN** the shades are kept, ZHA is recorded as unavailable, and no shade is reported as missing its quirk until discovery runs against the rebuilt gateway

### Requirement: Missing-quirk Repairs issue
While U is not active for one or more tracked shades, the integration SHALL maintain exactly one Repairs issue in Home Assistant's issue registry. The issue has a fixed issue id and translation key, `quirk_not_loaded`, is not fixable, and has severity ERROR, because the shade misbehaves now. Its text is in `strings.json` under `issues`. This is the stock Home Assistant mechanism for asking the user to fix their setup (owner decision 2026-10-06: match stock Home Assistant). The issue SHALL name each affected shade by its device name (the user's name if set), followed by its IEEE. It SHALL state what those shades lose: ZHA uses the released quirk, which swaps the Open and Close commands for these shades, sends each command once, and can show an error for a command that worked. It SHALL state the remedy: install the SmartWings quirk through ZHA's `custom_quirks_path`, then restart.

The integration SHALL update the issue only when the affected set or its text changes (including a shade's rename). It SHALL delete the issue when the set becomes empty and when the entry is unloaded or removed. It SHALL reconcile the issue with every completed discovery, an empty one included, so no issue or inactive issue record outlives the last affected shade. It SHALL log the affected set once per change at WARNING (Part 3 §2m, §3f, F12). While the integration's `restart_required` issue stands (bundled-quirk-install), the integration has just installed or updated the quirk and nothing is wrong yet: it SHALL withhold this issue, deleting it if raised, and SHALL NOT log the WARNING. It SHALL first evaluate the issue at entry setup after the first quirk-file reconciliation, and again after every reconciliation, so that the issue appears, with its WARNING, once the restart request is gone and U is still not active.

#### Scenario: Setup order with only the integration
- **WHEN** a real Home Assistant with real ZHA, whose YAML has no `custom_quirks_path` (so the integration cannot supply U), restarts with only the integration installed and one WM25/L-Z in zigpy's database
- **THEN** exactly one Repairs issue exists, and it names that shade and the `custom_quirks_path` remedy (Part 3 §5b item 1)

#### Scenario: Setup order with U in custom_quirks_path
- **WHEN** a real Home Assistant with real ZHA restarts with U supplied through `custom_quirks_path`
- **THEN** no missing-quirk Repairs issue exists and U is active for the shade

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

#### Scenario: Restart request pending
- **WHEN** the integration has just installed the quirk file and `restart_required` stands, and U is not active
- **THEN** this issue is not raised and nothing is logged at WARNING

#### Scenario: Restart request gone, quirk still missing
- **WHEN** `restart_required` is withdrawn while U is still not active for a tracked shade
- **THEN** this issue is raised naming that shade, and the WARNING is logged once

## REMOVED Requirements

### Requirement: Quirk activity is decided only by the data contract
**Reason**: The 0xFC01 contract is gone with "Stops at" (#54).
**Migration**: "Quirk activity is decided by U's quirk ID".

### Requirement: The contract terms are mirrored without a code dependency on U
**Reason**: The only term left is the quirk ID.
**Migration**: "The quirk ID is mirrored without a code dependency on U".

### Requirement: Per-shade status is published and no control exists without U
**Reason**: Nothing consumes a per-shade status signal now that the control, the dialog and the actions are gone. No control exists with or without U.
**Migration**: "Shade discovery through ZHA" (listeners, ZHA availability) and "Missing-quirk Repairs issue".
