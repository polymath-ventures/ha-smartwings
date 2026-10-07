## Why

The radio firmware analysis (#43, `docs/evidence/firmware-analysis.md` §3, §6) and session A on the Office Shade (2026-10-06) show three things the quirk gets wrong (issue #45):

- Every Window Covering command the radio handles draws two Default Responses with the same TSN: SUCCESS, then UNSUP_CLUSTER_COMMAND (0x81), because each handler sends its own SUCCESS and then returns "not handled". zigpy returns whichever arrives first (session A: Stop drew SUCCESS on some sends and 0x81 on others). When the 0x81 wins, U hands it to ZHA, whose cover raises `Failed to open cover: <Status.UNSUP_CLUSTER_COMMAND: 129>` (`zha/application/platforms/cover/__init__.py:637-640`, and `:663-666`, `:692-697` for close and set position) although the radio forwarded the command and the shade moved.
- `go_to_lift_value` (0x04), `go_to_tilt_value` (0x07) and `go_to_tilt_percentage` (0x08) make the radio send malformed serial frames that can repeat the previous command or corrupt the next. U passes them through (0x04 only with no closed limit set).
- Battery: the issue says U's doubling reports twice the motor's percentage. Checked against the code, it does not; see "Battery" below.

## What Changes

- For an open, close or go-to, a Default Response UNSUP_CLUSTER_COMMAND to the frame is the firmware's second reply, which like the SUCCESS carries no motor state: delivery counts it as an answer, never as a failure or a reason to re-send, and reports SUCCESS to ZHA, so ZHA's cover takes its stock success path (the `res[1] is not Status.SUCCESS` checks above). A verified movement still rests on the position reads: it succeeds when travel is seen, whatever the replies, and fails with FAILURE when it is not. The blind path (no baseline) and a go-to without a valid lift read no position, so their SUCCESS reports the radio's acceptance of a frame, not movement, exactly as before; both send only `go_to_lift_percentage` or `down_close`, which the radio handles, so the mapping applies to them too.
- A manufacturer-specific open, close or go-to, which a caller can request through `command(manufacturer=…)`, is refused up front like 0x04/0x07/0x08: the radio refuses every manufacturer-specific Window Covering frame with a genuine 0x81 and forwards nothing (firmware analysis §2), so sending one is pointless. Every movement frame that goes out is therefore standard, and the 0x81 mapping applies to all of them. A manufacturer-specific Stop keeps Stop's pass-through.
- Stop stays a pass-through, unchanged: zigpy's first matched reply reaches ZHA as it is. Today HA therefore shows no error when SUCCESS wins and `Failed to stop cover: <Status.UNSUP_CLUSTER_COMMAND: 129>` when the 0x81 wins (`cover/__init__.py:733-735`). Its user-facing behaviour is decided after `STOP-WHILE-MOVING`.
- 0x04, 0x07 and 0x08 are refused in the quirk's `request()`, before anything is sent and whatever path they come by, with the Default Response a device gives for a command it does not support (UNSUP_CLUSTER_COMMAND). ZHA reports that as for any unsupported command: `Failed to issue cluster command with status: …` from its cluster-command service (`zha/zigbee/device.py:1485-1487`). A refusal takes no lock and leaves tracking and the baseline alone. `go_to_lift_value` is no longer a movement command, so the closed limit's "cannot be bounded" refusal now covers only a go-to without a valid lift.
- The harness motor can send the double reply, in either order (`MotorSim.double_reply`).

### Battery

No change to behaviour; the reasoning is recorded so the question stays closed:

1. The radio copies the motor's byte into BatteryPercentageRemaining (0x0001/0x0021) unchanged (firmware analysis §6). The Office Shade's cache holds 168 under the vendor quirk's doubling, so the radio sent 84, which as whole percent is 84 %. Whole percent is inferred, pending a raw read (`POWER-BATTERY-UNITS`).
2. ZCL counts 0x0021 in half percent (200 = 100 %). `DoublingPowerConfigurationCluster._update_attribute` (zha-quirks 2.3.0, `zhaquirks/__init__.py:254-266`) doubles every value written to it, by read or report: 84 is cached as 168, which is correct ZCL.
3. ZHA's battery sensor shows half the cached value (`Battery.formatter`, `zha/application/platforms/sensor/__init__.py:800-806`, "per zcl specs battery percent is reported at 200%"): 168 is shown as 84 %, the motor's own figure.
4. zigpy restores the cache from its database without `_update_attribute` (`zigpy/appdb.py:959`, `_attr_cache.set_value`), so a restart does not double it again.

So the doubling is the correct ×2 conversion, and HA already shows the motor's percentage. Removing it would show half (42 % for the Office Shade). U keeps it; a new end-to-end test pins 84 → 84 % and 100 → 100 %. If `POWER-BATTERY-UNITS` finds the motor's byte is not whole percent, this is the place to change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `command-delivery`: the firmware's second reply is not a failure; 0x04, 0x07 and 0x08 are refused unsent; pass-through now covers Stop and unknown commands only.
- `closed-limit-enforcement`: `go_to_lift_value` is refused always, not only with a stop set, and is no longer a movement command; the battery requirement records why the doubling is kept.

## Impact

- `quirk/zhaquirks/smartwings/wm25lz.py` and its bundled copy.
- Harness: `tests/zha_harness/motor.py` (`double_reply`, `replies()`), `tests/zha_harness/radio.py` (sends every reply).
- Tests over the quirk and the real Home Assistant + ZHA harness.
- README: Known limitations (Stop; refused commands).
