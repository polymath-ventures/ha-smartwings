## 1. Bundled file and marker

- [x] 1.1 Failing tests (`tests/test_packaging.py`, `tests/test_quirk_file.py`): the bundled file exists and is byte-identical to the quirk source; the tracked-copy scan covers files of any suffix named like `wm25lz*`; the source's first line is the marker; own/outdated/foreign recognition (marker on line 1 only, exact match, byte comparison).
- [x] 1.2 Add the marker as the quirk source's first line; add `custom_components/smartwings/bundled_quirk/wm25lz.py.txt`; widen the packaging scan.
- [x] 1.3 Add `bundle.py`: synchronous inspect (absent / own current / own outdated / foreign), atomic install via `homeassistant.util.file.write_utf8_file` (creating the folder), and remove-if-own. No Home Assistant state, no imports of quirk code.

## 2. ZHA surfaces

- [x] 2.1 Failing tests: `custom_quirks_path` is read from ZHA's runtime YAML (configured and unconfigured harness); the registry check is false with only zha-quirks' released vendor quirk, false when the contract-declaring entry comes from `custom_quirks_path`, true when it comes from outside it, false when a near-miss declaration differs in type or manufacturer code.
- [x] 2.2 Harness: allow starting ZHA without `custom_quirks_path`; helper to register the quirk as if zha-quirks shipped it (loaded from a folder outside `custom_quirks_path`), cleaned up at close.
- [x] 2.3 Implement `async_custom_quirks_path` and `zha_quirks_provide_closed_limit` in `zha_gateway.py`; factor the contract's attribute-definition check in `contract.py` so device and declaration share it.

## 3. Reconciliation and Repairs issues

- [x] 3.1 Failing harness tests: fresh install writes the file and raises `restart_required` without reloading ZHA; restart → U active and no install issue; ZHA reload → U active and `restart_required` gone; entry reload keeps `restart_required` without a rewrite; YAML missing → `custom_quirks_path_missing` with the exact line, file in `<config>/custom_zha_quirks/`, then line added + restart → active and issues gone; own outdated file updated; own current file not rewritten; unmarked file untouched (bytes and mtime) with `quirk_file_conflict`; unmarked working copy → no issue; upstream present → own file removed and `quirk_file_removed`, still raised after restart with U active from zha-quirks; upstream present with unmarked file → untouched; file reads/writes/removals go through `hass.async_add_executor_job`; `OSError` on write → ERROR log, no `restart_required`; no WARNING in normal operation; unload deletes the missing-line and conflict issues and keeps `restart_required`; removal deletes all of them; no module created from the bundled file and no registry entry added.
- [x] 3.2 Add `strings.json` / `translations/en.json` text for the four issues; translation tests for their placeholders and the exact YAML line.
- [x] 3.3 Implement `installer.py` (`QuirkInstaller`: lock, the active `restart_required` issue as the record of a pending restart, the D7 decision table, D8 issues, INFO logging) and wire it in `__init__.py`: awaited after the first discovery at setup, re-run when ZHA's entry becomes loaded through the existing ZHA state-change listener, the missing-line and conflict issues deleted at unload, all deleted at removal.
- [x] 3.4 Update existing tests whose precondition is "U absent": run them with ZHA's `custom_quirks_path` unconfigured, or expect the new issues alongside `quirk_not_loaded`.

## 3b. Review of PR #33

- [x] 3b.1 Check and write in one executor job (`bundle.sync`): a new file is hard-linked into place (fails if anything appeared), an outdated own file is re-inspected just before `os.replace`; tests where the user writes the file meanwhile, for both cases.
- [x] 3b.2 Never delete on upstream detection: stop updating, raise the non-persistent `quirk_now_upstream` note while the own file is there; detection ignores entries with a filter or firmware bounds; tests for the note, skipped update, the user deleting the file, and restricted entries (unit and harness).
- [x] 3b.3 Judge the path, not a link's target: `O_NOFOLLOW` plus `fstat`; a link (broken or not) or a non-regular file is foreign; unit tests and a harness test with a broken link.
- [x] 3b.4 `restart_required` is withdrawn only when a reconciliation finds the quirk active; test a ZHA reload that misses the file.
- [x] 3b.5 `custom_quirks_path_missing` no longer depends on the write; a failed write raises `quirk_file_not_written` with the error; tests configured and unconfigured.
- [x] 3b.6 While `restart_required` stands, `quirk_not_loaded` is withheld and nothing logs at WARNING (integration-core delta); the missing-quirk issue is first evaluated after the first reconciliation; tests check every integration logger, and the issue returns after a restart that does not load the quirk. Existing repairs tests run without `custom_quirks_path` or with a user file blocking the install.
- [x] 3b.7 Marker wording: "which keeps this file up to date" (the integration no longer deletes it).
- [x] 3b.8 Re-review C3: resolve a relative `custom_quirks_path` as ZHA does (working directory) and compare absolute paths on both sides; harness tests with `custom_quirks_path: custom_zha_quirks` run from the config folder.

## 4. Documentation

- [x] 4.1 README "Install": the integration installs and updates the quirk once `custom_quirks_path` is set; the Repairs issues it raises; copying the file by hand stays as an alternative (keep the file path and the one YAML block the packaging tests read).
- [x] 4.2 Full gate: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`.
