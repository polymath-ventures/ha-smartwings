## Why

ZHA resolves every device's quirk when it sets up, before any custom integration loads (Part 2 §3c), so the only pre-upstream way to give ZHA the SmartWings quirk (U) is its `custom_quirks_path` folder. Today the user copies `wm25lz.py` there by hand and must copy it again after every update, because HACS updates the integration, not the quirk file. Owner decision (2026-10-05, issue #18): the integration (I) ships the quirk and installs it there itself, so the user installs one thing plus a one-time YAML line, and I steps aside once Home Assistant's own zha-quirks carries U (Part 3 §1b item 3, §3i as revised, §5f).

## What Changes

- The integration bundles the quirk as a data file, byte-identical to `quirk/zhaquirks/smartwings/wm25lz.py`. It is never imported or registered by the integration; it is only copied.
- The quirk source gains a marker line (its first line) that identifies a copy the integration installed. The bundled file carries it because it is identical to the source.
- On setup, and again whenever ZHA finishes (re)loading, the integration reconciles the quirk file in ZHA's `custom_quirks_path` (or, while that is not configured, the folder the Repairs issue tells the user to configure):
  - no file → install it; a file with the marker that differs from the bundled one → update it;
  - a file without the marker, a symbolic link or anything but a regular file → never touched; a Repairs issue explains why the quirk is not loaded from it;
  - the integration never deletes the file;
  - each check and its write run together in one executor job, atomically, re-checking ownership just before the file is put in place.
- New Repairs issues, all stock Home Assistant issues with translation keys in `strings.json` (= `translations/en.json`):
  - `custom_quirks_path_missing`: ZHA has no `custom_quirks_path`; gives the exact YAML line and says to restart; goes once the quirk is active.
  - `restart_required`: the integration installed or updated the file; asks for a restart (a ZHA reload also loads it); goes once the quirk is found active. While it stands, it is shown instead of `quirk_not_loaded`, and nothing logs at WARNING.
  - `quirk_file_conflict`: an unmarked file (or a link) of the same name is in the way and the quirk is not active.
  - `quirk_file_not_written`: writing the file failed; gives the reason.
  - `quirk_now_upstream`: zha-quirks now provides U; the integration stopped updating its file, and the user may delete it and the `custom_quirks_path` line if nothing else uses them.
- Upstream transition: when ZHA's quirk registry holds an unrestricted WM25/L-Z quirk (no filter, no firmware bounds) from outside `custom_quirks_path` that declares the closed-limit contract, the integration stops installing and updating, never deletes its file, and raises `quirk_now_upstream`.
- ZHA is never reloaded automatically.
- README "Install": the quirk is installed automatically once `custom_quirks_path` is set; copying the file by hand stays as an alternative.

## Capabilities

### New Capabilities
- `bundled-quirk-install`: shipping U inside I and installing and updating it in ZHA's `custom_quirks_path`, with the Repairs issues that tell the user what to do (Part 3 §1b item 3, §3i, §5f; issue #18).

### Modified Capabilities
- `integration-core`: the missing-quirk Repairs issue is withheld, and its WARNING not logged, while the integration's restart request stands (PR #33 review); it is first evaluated after the first reconciliation at setup.

## Impact

- Code: `custom_components/smartwings/` (new install module and bundled quirk data file, `zha_gateway.py` gains ZHA's YAML `custom_quirks_path` and the quirk-registry check, `__init__.py` wiring, `repairs_missing.py`, `strings.json`, `translations/en.json`).
- Quirk source: one marker comment line at the top of `quirk/zhaquirks/smartwings/wm25lz.py`. No behaviour change. The upstream PR (#17) may drop the line; a file without it is never touched.
- Tests: the real Home Assistant + real ZHA harness (fresh install, YAML missing, outdated own file, unmarked file, upstream present, ZHA reload, executor use); `tests/test_packaging.py` covers the bundled copy; the harness can run ZHA without `custom_quirks_path`. Existing tests that need U absent run without `custom_quirks_path`, or expect the new issues.
- Docs: README "Install".
- Files written in the user's config: only `<custom_quirks_path>/wm25lz.py` (or the default folder while unconfigured), and only when absent or a regular file carrying the marker. No file is ever deleted.
