## 1. Preconditions

- [x] 1.1 Confirm these dependencies are merged and record the exact interfaces used in this change's PR description:
  - `add-closed-limit-contract` (#7): range constants and unset value.
  - `add-verified-delivery` (#8): read-retry values (mirrored in the integration, not imported).
  - `add-closed-limit-enforcement` (#9): that read return values stay raw while the cache is rescaled.
  - `add-integration-core` (#11): shade resolution and the quirk-active check.
  - `add-stops-at-control` (#12): `async_change_closed_limit`, `async_clear_closed_limit` and `async_refresh_control`.
- [x] 1.2 Read ADR 0001 (`docs/decisions/0001-quirk-v2-hosts-stops-at.md`): ZHA hosts "Stops at" from the quirk, so the actions target the cover (D1) and write through #12's store operations followed by a refresh (D4).

## 2. Harness tests first (all failing before implementation)

- [x] 2.1 Using the #5 harness: success. The motor model rests at lift 84 and the cache holds lift 0. Capture stores 16, the response returns 16, no persistent notification is created, and the wire shows only Read Attributes for 0x0102/0x0008.
- [x] 2.2 Raw versus scaled: with an existing stop of 20 (so the cover is rescaled by #9) and the motor at lift 84, capture stores 16.
- [x] 2.3 `read_attributes_raw` returns the unscaled lift while the quirk rescales the cache (guards D2's coordination with #9).
- [x] 2.4 Still moving: the motor model is travelling during capture. The action raises "still moving", and the store is unchanged.
- [x] 2.5 Each remaining failure path raises `HomeAssistantError` naming the shade and leaves the store unchanged:
  - no such entity;
  - a non-WM25/L-Z ZHA cover;
  - quirk inactive (stock vendor quirk loaded);
  - all reads time out;
  - lift 255;
  - error status record;
  - out-of-range value;
  - store raises;
  - an exception inside the quirk-active check (fails with that exception: no catch-all).
  Unreadable and still-moving messages include the what-to-do guidance (design D10).
- [x] 2.5a Existing stop: without `replace_existing` capture raises naming the shade, its current value, `replace_existing` and Change stop, sends no read, and stores nothing; with `replace_existing: true` it stores and returns the new value; a first capture needs no flag.
- [x] 2.5b Conversion: lift 84 → stored 16 via the single integration function; no import of quirk modules anywhere in `custom_components/smartwings` (assert by scanning imports).
- [x] 2.6 Retry: the first read is dropped and the retry lands. Capture succeeds, and exactly the expected number of read frames is sent.
- [x] 2.7 Concurrency: two captures on one shade run serially, and captures on two shades do not block each other.
- [x] 2.8 Clear:
  - clear with a stop set, then `cover.close_cover`, gives a stock frame identical to the vendor quirk's;
  - clear with nothing set succeeds and sends no frame;
  - clear with the quirk inactive raises naming the shade and the remedy, and sends no frame;
  - clear on a non-WM25/L-Z raises;
  - clear when the store raises raises.
- [x] 2.9 Worst-case duration of one capture with every read dropped is within the documented bound (virtual time).
- [x] 2.10 Persistence: after capture, a full HA restart in the harness, then `cover.close_cover`, the frame stops at the captured value (restored from zigpy's database; no Home Assistant restore involved).

## 3. Implementation

- [x] 3.1 Add action constants and schemas: `capture_closed_limit` (required `cover`, optional boolean `replace_existing`, default false) and `clear_closed_limit` (required `cover`). Register them in `async_setup` (Home Assistant's action-setup rule; design D4a); capture declares `SupportsResponse.OPTIONAL`.
- [x] 3.2 Implement shade resolution (via #11) and the WM25/L-Z check, wrapping errors as `HomeAssistantError` (D6 steps 1–3).
- [x] 3.3 Implement the raw live read with `read_attributes_raw([0x0008])`, record validation (SUCCESS, value 0–100) and #8's retry constants (D2).
- [x] 3.4 Implement the stationary check: read A, `CAPTURE_SETTLE_S`, read B, exact equality (D3).
- [x] 3.5 Implement the conversion as one integration function, `stored = 100 − raw lift` (design D8), and range validation with the integration's copy of #7's published contract terms. No use or mirror of `LiftScale`; no import of quirk code.
- [x] 3.6 Implement the `replace_existing` gate (D9), then `async_change_closed_limit` and `async_refresh_control` from #12; success response, no notification, and INFO log (D4, D5). Test that the "Stops at" control shows the new value immediately.
- [x] 3.7 Implement clear with `async_clear_closed_limit` and `async_refresh_control` from #12, idempotently; without ZHA or the quirk it fails naming the shade, as the merged store does (D6). Test that the control shows `unknown` immediately.
- [x] 3.8 Add the per-IEEE handler lock (D7).
- [x] 3.9 Port from `oldcode/.../__init__.py::capture` only its error-message pattern ("Closed limit not captured: <entity>: <reason>"). Drop:
  - `zha_toolkit`;
  - `update_entity`;
  - `asyncio.sleep(6)`;
  - the `current_position` read;
  - the direct-write fallback;
  - WARNING logs.

## 3a. Review of PR #31 (2026-10-06)

- [x] 3a.1 Capture refuses, storing nothing, when ZHA's "Stops at" control was removed during its reads; the owed clear survives. A disabled control is allowed (the Repairs issue names the stop).
- [x] 3a.2 Move the per-shade write lock into the store, taken by every writer (dialog, capture, clear, removal sweep, owed clears); capture, the dialog and owed clears compare-and-set. Test the dialog-versus-capture race in both orders.
- [x] 3a.3 Carve the store's refresh failure out of "stores nothing" in the capture and clear spec and docstrings; cover it for capture.
- [x] 3a.1a Move the control check into the store's change path, so the Change-stop dialog refuses too while the control is missing (clears exempt); update #12's dialog test, the pending-clears docstring and the `stops-at-control` delta.
- [x] 3a.4 State the single-capture bound and that a capture waits for another one on the same shade.
- [x] 3a.5 Re-review: an owed clear refused by compare-and-set for another stop drops its debt at DEBUG; the store refuses writes once the entry is unloaded or removed (removal sweep exempt); the proposal carves out the refresh failure.

## 4. Metadata and docs

- [x] 4.1 Write `services.yaml` entries with a cover entity selector filtered to integration `zha`, domain `cover`, and the `replace_existing` boolean on capture. Add the matching `strings.json` and `translations/en.json` text in protocol vocabulary ("closed limit", label "Stops at"), stating the worst-case duration.
- [x] 4.2 Add a test that every registered action has translations and that the service schema matches `services.yaml`.
- [x] 4.3 Add a README section on capture and clear: drive the shade to its stop with the remote, wait for it to stop, run capture. Hand the wording to #14.

## 5. Verify

- [x] 5.1 `ruff check` and the full pytest suite pass, and every scenario in `specs/closed-limit-capture/spec.md` maps to a named test.
- [x] 5.2 `openspec validate add-closed-limit-capture --strict` passes.
- [x] 5.3 Hand the acceptance step to #15: capture the Office Shade's stop with its remote on the box and confirm the stored value in the response and on the "Stops at" control. The owner runs this. *Handed to #15 (comment posted).*
