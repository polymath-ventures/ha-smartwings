## Context

ZHA loads quirks once per setup of its config entry: `Gateway.async_from_config` calls `zhaquirks.setup(custom_quirks_path)` in the executor (`zha/application/gateway.py:231-240`), which imports zha-quirks' own modules, then every module in `custom_quirks_path` (`zhaquirks/__init__.py:565-613`). Devices are resolved against that registry as the gateway starts. A quirk file that appears later takes effect at the next Home Assistant restart or ZHA reload, never sooner (memory of #11; ADR 0001's spike proved both paths).

The `custom_quirks_path` value is ZHA's YAML, validated with `cv.isdir` (`homeassistant/components/zha/__init__.py:77`), stored as `HAZHAData.yaml_config` in `hass.data["zha"]` (`__init__.py:124-125`, `helpers.py:1120-1124`), read through `get_zha_data` (`helpers.py:1151-1157`) and passed to the quirks configuration (`helpers.py:1418-1420`). It is fixed for the whole Home Assistant run: a ZHA reload does not re-read YAML.

Today the README tells the user to copy `quirk/zhaquirks/smartwings/wm25lz.py` into that folder and to repeat the copy after every update. Part 3 §3i, as revised, allows I to install that file (#18); it still forbids any file bridge for the stop value. Part 3 §1c still forbids I importing or calling U's code.

## Goals / Non-Goals

**Goals:**
- One install (the integration) plus one YAML line gives a working quirk after a restart, and keeps it current as the integration updates.
- Never overwrite a file the integration did not write, and never delete any file.
- Step aside when Home Assistant's own zha-quirks carries U: stop updating and tell the user, never delete.
- Say what to do through stock Repairs issues; no WARNING log in normal operation; file I/O off the event loop.

**Non-Goals:**
- Reloading ZHA automatically, at startup or after an install.
- Editing `configuration.yaml`.
- Detecting other custom quirks that claim the WM25/L-Z under other file names (the owner's old `smartwings_wm25lz_readback.py`, for example). If one wins, U is not active, and the existing `quirk_not_loaded` issue says so.
- Any change to how U's activity is decided (integration-core) or to the missing-quirk issue.

## Decisions

### D1. The bundled copy is a data file, kept identical by a test

`custom_components/smartwings/bundled_quirk/wm25lz.py.txt` holds the exact bytes of `quirk/zhaquirks/smartwings/wm25lz.py`. The `.txt` suffix means no import machinery, linter or import scan treats it as integration code, and nothing can import it by accident. The integration installs it under the name `wm25lz.py`, the name the README gives.

`tests/test_packaging.py` already requires every tracked copy of the quirk to be byte-identical to the source. Its scan widens from `*.py` files to any tracked file named like `wm25lz*`, and a direct test compares the bundled file. A change to the quirk without copying it fails the suite.

*Alternatives:* a symlink, which HACS downloads as a text file holding the link target; a build step, which nothing here runs; a `.py` copy inside the package, which the import-boundary test would scan as integration code and which Python could import as a namespace-package module.

### D2. The marker is the quirk's first line; the version is the content

The source file's first line is a comment marking a copy the integration manages:

`# Installed by the SmartWings integration for Home Assistant, which keeps this file up to date. Delete this line to keep the file as your own.`

A regular file (not a link) whose first line equals that text is the integration's own. It is outdated when its bytes differ from the bundled file's. A version number would have to be bumped by hand on every change, and a missed bump would leave users on old code; a byte comparison cannot drift. The marker tells the user how to opt out: a file without it is never touched.

### D3. The target folder

The target is `<custom_quirks_path>/wm25lz.py`, with the path read from ZHA's own YAML data (`get_zha_data(hass).yaml_config`; Context). The helper lives in `zha_gateway.py` with the other ZHA surfaces.

A relative value is resolved as ZHA resolves it: against the process's working directory, not the config folder. `cv.isdir` checks `os.path.isdir(os.path.expanduser(value))` and stores the expanded value (`homeassistant/helpers/config_validation.py:301-311`). `zhaquirks.setup` walks `pathlib.Path(value)` (`zhaquirks/__init__.py:574, 594-600`). Python's path finder records each module's file as `os.path.abspath` of it (`FileFinder.__init__`). The helper therefore returns `abspath(expanduser(value))`, so the folder written to and every quirk's source file are compared as absolute paths. On Home Assistant OS the working directory is `/config`. (ZHA's own `purge_custom_quirks` compares against the unresolved value, so with a relative path its purge misses; that is ZHA's, not changed here.)

When `custom_quirks_path` is not configured, the target is the folder the Repairs issue asks the user to configure, `hass.config.path("custom_zha_quirks")`, `/config/custom_zha_quirks/` on Home Assistant OS. The integration creates the folder and installs the file there first, because `cv.isdir` makes ZHA's whole configuration invalid when the folder does not exist. The YAML line the issue gives is then always valid, and one restart after adding it loads U. The integration writes nothing else outside `custom_quirks_path`.

### D4. "U is active" comes from the shade directory

The decision reuses integration-core's contract-only status: U is active when at least one shade is tracked and U is active for every tracked shade. With no shades the answer is "not active", so the file is installed in advance, and a shade paired later is resolved with U once ZHA has loaded it.

### D5. "zha-quirks provides U" comes from ZHA's quirk registry, by the contract

ZHA registers custom quirks after zha-quirks' own and inserts each new entry at the front of the list for its model (`zha/quirks.py:174-191`). The first match wins (`zha/quirks.py:216-233`). While the integration's file is installed it therefore always wins, so the quirk on the device cannot show whether zha-quirks would also provide U. The integration answers that from the registry instead: zha-quirks provides U when `zha.quirks.DEVICE_REGISTRY` holds an entry that

1. applies to `("Smartwings", "WM25/L-Z")` with no filter and no firmware bounds, so ZHA would apply it to every unit (`zha/quirks.py:63-105`),
2. was not loaded from `custom_quirks_path`, judged the way ZHA's own purge judges it (`Path(source.file).is_relative_to(custom_quirks_path)`, `zha/quirks.py:288-297`), and
3. adds or replaces, on endpoint 1 as a server cluster, a cluster class with id `0xFC01` whose attribute definitions declare attribute `0x0000` as `uint8` with manufacturer code `0x1002`. That is the same contract check as integration-core's, applied to the declaration instead of the built device.

This reads data ZHA has already loaded. It imports nothing, calls no quirk code and uses no class or module name. It answers a different question from integration-core's activity decision, which still reads only the device. Only quirks v2 operations, which carry a `cluster` class with an `endpoint_id`, are inspected: U is a quirks v2 quirk (ADR 0001).

The registry cannot show which entry ZHA would really resolve to once the file is gone: ZHA's priority between entries and its filters decide that. So the answer only ever changes what the integration says and whether it updates its file. **The integration never deletes the file on this answer** (owner rule: never risk the user's working setup; PR #33 review). It stops updating it and raises `quirk_now_upstream`, which tells the user that they may delete the file and the `custom_quirks_path` line. A wrong answer then costs at most a note and a skipped update.

*Alternatives:* comparing the active quirk's source file with the installed file only detects upstream once the integration's file is gone. Removing the file automatically was the first design; review rejected it because a filtered or lower-priority upstream entry could leave the shades without U. Reading zha-quirks' `smartwings/wm25lz.py` source text breaks if upstream renames the file.

### D6. When reconciliation runs

- At entry setup, after the first discovery; setup awaits it.
- Each time ZHA's config entry becomes loaded again, through the one ZHA state-change listener `__init__.py` already registers, so no listener is added.
- Runs are serialised by a lock. A run does nothing while ZHA's gateway is unavailable.

The record that the integration wrote the file and ZHA has not loaded it since is the `restart_required` issue itself, as Home Assistant's issue registry holds it. It survives a reload or unload of the `smartwings` entry. It is deleted only when a reconciliation finds U active on every tracked shade, not merely because ZHA's entry became loaded. A reload that raced the write and missed the file therefore leaves it in place. A restart leaves only an inactive record, because the issue is not persistent. The integration keeps no state of its own in `hass.data` for this.

The missing-quirk issue (integration-core) is only for a quirk the integration could not get loaded. While `restart_required` stands, it is shown instead: the missing-quirk issue is withheld, and its WARNING is not logged. At setup the missing-quirk issue is first evaluated after the first reconciliation. After every reconciliation it is evaluated again, so it appears once the restart request is gone and the quirk is still not active.

### D7. What one reconciliation does

| zha-quirks provides U (D5) | File at target | U active (D4) | Action | Issues raised (all others of D8 deleted) |
|---|---|---|---|---|
| yes | ours (any version) | any | none: no update, no deletion | `quirk_now_upstream` |
| yes | absent or foreign | any | none | none |
| no | ours, outdated | any | update it | `restart_required`, or `custom_quirks_path_missing` if unconfigured and U not active |
| no | absent | no | install it | `restart_required`, or `custom_quirks_path_missing` if unconfigured |
| no | absent | yes | none (U comes from elsewhere) | none |
| no | ours, current | no | none | `restart_required` if still raised (D6); `custom_quirks_path_missing` if unconfigured |
| no | ours, current | yes | none | none |
| no | foreign (incl. a link or non-file) | no | none | `quirk_file_conflict` (plus `custom_quirks_path_missing` if unconfigured) |
| no | foreign | yes | none | none |
| no | write fails | any | none | `quirk_file_not_written` (plus `custom_quirks_path_missing` if unconfigured and U not active) |

An own outdated file is updated even while U is active, so that an integration update reaches the user's quirk. That is the README's "copy it again" step, now automatic.

### D8. The Repairs issues

All five are stock issue-registry issues with fixed ids equal to their translation keys and text under `issues` in `strings.json`. None is fixable and none is persistent. Every reconciliation recomputes them.

| Id | Severity | Placeholders | Deleted when |
|---|---|---|---|
| `custom_quirks_path_missing` | WARNING | `path` | a run finds it configured, U active, or zha-quirks providing U; entry unload or removal |
| `restart_required` | WARNING | `file` | a run finds U active; zha-quirks providing U; a restart; entry removal |
| `quirk_file_conflict` | WARNING | `file`, `marker` | a run finds the file absent, ours, or U active; entry unload or removal |
| `quirk_file_not_written` | WARNING | `file`, `error` | a run whose file work succeeds; entry unload or removal |
| `quirk_now_upstream` | WARNING | `file` | the user deletes the integration's file; entry unload or removal |

`restart_required` outlives an unload of the entry: ZHA still has to load the file whether or not the integration is loaded. The others are recomputed only while the entry is loaded, so they go when it unloads, as `quirk_not_loaded` does.

`restart_required` says that a ZHA reload also loads the file. A harness test proves that a ZHA reload resolves the shade with the newly installed U, so the issue offers it rather than requiring a full restart (#18's decision default). The integration never triggers the reload itself.

### D9. File I/O

`bundle.py` holds the synchronous file operations, with no Home Assistant state. Each runs as one `hass.async_add_executor_job`:

- `inspect` judges the path itself: it opens with `O_NOFOLLOW` and checks `fstat`. A symbolic link, broken or not, and anything but a regular file is foreign, never "absent" and never "ours".
- `sync` checks and writes in the same job. The bytes go to a temporary file in the same folder, named `.wm25lz.py.*.tmp`, so ZHA's loader never sees a half-written module.
  - A new file is hard-linked into place, which fails atomically if anything appeared at the path meanwhile.
  - An outdated own file is re-inspected immediately before `os.replace`, and the write is abandoned if it is no longer the integration's.

Only `OSError` is caught. It is logged at ERROR with the path and reported through `quirk_file_not_written`; no issue claims the file was installed. Nothing else is caught.

### D10. Logging

A write is logged at INFO with the path; leaving a foreign file alone at DEBUG. Nothing in this capability logs at WARNING, and while a restart is pending no part of the integration does. Home Assistant shows the Repairs issues.

## Risks / Trade-offs

- [The marker line goes upstream with the file] → harmless there, because zha-quirks' copy never sits in `custom_quirks_path`. The upstream PR (#17) can drop it, and a copy without it is simply foreign.
- [A user's edits to a marked file are overwritten] → the marker says so and tells them to delete the line to keep their own copy.
- [ZHA/zhaquirks internals: `HAZHAData.yaml_config`, `DEVICE_REGISTRY` entries, builder operations] → isolated in `zha_gateway.py`, and pinned by harness tests that load real ZHA and real zha-quirks. An upgrade that changes them fails the tests, not the user's shades.
- [A wrong "zha-quirks provides U" answer] → it never deletes anything (D5). The worst case is a note and skipped updates while it stands.
- [Writing into a folder ZHA does not use yet (unconfigured case)] → limited to creating `<config>/custom_zha_quirks/` and its `wm25lz.py`, which is what the issue's YAML line points at.
- [Another custom quirk file that claims the WM25/L-Z can still win] → U is then not active and `quirk_not_loaded` remains. This is out of scope (Non-Goals).
- [Accepted: update of an active quirk] → reloading only SmartWings after updating an already-active outdated quirk clears `restart_required` although ZHA still runs the old code; the old quirk keeps working until ZHA loads the new file.
- [Accepted: replace window] → between the final ownership check and `os.replace` of an outdated own file there is a residual window; POSIX has no compare-and-rename, so a user write in that instant can be overwritten.
- [Accepted: held-back issue across ZHA reloads] → while `restart_required` stands, `quirk_not_loaded` stays held back across ZHA reloads; `restart_required` is visible and says what to do.
- [ZHA reloaded while the `smartwings` entry is unloaded] → nothing deletes `restart_required` then. It is not persistent, so it lasts until the next restart at most.
- [A filesystem without hard links] → installing a new file then fails with `OSError` and `quirk_file_not_written` says so. Home Assistant OS's `/config` supports them.
- [Module names] → the integration's modules are `bundle.py` and `installer.py`. A name starting with `quirk` would trip the existing guard against importing the `quirk/` package.

## Migration Plan

Users who copied the file by hand have an unmarked copy. While it provides U, nothing changes. If it is older and does not provide U, `quirk_file_conflict` tells them to delete it so the integration can manage it. The README says the same. No data migration. When zha-quirks ships U, the integration's file stays until the user deletes it, as `quirk_now_upstream` suggests.
