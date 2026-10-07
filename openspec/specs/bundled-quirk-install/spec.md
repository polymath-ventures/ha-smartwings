# bundled-quirk-install Specification

## Purpose
TBD - created by archiving change add-bundled-quirk-install. Update Purpose after archive.
## Requirements
### Requirement: The integration ships the quirk as a file it never imports
The integration SHALL include, at `custom_components/smartwings/bundled_quirk/wm25lz.py.txt`, a file byte-identical to `quirk/zhaquirks/smartwings/wm25lz.py`. It SHALL use that file only as bytes to copy. It SHALL NOT import it, execute it, or register anything from it in zigpy's or ZHA's quirk registries (Part 3 §1c). A test SHALL fail when the bundled file differs from the quirk source.

#### Scenario: Bundled copy drifts
- **WHEN** the quirk source changes and the bundled file is not updated to match
- **THEN** the packaging test fails

#### Scenario: Setup imports no quirk code
- **WHEN** the integration is set up and installs the quirk file
- **THEN** no module is created from the bundled file, and ZHA's quirk registry holds no entry the integration added

### Requirement: The quirk file carries the integration's marker
The first line of `quirk/zhaquirks/smartwings/wm25lz.py`, and so of the bundled file, SHALL be the comment `# Installed by the SmartWings integration for Home Assistant, which keeps this file up to date. Delete this line to keep the file as your own.` The integration SHALL treat a path as its own file if and only if the path itself (not a symbolic link's target) is a regular file whose first line equals that marker. It SHALL treat its own file as outdated if and only if its bytes differ from the bundled file's.

#### Scenario: Own file recognised
- **WHEN** the target is a regular file whose first line is the marker
- **THEN** the integration treats it as its own, whatever the rest of the file holds

#### Scenario: Marker elsewhere does not count
- **WHEN** a file contains the marker text on a line other than the first, or has a first line that differs from it in any character
- **THEN** the integration treats the file as not its own

#### Scenario: A link is never its own
- **WHEN** the target is a symbolic link, even to a file identical to the bundled one, or a broken link, or a directory
- **THEN** the integration treats it as not its own, and a broken link as present, not absent

### Requirement: The install target is ZHA's custom quirks folder
The integration SHALL read `custom_quirks_path` from ZHA's own YAML configuration as ZHA holds it at runtime, SHALL resolve a relative value as ZHA does (against the working directory, after `~` expansion), and SHALL use the resolved `<custom_quirks_path>/wm25lz.py` as the target file. It SHALL compare that resolved folder with quirks' absolute source files whenever it decides whether a quirk was loaded from it. While `custom_quirks_path` is not configured, the target SHALL be `wm25lz.py` in `<config dir>/custom_zha_quirks/`, and the integration SHALL create that folder if it does not exist. The integration SHALL NOT write or rename any other file, and SHALL NOT delete any file.

#### Scenario: Configured path
- **WHEN** ZHA's YAML sets `custom_quirks_path` to a folder and the integration installs the quirk
- **THEN** the file is written as `wm25lz.py` in that folder and nowhere else

#### Scenario: Relative path
- **WHEN** ZHA's YAML sets `custom_quirks_path: custom_zha_quirks`, Home Assistant runs from the config folder, and ZHA loaded the integration's own file from it
- **THEN** the integration recognises that file as its own: it updates it when outdated, and raises no `quirk_now_upstream`

#### Scenario: Unconfigured path
- **WHEN** ZHA's YAML has no `custom_quirks_path` and the integration installs the quirk
- **THEN** `<config dir>/custom_zha_quirks/` exists and holds `wm25lz.py`, and ZHA does not load it until the user adds the line and restarts

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

### Requirement: A file the integration did not write is never touched
The integration SHALL NOT write, replace, rename or delete a target that is not its own file. Ownership SHALL be decided in the same executor job as the write. It SHALL be checked again immediately before an outdated file is replaced. A new file SHALL be put in place by an operation that fails if anything exists at the path. When the target is not its own and U is not active, the integration SHALL raise the `quirk_file_conflict` Repairs issue, naming the file and the marker line, and saying that the integration left it alone and how to let the integration manage it. It SHALL delete that issue when a later reconciliation finds the file absent or its own, or U active.

#### Scenario: Unmarked file with the same name
- **WHEN** `wm25lz.py` in `custom_quirks_path` has no marker line, U is not active, and the integration is set up
- **THEN** the file's bytes and modification time are unchanged and `quirk_file_conflict` is raised, naming the file

#### Scenario: A link in the way
- **WHEN** `wm25lz.py` in `custom_quirks_path` is a broken symbolic link and the integration is set up
- **THEN** the link is unchanged and `quirk_file_conflict` is raised

#### Scenario: The user writes the file meanwhile
- **WHEN** the target was absent or the integration's outdated file when checked, and the user writes their own file there before the integration puts its copy in place
- **THEN** the user's file is kept and the integration reports it as not its own

#### Scenario: User's own working copy
- **WHEN** an unmarked `wm25lz.py` provides U, so U is active
- **THEN** the file is unchanged and no install-related Repairs issue is raised

### Requirement: Repairs issue when custom_quirks_path is not configured
While ZHA's YAML has no `custom_quirks_path`, U is not active and zha-quirks does not provide U, the integration SHALL raise the `custom_quirks_path_missing` Repairs issue, translated, not fixable, severity WARNING, whether or not writing the file succeeded. It SHALL give the exact YAML to add, `custom_quirks_path: <config dir>/custom_zha_quirks/` under `zha:`, and SHALL say to restart Home Assistant. It SHALL delete the issue when a reconciliation finds `custom_quirks_path` configured, U active, or zha-quirks providing U.

#### Scenario: YAML line missing
- **WHEN** the integration is set up while ZHA's YAML has no `custom_quirks_path`
- **THEN** `custom_quirks_path_missing` is raised, its text contains `custom_quirks_path: <config dir>/custom_zha_quirks/` and tells the user to restart, and `restart_required` is not raised

#### Scenario: YAML line missing and the folder unwritable
- **WHEN** the same happens and writing the file fails
- **THEN** both `custom_quirks_path_missing` and `quirk_file_not_written` are raised

#### Scenario: Line added and restarted
- **WHEN** the user then adds that line and restarts Home Assistant
- **THEN** U is active, and neither `custom_quirks_path_missing` nor `restart_required` is raised

### Requirement: Repairs issue asking for a restart after an install or update
After the integration writes the target file while `custom_quirks_path` is configured, it SHALL raise the `restart_required` Repairs issue, translated, not fixable, not persistent, severity WARNING, naming the file. The issue SHALL say that ZHA loads quirks only when it starts, and to restart Home Assistant or reload ZHA. The issue itself, as Home Assistant's issue registry holds it, SHALL be the record that ZHA has not loaded the file since that write; the integration SHALL keep no other state for it. The integration SHALL keep the issue across a reload or unload of the `smartwings` entry and across a ZHA reload after which U is still not active. It SHALL delete the issue only when a reconciliation finds U active, or zha-quirks providing U, or when the entry is removed. A Home Assistant restart ends it, because it is not persistent. While the issue stands, the missing-quirk issue SHALL be withheld (integration-core).

#### Scenario: ZHA reload loads the installed quirk
- **WHEN** the integration has installed the file and raised `restart_required`, and the user reloads ZHA
- **THEN** U is active for the shade and `restart_required` is deleted

#### Scenario: ZHA reload that misses the file
- **WHEN** ZHA's entry becomes loaded again without having loaded the installed file, so U is still not active
- **THEN** `restart_required` stays raised, `quirk_not_loaded` is not raised, and nothing logs at WARNING

#### Scenario: Reload of the integration keeps the request
- **WHEN** the `smartwings` entry is reloaded after it installed the file and before ZHA has loaded again
- **THEN** `restart_required` is still the only Repairs issue of the integration, and the file is not written again

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

### Requirement: File work runs off the event loop and fails visibly
The integration SHALL read and write the target file only in Home Assistant's executor (`hass.async_add_executor_job`), with each ownership check and the write it guards in one job. It SHALL write through a temporary file in the same folder whose name does not end in `.py`, putting it in place atomically. An `OSError` while reading or writing SHALL be logged at ERROR with the path. It SHALL also raise the `quirk_file_not_written` Repairs issue, translated, not fixable, severity WARNING, naming the file and the error. After a failed write, no Repairs issue SHALL claim the file was installed. No other exception SHALL be caught. Normal operation, including install, update and leaving a foreign file alone, SHALL NOT log at WARNING or above in any of the integration's loggers.

#### Scenario: Writes in the executor
- **WHEN** the integration installs the file or inspects it
- **THEN** every read and write of it runs through `hass.async_add_executor_job`, never on the event loop

#### Scenario: Unwritable folder
- **WHEN** writing the target file raises `OSError`
- **THEN** an ERROR is logged naming the path, `quirk_file_not_written` is raised with the error, setup still succeeds, and `restart_required` is not raised

#### Scenario: Quiet normal operation
- **WHEN** the integration installs or updates its file
- **THEN** none of its loggers logs at WARNING or above

### Requirement: Install issues follow the entry's lifecycle
Unloading the `smartwings` entry SHALL delete `custom_quirks_path_missing`, `quirk_file_conflict`, `quirk_file_not_written` and `quirk_now_upstream`. It SHALL keep `restart_required`, and SHALL leave the target file as it is. Removing the entry SHALL delete all five issues. Removing the entry SHALL NOT delete the installed quirk file, because ZHA may be using it.

#### Scenario: Entry unloaded
- **WHEN** the entry is unloaded while `restart_required` is raised
- **THEN** `restart_required` stays raised and the file stays

#### Scenario: Entry unloaded with a missing line and a foreign file
- **WHEN** the entry is unloaded while `custom_quirks_path_missing` and `quirk_file_conflict` are raised
- **THEN** both are deleted

#### Scenario: Entry removed
- **WHEN** the entry is removed while `quirk_now_upstream` or `restart_required` is raised
- **THEN** no Repairs issue of the integration remains

