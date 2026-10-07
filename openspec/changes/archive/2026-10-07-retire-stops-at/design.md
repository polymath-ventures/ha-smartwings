## Context

U (the quirk) and I (the integration) were built around one measured premise, Part 1 §3a: over Zigbee, these motors ignore the closed limit set with the remote. U therefore kept a second closed limit, published as the 0xFC01 contract and shown as ZHA's `number.*_stops_at`. It bounded every close and go-to short of that limit, and scaled the displayed position to it. I captured, cleared and changed that limit and watched its control. On 2026-10-06 (#54), live, the premise failed. `go_to_lift_percentage(100)` and raw `down_close` stopped the Office Shade at its remote-set lower limit, which it then reported as lift 100. The guest blackout's close from Home Assistant stopped at its remote limit too. The motor scales Zigbee positions between its remote-set limits and enforces them. The owner decided to retire the feature, provided Open, Close, Stop and the slider work on the shade cards.

This change builds on #53 (`fix-delivery-stale-position`, still under review): send once, judge after the travel time, re-send once. Its delivery and readback stay as they are. Only their closed-limit clauses go.

## Goals / Non-Goals

**Goals:**
- Remove every part of "Stops at" from U, I, the tests, the specs and the user docs.
- Home Assistant's Open, Close, Stop and slider work through the real ZHA cover entity, with no error on the firmware's double reply, including Stop's.
- Detect "quirk not loaded" without the 0xFC01 contract.

**Non-Goals:**
- Changing #51's delivery or readback (timings, budget, re-send rule).
- Setting the motor's limits from Home Assistant. The remote does that (SmartWings' guide). Nothing in the radio firmware sets them (firmware analysis §5).
- Migrating stored stops. None exists on the owner's box (below).

## Decisions

### D1. Commands go out as ZHA sends them; opens are `up_open`, not `go_to_lift_percentage(0)`

U passes `up_open`, `down_close` and `go_to_lift_percentage` through unchanged, with no scaling, and keeps the vendor quirk's swap unused. ZHA's cover already sends open as `up_open`, close as `down_close` and position `p` as `go_to_lift_percentage(100 - p)` (`zha/application/platforms/cover/__init__.py`). That is the stock behaviour the owner asks us to match.

Opens were `go_to_lift_percentage(0)` for two reasons. Raw `up_open`'s direction was unobserved, and one unit ("Right master blackout") stalled partway on `open_cover` three times on one day, while a go-to 0 reached the top (Part 1 §3b, DH:210-222). The first reason is gone: raw `up_open` from lift 71 raised the Office Shade to the top (#51, session B, Part 1 §3c). The second is one unit on one day, and it was never reproduced **[open]**. It was also seen under a handler that may have sent the swapped frame, and before the remote limits were known to govern Zigbee travel. Against that, a go-to 0 and `up_open` end at the same place, the upper limit set with the remote. Keeping the substitution keeps a translation layer whose only other job is gone. **Decision: pass `up_open` through.** If the stall recurs, the slider at 100 % still sends a go-to 0 (ZHA's own mapping), and the case is reopened with its evidence. Alternative considered: keep go-to 0 for opens only. Rejected: it is unmeasured insurance that costs a translation path, its tests and a Part 3 exception to "match stock".

The readback still needs a target. An open's is lift 0, a close's lift 100 (the remote-set lower limit, as the shade reports it), and a go-to's is its lift. A go-to without a valid lift is sent once, unverified, as before.

### D2. Stop: once, never synthesised, and its second reply is SUCCESS

