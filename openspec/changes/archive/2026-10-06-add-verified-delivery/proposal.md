## Why

SmartWings WM25/L-Z motors usually ignore the first command frame after idling. In the last measured batch, frame 1 moved the shade zero times out of three, and a re-send worked every time (docs Part 1 §3e). Reads are lost the same way. The shades are sleepy end devices, with receiver-on-when-idle clear. A one-shot command therefore looks broken to the user. Part 3 §2j makes "one press is one action" the quirk's job, and §2k requires a command that cannot take effect to fail visibly instead of animating a stationary shade.

## What Changes

- Add a delivery layer to the SmartWings WindowCovering cluster in the quirk (U). It is used for every command that has a target lift: send the frame, read the motor's live position back, and re-send only when the reads show no movement toward the target. The number of frames is bounded.
- Make every safety rule from the old handler structural: an unreadable position is not movement (F3), movement away from the target is not success (F4), success is never reported after no movement (F5), and an unverifiable command is sent at least twice (F6).
- When a command cannot be made to take effect, fail it through ZHA's standard path: return a Default Response with `Status.FAILURE`, so ZHA clears its transition, Home Assistant shows ZHA's standard error, and the cover never animates (§2k; owner decision 2026-10-05: match stock Home Assistant behaviour).
- Serialise commands per shade with a lock that delivery's own frames and reads never take again (F2). Shades are independent, so one stuck shade never delays another (§3g).
- Give each command a documented worst-case duration, built from named constants and asserted by a test using virtual time (§3g).
- Retry an attribute read once on a lost frame, including Home Assistant's own refreshes.
- Parse zigpy's real `read_attributes` response shape. Lift 255 ("unknown") and other out-of-range values count as unreadable (§5a item 17).
- Normal operation, re-sends included, logs at DEBUG. Nothing logs at WARNING unless something is actually wrong (§3c).
- Pass through, once and unverified, any command that has no target lift: Stop, tilt and anything unrecognised (§2l). Deciding which commands carry a target is the job of `add-closed-limit-enforcement`.

## Capabilities

### New Capabilities
- `command-delivery`: How the quirk makes a WindowCovering command take effect on WM25/L-Z hardware. Covers verified send and re-send, the evidence rules for "it moved", failure signalling, read retry, per-shade serialisation and the latency bound.

### Modified Capabilities
<!-- None: openspec/specs/ is empty. -->

## Impact

- **Code:** the quirk's WindowCovering cluster class (`zhaquirks/smartwings/wm25lz.py` layout in this repo). It adds the delivery seam that `add-closed-limit-enforcement` (#9) calls with a wire command and a raw target lift, and the live-read seam that `add-final-position-readback` (#10) reuses.
- **Tests:** U's command-path tests in upstream zha-device-handlers style, run against the real cluster class and zigpy's real request path with decoded frames, covering Part 3 §5a items 6–14 and 17. Entity-layer checks (no animation on failure, the shade named in the error) run on the real-ZHA harness from #5.
- **Dependencies:** none new. Targets zigpy 2.3.x, zha 2.3.x, zha-quirks 2.3.x and Home Assistant 2026.10.
- **Blocked by:** #2 (environment) and #5 (harness).
- **Ported from `oldcode/`:** the evidence rules, the direction check, the double send for unverifiable commands, the final grace look and the read retry. Each is ported only once a failing test exists for it.
- **Dropped from `oldcode/`:** WARNING logs in normal operation, the one-time "handler active" WARNING, the live read in `async_initialize` (that hook does not fire for cache-loaded devices), the guessing at response shapes in `_live_lift`, and the blanket `except Exception` handlers that turned programming errors into "unreadable".
