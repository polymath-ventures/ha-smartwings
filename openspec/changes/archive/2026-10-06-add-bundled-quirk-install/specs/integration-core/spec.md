## MODIFIED Requirements

### Requirement: Missing-quirk Repairs issue
While U is not active for one or more tracked shades, the integration SHALL maintain exactly one Repairs issue in Home Assistant's issue registry, with a fixed issue id and translation key `quirk_not_loaded`, not fixable, severity ERROR (the stop is not in force now), and its text in `strings.json` under `issues`. This is the stock Home Assistant mechanism for asking the user to fix their setup (owner decision 2026-10-06: match stock Home Assistant). It SHALL name each affected shade by its device name (the user's name if set), followed by its IEEE. It SHALL state that those shades' stops are not in force and that a close runs to the bottom of travel. It SHALL state the remedy: install the SmartWings quirk through ZHA's `custom_quirks_path`, then restart. It SHALL update the issue only when the affected set or its text changes (including a shade's rename), SHALL delete it when the set becomes empty and when the entry is unloaded or removed, SHALL reconcile it with every completed discovery (an empty one included, so no issue or inactive issue record outlives the last affected shade), and SHALL log the affected set once per change at WARNING (Part 3 §2m, §3f, F12). While the integration's `restart_required` issue stands (bundled-quirk-install), the integration has just installed or updated the quirk and nothing is wrong yet: it SHALL withhold this issue, deleting it if raised, and SHALL NOT log the WARNING. It SHALL first evaluate the issue at entry setup after the first quirk-file reconciliation, and again after every reconciliation, so that the issue appears, with its WARNING, once the restart request is gone and U is still not active.

#### Scenario: Setup order with only the integration
- **WHEN** a real Home Assistant with real ZHA, whose YAML has no `custom_quirks_path` (so the integration cannot supply U), restarts with only the integration installed and one WM25/L-Z in zigpy's database
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

#### Scenario: Restart request pending
- **WHEN** the integration has just installed the quirk file and `restart_required` stands, and U is not active
- **THEN** this issue is not raised and nothing is logged at WARNING

#### Scenario: Restart request gone, quirk still missing
- **WHEN** `restart_required` is withdrawn while U is still not active for a tracked shade
- **THEN** this issue is raised naming that shade, and the WARNING is logged once
