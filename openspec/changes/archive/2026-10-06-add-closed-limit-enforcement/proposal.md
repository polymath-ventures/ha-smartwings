## Why

SmartWings WM25/L-Z motors ignore the closed limit set with their remote whenever a command
arrives over Zigbee, by both run-to-limit and go-to-percentage, and drive past it until the
fabric bunches (docs Part 1 §3a). The hub must supply the stop itself, in the one layer every
caller passes through (the quirk's WindowCovering cluster, Part 2 §2), and a shade resting at
its stop must answer "closed" (Part 3 §2h, confirmed by the owner 2026-10-05). Today nothing
reports closed at the stop (review item 2f), so voice, HomeKit and automations get the wrong
answer. Issue #9.

## What Changes

- With a closed limit set, every movement command a caller can send is translated so the motor
  is never told to go past the stop: `down_close` and every `go_to_lift_percentage` become an
  absolute go-to no further than a fixed margin short of the stop; `go_to_lift_value` is
  refused (Part 3 §2g, §1a-2).
- Every open, with or without a closed limit, goes out as `go_to_lift_percentage(0)` (raw lift 0)
  through #8's delivery layer. Owner decision 2026-10-05: Part 3 §3a forbids changing a command's
  direction or end point versus the released quirk, not its form; go-to 0 has the same direction
  and end point, and reached the top first time where run-to-limit `up_open` stalled (Part 1 §3b,
  DH:210-222).
- With a closed limit set, the lift position ZHA sees is rescaled so the stop is 100 % lift
  (HA position 0, "closed") and positions between the open limit and the stop are scaled
  linearly; incoming go-to percentages are un-scaled before transmit. Changing or clearing the
  stop rescales the displayed position at once (Part 3 §2h).
- With no closed limit set, every frame other than an open is byte-identical to the released
  vendor quirk (`zhaquirks.smartwings.wm25lz`, zha-quirks 2.3.x); a close keeps its swapped
  frame (`up_open`) until hardware test 8a (#4) reports, and the displayed position is the raw
  lift (Part 3 §3a).
- Stop (0x02) is passed through once, unchanged and unverified; no stop is ever synthesised
  (Part 3 §2l, F16).
- All conversions between raw lift, scaled lift and HA cover position live in one pure module
  (F1). Command-ID handling and lift values are never used to correct each other (F18).
- Translated movement commands are handed to the delivery layer from `add-verified-delivery`
  (#8) with their target in raw lift.
- U is a quirks v2 quirk (ADR 0001): the same `QuirkBuilder` chain that adds #7's closed-limit
  cluster (`0xFC01`) replaces the WindowCovering cluster with the enforcement subclass, which
  reads the stop from that sibling cluster. The v2 quirk supersedes the released v1 vendor quirk,
  so it also keeps the vendor quirk's doubled battery reporting.

## Capabilities

### New Capabilities

- `closed-limit-enforcement`: how U turns caller commands into wire frames given the shade's
  closed limit (set or unset), how lift position is rescaled for display when a limit is set,
  and the single conversion module that owns every coordinate-space transform.

### Modified Capabilities

<!-- None: openspec/specs/ is empty. Depends on closed-limit-contract (#7) and
command-delivery (#8), introduced by sibling changes. -->

## Impact

- Code: the SmartWings v2 quirk in U (`quirk/zhaquirks/smartwings/wm25lz.py`): the replaced
  WindowCovering cluster's `command()` translation and `_update_attribute()` for attribute
  0x0008, the doubled battery reporting carried over from the vendor quirk, and a new pure
  conversion module (`LiftScale`).
- Depends on: `add-closed-limit-contract` (#7) for reading the stop and its range;
  `add-verified-delivery` (#8) for sending translated movement commands; the real-ZHA harness
  (#5) for end-to-end tests. Consumed by: `add-closed-limit-capture` (#13), which needs the raw
  position; `add-final-position-readback` (#10), whose reads update the cache through the same rescaling while comparing the raw values `read_attributes` returns.
- User-visible: with a stop set, the cover slider's 0 is the stop, "closed" is reported at the
  stop, and the slider rescales when the stop changes. With no stop set, nothing changes from
  stock.
- Upstream: the unset path's byte-identity with the released quirk is what lets the upstream PR
  (#17) claim no behaviour change for users who never set a stop.