Stop stays a pass-through: one frame, no lock, no read, no re-send. It drops a pending re-send (#51). For a standard Stop the radio forwards the frame and the motor halts (Part 1 §3d, #51), so the 0x81 that follows (or precedes) the SUCCESS is the same firmware bug as for movements (firmware analysis §3). U reports it as SUCCESS through the same mapping, so `cover.stop_cover` takes ZHA's success path (it raises on anything else, `cover/__init__.py:733-735`). A manufacturer-specific Stop is refused by the radio with a genuine 0x81 and not forwarded (firmware analysis §2), so its reply still passes through unchanged. Alternative considered: refuse it unsent like a manufacturer-specific movement. Rejected: nothing sends one, and passing it through is the smaller change.

### D3. "Quirk not loaded" by quirk ID, not by the 0xFC01 contract

U declares `QUIRK_ID = "smartwings.wm25lz"` with `QuirkBuilder.exposes_feature()` (`zhaquirks/builder/builder.py:960-967`), following ZHA's quirk-ID naming (`zha/quirks.py`, "Quirk IDs"). ZHA exposes it in two places, and I reads each:

- **On the device.** ZHA's `Device.exposes_features` (`zha/zigbee/device.py:427-431`) is the v1 `quirk_id` plus the v2 quirk's features (`QuirkV2Device._quirk_exposes_features`, `zhaquirks/builder/device.py:50-51`). ZHA's own entity discovery matches on it (`zha/application/discovery.py:233-243`), and ZHA shows it in device diagnostics. I decides that U is active for a shade iff `QUIRK_ID in proxy.device.exposes_features` on the device ZHA holds now. That device is rebuilt at every ZHA reload and re-read at every discovery.
- **In the registry.** For "zha-quirks provides U", I scans `zha.quirks.DEVICE_REGISTRY` as before: an unrestricted WM25/L-Z entry not loaded from `custom_quirks_path`. But it reads `entry.zha_device_factory.quirk_definition.exposes_features` (`QuirkV2Factory`, `zhaquirks/builder/device.py:140-150`) instead of looking for an 0xFC01 cluster among the transforms. Anything missing on the way answers False. That only withholds a note: it never deletes a file.

One string replaces the nine-term contract, and I mirrors it in `const.py` with a test that keeps the two equal. No class, module or file name is used. Alternatives considered:
- (a) `Device.quirk_class` (`module:label`). Upstream, U's module would be `zhaquirks.smartwings.wm25lz`, the vendor quirk's module, and the v2 label is the builder's formatting `"(Smartwings / WM25/L-Z)"`, not a declaration.
- (b) The WindowCovering cluster's class name. Part 3 §1c forbids it, and it breaks on any rename.
- (c) "The registry entry was loaded from `custom_quirks_path`". It answers wrongly once U ships upstream.

The registry entry ZHA stamps on the zigpy device (`QUIRK_REGISTRY_ENTRY_ATTR`) would also work. It is a private attribute name, though, and `exposes_features` is the device's public view of the same declaration.

Risk: if upstream review drops or renames the quirk ID, I reports U as missing once zha-quirks ships it. Mitigation: the ID goes into the upstream PR as part of the quirk, and the integration's test pins the mirrored value.

### D4. What remains

- **U:** the `WM25LZWindowCovering` cluster with #51's delivery and readback, unchanged except that a command is no longer translated (D1) and that a standard Stop's 0x81 is reported as SUCCESS (D2). It keeps the double-reply mapping, the refusals (0x04, 0x07, 0x08 and manufacturer-specific movements on every path), the read retry, the radio budget and the tracking hooks. Lifts are cached as received; ZHA's `100 - lift` is the only conversion. It keeps `DoublingPowerConfigurationCluster` and adds the quirk ID. Removed: `LiftScale`, `ClosedLimitCluster`, the number entity, the closed-limit constants, the rescale on change, and the re-send's closed-limit guard. Translation no longer reads anything; it still happens once the command holds the shade's lock, which serialises delivery as before (`command-delivery`), so the delivery code #53 reviews is left as it is.
- **I:** the single-entry config flow (no options flow), shade discovery, the quirk installer and its five Repairs issues, and the `quirk_not_loaded` Repairs issue, detected by D3. Removed: `contract.py`, `store.py`, `services.py`, `services.yaml`, `icons.json`, `pending_clears.py` and `stops_at_watch.py`. Also removed: the Change-stop options flow, `async_setup` (it only registered the actions), the remove-entry stop clearing, the per-shade status signal and `ShadeStatus` (nothing consumes them any more), and the shade's cover entity id.

### D5. The harness motor honours the remote's limits

`MotorSim` already works in lift 0-100 between its ends. What changes is what that space means: 0 is the upper limit and 100 the lower limit set with the remote, and the motor scales go-tos between them (#54). The docstring says so instead of "it has no closed limit", and a harness test pins it: `down_close` and `go_to_lift_percentage(100)` both stop at lift 100, and `up_open` at 0.

### D5a. The spec folders

The four retired capabilities lose every requirement. OpenSpec rebuilds a spec from its deltas and rejects a spec with no requirements, so at archive the four folders under `openspec/specs/` are deleted by hand rather than left empty, while the change's four REMOVED deltas are kept in the archived change as the record of what was removed and why (task 6.2 gives the procedure).

## Risks / Trade-offs

- [The run-to-limit open stall (Part 1 §3b) recurs on a unit] → the slider at 100 % is a go-to 0 and still opens it. The test plan revives its deferred `up_open` stall count (old 8e) inside `REPEAT-DOWN-CLOSE-STALL`, so a recurrence is recorded and the decision revisited with evidence.
- [A shade whose limits were never set with the remote closes to its factory end] → README setup step, linking SmartWings' guide (DOWN+STOP 5 s, move, DOWN+STOP 2 s; the same with UP for the top). Known limitations says that Home Assistant cannot set or read the limits.
- [A user of a test build has an 0xFC01 row and a `number.*_stops_at` registry entry] → the row is inert: no cluster reads it. ZHA shows the number entity as unavailable until the user deletes it. Troubleshooting says so.
- [#53 changes the same quirk file while under review] → this branch rebases onto main after #53 merges. Delivery and readback code is left as #53 has it, apart from the D1 and D2 call sites.

## Migration Plan

Nothing to migrate. The owner's box never ran a build with 0xFC01: `zigbee.db` has no 0xFC01 row (Part 1 §3c, #34), and the deployed v18 quirk sends `down_close` unswapped. Deploying is the integration's normal quirk update: the installer replaces its outdated file and asks for one restart. Rollback is reinstalling the previous release. A stop set under it would have to be set again, but none exists.

## Open Questions

- Whether a move made with the remote is reported (Part 1 §3f). It does not affect this change: a refresh shows it either way.
