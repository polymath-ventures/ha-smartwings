## 1. Preconditions

- [x] 1.1 Confirm #5 (real-ZHA harness), #7 (U's closed-limit cluster and `number`, contract constants) and #11 (shade directory, "U active" predicate, `get_contract_cluster`) are merged. Read ADR 0001.

## 2. Failing tests first (harness #5; each must fail before implementation)

- [x] 2.1 One ZHA-owned `number` per shade on the shade's device; the integration registers no `number` platform; no extra device in the registry
- [x] 2.2 Control shows the raw stored value (14) while the cover reports position 0 at the stop; unset shows `unknown`
- [x] 2.3 Store operations: change and clear write through `update_attribute`, send no frame, and refresh ZHA's control (a clear is visible without a restart); a missing cluster or raising write fails naming the shade and keeps the old stop (F8)
- [x] 2.4 Options flow Change stop: lists only shades with U active and a stop; rejects 96 and -1 with the range message (F7, §5b item 7); "<shade>: <old> → <new>. Change it?" stores on confirm and the next close uses it; cancel stores nothing
- [x] 2.5 Restart and ZHA reload: stop 14 shown and the first `cover.close_cover` is the limited go-to (§5b items 3, 4)
- [x] 2.6 Clear → control `unknown`, next close byte-identical to the vendor quirk's (§2d, §5b item 6)
- [x] 2.7 Delete the config entry → every stop cleared, including after a restart with U loaded (F9)
- [x] 2.8 Remove the shade's "Stops at" entity from the registry → stop cleared; disable it → stop kept and one Repairs issue names the shade and value; re-enable → issue deleted (§2f)
- [x] 2.9 New control id ends in `_stops_at`; a user rename survives restart (F11)
- [x] 2.10 Fresh install, three restarts → nothing written, every control `unknown` (F15)

## 3. Store operations (shared with #13)

- [x] 3.1 Implement `store.py`: `async_change_closed_limit`, `async_clear_closed_limit`, `async_refresh_control`, resolving the cluster through #11's `get_contract_cluster` each call and using only zigpy's public cluster API
- [x] 3.2 Find ZHA's "Stops at" entity by device plus the translation key U publishes (`closed_limit`), not the unique-id suffix (that is U's Python attribute name, not a contract term); pin it with a harness test

## 4. Dialog, removal and registry watching

- [x] 4.1 Options flow "Change stop": shade select → value (number selector, contract range, step 1) → confirm step, calling the store operations
- [x] 4.2 `async_remove_entry` sweep: clear and refresh every shade with U active
- [x] 4.3 Entity-registry listener for each shade's "Stops at" entity: clear on removal; Repairs issue on disable; delete it on re-enable or clear
- [x] 4.4 Translations (`strings.json` / `translations/en.json`) for the dialog steps, the range error, the change-refused hint (pointing to Configure → Change stop), and the disabled-control Repairs issue, in protocol vocabulary per §3h

## 5. Verify and clean up

- [x] 5.1 All tests in group 2 pass; `ruff check` clean; review checklist (§5e): no test passes on missing input (F14)
- [x] 5.2 Confirm none of the dropped old-code pieces (design "Port notes") exist in the new code

## 6. Review fixes (PR #29)

- [x] 6.1 Owed clears: a control removed while the stop cannot be cleared is recorded in the integration's Store and cleared at the next discovery that reaches the shade; a failed clear is retried
- [x] 6.2 Refresh confirmation: after `update_entity`, the control must show the stored value, or the operation raises saying the stop was stored but the control could not be refreshed
- [x] 6.3 Disabled-control Repairs text gives routes that exist now (enable the control, Configure → Change stop, remove the control)
- [x] 6.4 Integration removal while ZHA is down: documented as a known limit of F9; the WARNING names every registered shade
- [x] 6.5 Owed clears name the stop they are owed for; a write through the integration cancels the debt; a different stored value drops it
- [x] 6.6 Owed-clear saves are serialised and awaited on unload, so removal leaves no store behind
- [x] 6.7 Removal waits for every owed-clear save in flight, however long, before deleting the store
