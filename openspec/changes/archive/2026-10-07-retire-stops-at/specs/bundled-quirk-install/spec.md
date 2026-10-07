## MODIFIED Requirements

### Requirement: Install and update when the quirk is not active
At entry setup, and each time ZHA's config entry becomes loaded again, the integration SHALL reconcile the target file, unless ZHA's quirk registry shows that Home Assistant's zha-quirks provides the quirk. U counts as active when at least one shade is tracked and U is active for every tracked shade, as integration-core decides from U's quirk ID. When the target file is absent and U is not active, the integration SHALL install the bundled file. When the target file is its own and outdated, it SHALL replace it with the bundled file, whether or not U is active. It SHALL NOT write the file when its own copy is current. It SHALL NOT reload ZHA.

#### Scenario: Fresh install
- **WHEN** the integration is set up with `custom_quirks_path` configured, no `wm25lz.py` in it, and U not active
- **THEN** `wm25lz.py` in that folder is byte-identical to the bundled file, `restart_required` is the only Repairs issue of the integration, nothing of the integration logs at WARNING, and ZHA's config entry is not reloaded

#### Scenario: Restart after a fresh install
- **WHEN** Home Assistant restarts after the integration installed the file
- **THEN** U is active for the shade, the file is not written again, and no Repairs issue of the integration is raised

#### Scenario: Own file outdated
- **WHEN** the target file is the integration's own but its bytes differ from the bundled file's, and the integration is set up
- **THEN** the file is replaced with the bundled file and `restart_required` is raised

#### Scenario: Own file current
- **WHEN** the target file is identical to the bundled file and U is active
- **THEN** the file is not written, and no install-related Repairs issue is raised

#### Scenario: U active from elsewhere
- **WHEN** no target file exists but U is active for every tracked shade
- **THEN** nothing is written and no install-related Repairs issue is raised

### Requirement: Stop updating once zha-quirks provides the quirk
The integration SHALL decide that Home Assistant's zha-quirks provides U if and only if ZHA's quirk registry holds an entry that applies to manufacturer `Smartwings` and model `WM25/L-Z` with no filter and no firmware-version bounds, whose source file is not inside the configured `custom_quirks_path`, and whose quirk definition declares U's quirk ID, `smartwings.wm25lz`, as an exposed feature (`entry.zha_device_factory.quirk_definition.exposes_features`; `zhaquirks/builder/device.py:140-150`). Anything missing on the way answers "not provided". The integration SHALL read this from the registry ZHA has already loaded. It SHALL NOT import or call quirk code, or use a class, module or cluster. When zha-quirks provides U, the integration SHALL NOT install, update or delete the file. While the target is its own file, it SHALL raise the `quirk_now_upstream` Repairs issue, translated, not fixable, not persistent, severity WARNING. That issue SHALL name the file and say that zha-quirks now ships the quirk, and that the user may delete the file and the `custom_quirks_path` line if nothing else uses them. The integration SHALL delete the issue when the file is no longer its own (the user deleted it), and when the entry is unloaded or removed.

#### Scenario: Upstream present, own file installed
- **WHEN** zha-quirks provides U and the target file is the integration's own, and the integration is set up
- **THEN** the file is unchanged, `quirk_now_upstream` is raised naming it, and no other Repairs issue of the integration is raised

#### Scenario: Upstream present, own file outdated
- **WHEN** zha-quirks provides U and the integration's own file is outdated
- **THEN** the file is not updated

#### Scenario: The user deletes the file
- **WHEN** the user then deletes the file and restarts Home Assistant
- **THEN** U is active for the shade from zha-quirks, no file is installed, and no Repairs issue of the integration is raised

#### Scenario: Upstream present, unmarked file
- **WHEN** zha-quirks provides U and the target file is not the integration's own
- **THEN** the file is unchanged and no install-related issue is raised

#### Scenario: Restricted upstream entry
- **WHEN** the only entry declaring the quirk ID from outside `custom_quirks_path` has a filter or firmware-version bounds
- **THEN** zha-quirks does not count as providing U: no `quirk_now_upstream` is raised and the integration's outdated file is updated

#### Scenario: Only the released vendor quirk in zha-quirks
- **WHEN** zha-quirks holds only the released vendor quirk for the WM25/L-Z, which declares no quirk ID
- **THEN** zha-quirks does not provide U, and the integration installs its file

#### Scenario: The integration's own quirk is not upstream
- **WHEN** the only registry entry that declares the quirk ID was loaded from `custom_quirks_path`
- **THEN** zha-quirks does not provide U, and the file stays
