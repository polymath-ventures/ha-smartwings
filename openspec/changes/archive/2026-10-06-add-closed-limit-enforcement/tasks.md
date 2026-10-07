## 0. The v2 quirk (ADR 0001)

- [x] 0.1 Write a failing harness test: with U in `custom_quirks_path`, the shade's WindowCovering cluster is the enforcement subclass, the `0xFC01` closed-limit cluster is present, and the battery entity shows the same value as the released vendor quirk for the same raw report
- [x] 0.2 Register U as one `QuirkBuilder` chain: replace WindowCovering with the enforcement subclass, replace PowerConfiguration with the vendor's `DoublingPowerConfigurationCluster`, add #7's closed-limit cluster

## 1. Conversion module (F1)

- [x] 1.1 Write failing property tests for `LiftScale` over all raw lifts 0–100 and every valid closed limit from #7's range: unset is identity; unscale never exceeds the close target; scale is monotonic; closed iff in the closed band; round-trip within 1 point below the band; only slider 0 reads closed, for every stop × slider position; the band shrinks to `min(CLOSED_BAND, A // 4)`
- [x] 1.2 Write failing table tests for the worked example (Stops at 14 → L 86, A 84, band from 82, scaled 50 → raw 41, scaled 99 → raw 81, raw 41 → scaled 50)
- [x] 1.3 Implement `LiftScale` as a pure frozen value object with integer round-half-up arithmetic and `CLOSE_TARGET_MARGIN = 2`, `CLOSED_BAND = 2`; `LiftScale` also owns the stop↔lift step (`L = 100 - s`); #7 provides no conversion
- [x] 1.4 Add a lint-level or test-level guard that no other U module performs `100 - …` position arithmetic (grep test over the U package)

## 2. Unset path is stock (Part 3 §3a, §5a items 1, 2, 16)

- [x] 2.1 Write failing wire tests (real cluster class, zigpy's real request path, decoded frames) comparing U against the released `zhaquirks.smartwings.wm25lz.InvertedWindowCoveringCluster` for `down_close`, `go_to_lift_percentage(37)` positional and keyword, `stop`, with no closed limit set; and a failing test that `up_open` with no closed limit set sends `go_to_lift_percentage(0)`, NOT the vendor frame (owner decision 2026-10-05; Part 3 §5a item 1 reads "open with and without a stop" as go-to 0 in both cases)
- [x] 2.2 Write failing tests that an out-of-range stored closed limit (per #7) yields the same stock frames (opens as go-to 0) and identity display
- [x] 2.3 Implement the unset branch of the translation table (D4): opens as `_deliver(WireCommand(go_to_lift_percentage, (0,), 0))`, the close swap ported from the released quirk, not from oldcode

## 3. Set path: translation (Part 3 §2g, §5a items 1, 3, 4)

- [x] 3.1 Write failing wire tests with Stops at 14: `down_close` → `go_to_lift_percentage(84)`; `up_open` → `go_to_lift_percentage(0)`; scaled 0/50/99/100 → raw 0/41/81/84 in positional and `percentage_lift_value=` forms; no frame ever exceeds 84; every frame is `go_to_lift_percentage`
- [x] 3.2 Write a failing test that `go_to_lift_value` with a stop set raises an error naming the shade and sends nothing
- [x] 3.3 Write a failing test that a raising contract read aborts `down_close` with an error naming the shade and sends nothing (F13)
- [x] 3.4 Implement argument normalisation (positional or keyword, forwarded once) and the set branch of `command()`, calling the #8 seam `self._deliver(WireCommand(command_id, args, target_lift))`; use a recording fake of `_deliver` in unit tests until #8 lands

## 4. Stop passthrough (Part 3 §2l, F16, §5a item 5)

- [x] 4.1 Write failing tests: `stop` with and without a limit sends exactly one `stop` frame, no reads and no go-to, and surfaces UNSUP_CLUSTER_COMMAND to the caller unchanged
- [x] 4.2 Implement the passthrough branch as `_deliver(WireCommand(command_id, args, None))`, which #8 sends once, unverified, without the lock or tracking hooks

## 5. Display rescaling (Part 3 §2h)

- [x] 5.1 Write failing tests at cluster level: with Stops at 14, a read response of raw 84 caches 100 and raw 41 caches 50; `read_attributes` returns the raw value; raw 255 leaves cache and raw field unchanged; a Report Attributes frame is scaled the same way
- [x] 5.2 Implement the `_update_attribute` override for 0x0008 and the in-memory `_raw_lift`; override #8's `_cached_lift_raw()` to return `_raw_lift` from the device, the cache when no limit is set, else `None` (no separate `raw_lift_baseline()`), with a failing test first
- [x] 5.3 Write failing tests for rescale on change: set 14 with raw 84 → cache 100 and an attribute event, no frame sent; clear with raw 42 → cache 42; after a simulated restart with cache 50 under 14 and no read, change to 20 → derived raw 41, rescaled cache, `_cached_lift_raw()` is `None`
- [x] 5.4 Implement `_rescale()` and subscribe to the sibling `0xFC01` cluster's `AttributeUpdatedEvent` and `AttributeClearedEvent` (a clear through `update_attribute(attr, None)` emits only the latter); read the limit once per command inside #8's per-shade lock

## 6. End to end through real ZHA (Part 3 §5b item 2)

- [x] 6.1 In the #5 harness, write a failing test: set the closed limit to 14 through ZHA's "Stops at" control (`number.set_value`, #7), call `cover.close_cover` on the real ZHA cover entity, assert the wire carried `go_to_lift_percentage(84)`, let the simulated motor (which ignores the remote-set stop) arrive at raw 84, and assert the `cover.*` state is `closed` with `current_position` 0
- [x] 6.2 Write a failing harness test that `cover.set_cover_position(50)` with Stops at 14 sends raw lift 41 and the entity then reports position 50
- [x] 6.3 Write a failing harness test that with no limit set, `cover.close_cover` sends the released quirk's frame (`up_open`) and the state machine behaves as stock
- [x] 6.4 Make all three pass; port from `oldcode/` only code that passes these tests unchanged in intent

## 7. Verification

- [x] 7.1 `ruff check` clean under upstream zha-device-handlers rules; no WARNING-level logging in normal operation; comments match code (Part 3 §3c)
- [x] 7.2 Map each spec scenario to a test name in the PR description; confirm Part 3 §5a items 1–5 and 16 and §5b item 2 are covered *Scenario → test map in PR #25's description.*
