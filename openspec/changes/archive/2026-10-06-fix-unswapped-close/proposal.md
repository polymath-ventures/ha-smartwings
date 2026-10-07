## Why

With no closed limit set, U sends a close as the released vendor quirk does: `down_close` swapped onto `up_open` (0x00). Evidence from the owner's box (issue #34, read-only, 2026-10-06) bears on the close: the deployed v18 quirk sends `down_close` (0x01) unswapped when no closed limit is in force, no shade has one in force, and the owner reports that closes from Home Assistant work. Raw `down_close` (0x01) is therefore known to lower these shades, while the stock swap sends a close as `up_open` (0x00), whose direction is unobserved. The owner closed #4 (hardware test 8a) on this indirect evidence, which settles what the code depends on; no air capture or per-shade trial was recorded.

## What Changes

- With no closed limit set, a close is sent as a plain `down_close` (0x01, no payload), unswapped, and runs to the end of travel.
- Opens stay `go_to_lift_percentage(0)`; closes with a closed limit set stay bounded go-tos; every other command with no closed limit set stays the released quirk's frame.
- "Stock behaviour" (no closed limit set) no longer means the released quirk's close frame; a clear restores that behaviour, so a close after a clear is the plain `down_close`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `closed-limit-enforcement`: with no closed limit set, a close is `down_close` unswapped; the vendor swap is no longer an allowed command-ID substitution.
- `closed-limit-capture`: a close after a clear is `down_close`, not the released quirk's frame.
- `stops-at-control`: a close after a clear is `down_close`, not the released quirk's frame.

## Impact

- `quirk/zhaquirks/smartwings/wm25lz.py` and its bundled copy: `_translate()` and the docstrings.
- Tests over the quirk and the real Home Assistant + ZHA harness: the harness motor now models the real units (raw `down_close` lowers) by default.
- Docs: Part 1 §3c and §8 (8a), README limitations.
