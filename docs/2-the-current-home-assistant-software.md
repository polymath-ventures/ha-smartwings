# Part 2: The Home Assistant software as it stood on 2026-10-05 (historical)

> **Historical record, not current behaviour.** This part describes the software stack and our earlier deliverable (since removed from the repository) as they stood on 2026-10-05, including the "Stops at" `number` entity, the capture and clear actions and the closed-limit quirk. All of those were retired by #54 (OpenSpec change `retire-stops-at`) once Zigbee commands were seen to stop at the limits set with the remote (Part 1 §3a). Present-tense statements below about "our integration", "our quirk" or "the repo" describe that earlier code. For what the software does now, read the [README](../README.md); for how the motors behave, [Part 1](1-the-devices.md). Sections 1a-1e, 1h and 2, about zigpy, zha-quirks and ZHA themselves, still hold.

What each piece is, what each is correctly called, and why the arrangement of 2026-10-05 could not deliver the behaviour on its own.

Written 2026-10-05. The installed versions cited here are the development environment's: Home Assistant 2026.10.0b0, zigpy 2.3.0, zha 2.3.0 and zha-quirks 2.3.0 (dist-info in `venv314/.../site-packages`). The owner's box ran Home Assistant 2026.9.4 with zha 2.2.2 on 2026-10-05. On 2026-10-06 it was upgraded to Home Assistant 2026.10.0b2, whose ZHA manifest pins `zha==2.3.0`. The source citations were not re-checked against those versions. HA's own ZHA manifest pins `"requirements": ["zha==2.3.0", "zha-quirks==2.3.0"]` (`homeassistant/components/zha/manifest.json:26`). Code citations below are to those installed files unless marked as the repo (`~/code/ha-smartwings`). The repo was being changed while this was written. Statements about it are made as behaviour, with file and function names, and they were checked against the files as they stood on 2026-10-05. That code has since been removed from the repository (#16); its paths below are as they stood then.

## 1. Terminology: what each piece is

No piece of this stack is a "driver" in the usual sense. Home Assistant's documentation and these projects do not use that word for any of them. The closest thing to a driver is the radio library that talks to the coordinator's USB/serial hardware (bellows, zigpy-znp, zigpy-deconz and others, listed in the ZHA manifest). On the owner's box it is bellows, driving the Home Assistant Yellow's onboard EZSP radio (reported by the HA agent on 2026-10-05, not independently verified). Nothing in this project touches that layer.

| # | Piece | What it is | Correct term | Evidence |
|---|---|---|---|---|
| 1a | **zigpy** (`zigpy` 2.3.0) | A Python implementation of the Zigbee application layer, run on the hub: device database, ZDO, and the Zigbee Cluster Library (ZCL) with every standard cluster's commands and attributes. | **Library.** "ZCL stack" is accurate for the part used here. | WindowCovering is defined at `zigpy/zcl/clusters/closures.py:736-827`. Cluster command methods are generated at `zigpy/zcl/__init__.py:1838-1851` as `functools.partial(self.command, cmd.id)`, which is why overriding `command()` intercepts `up_open()`, `down_close()` and the rest. The device database is `zigpy/appdb.py`. |
| 1b | **zha-device-handlers** (repo `zigpy/zha-device-handlers`; PyPI distribution `zha-quirks`; import name `zhaquirks`) | A shared library of per-device corrections ("quirks") for devices that do not behave like the standard. Each quirk matches a device signature and substitutes corrected cluster classes. ZHA installs it as a pinned requirement. | **Library of quirks.** The project uses "quirk" and "device handler" interchangeably. Both are its own terms, not ours. | Package docstring: "Quirks implementations for the ZHA component of Homeassistant." (`zhaquirks/__init__.py:1`). The vendor file's docstring: "Device handler for Smartwings blinds." (`zhaquirks/smartwings/wm25lz.py:1`). |
| 1c | **The SmartWings quirk** in that library: module `zhaquirks.smartwings.wm25lz`, class `WM25LBlinds`, replacement cluster `InvertedWindowCoveringCluster` | A **v1 quirk**: a `CustomDevice` subclass with a `signature` and a `replacement`. It doubles the battery percentage and swaps `up_open`/`down_close`. That is all it does. | **Quirk** (or device handler). "Vendor quirk" means the quirk *for* this vendor's device. Authorship is **not established**; nothing read here says SmartWings wrote it. Check `git log` on the file before saying so. | The whole quirk is 111 lines, with the swap at `zhaquirks/smartwings/wm25lz.py:34-63` and the replacement at `:94-110`. v1 registration: `CustomDevice.__init_subclass__` (`zhaquirks/legacy/__init__.py:75-79`). |
| 1d | **The zha library** (repo `zigpy/zha`; distribution `zha` 2.3.0) | The Zigbee gateway, device and entity logic used by Home Assistant's ZHA integration. The cover entity's state machine, reporting configuration and command calls live here, not in HA core. | **Library.** | `zha/application/platforms/cover/__init__.py`: reporting config `:151-160`, position conversion `:332-347`, state determination `:375-417`, commands `:634-738`. |
| 1e | **ZHA, the Home Assistant integration** (`homeassistant.components.zha`) | The core integration that owns the config entry, creates HA entities from the zha library's entities, and hands zhaquirks and `custom_quirks_path` to the gateway. | **Integration**, in HA's own sense: a component in `homeassistant/components/` with a manifest and config entries. It is part of Home Assistant core. | It passes `custom_quirks_path` and `setup_function=zhaquirks.setup` at `homeassistant/components/zha/helpers.py:1420-1421`. Its `ZhaCover.async_close_cover` calls `self.entity_data.entity.async_close_cover()` (`homeassistant/components/zha/cover.py:142-145`). |
| 1f | **Our integration** (`custom_components/smartwings`, repo `polymath-ventures/ha-smartwings`; as of 2026-10-05, since removed) | A Home Assistant **custom integration**. It is installed into `/config/custom_components/`, optionally through HACS. On 2026-10-05 it added one `number` entity per shade, the `smartwings.capture_closed_position` and `smartwings.clear_closed_limit` actions, and a bundled copy of our quirk. | **Custom integration.** That is HA's term for an integration not shipped in core. HACS is a community installer, not part of HA. | `manifest.json` declares `"dependencies": ["zha"]`. `__init__.py` imports `quirks/smartwings_wm25lz.py` at module load (`__init__.py`, bottom of `_handler_already_supplied`). |
| 1g | **Our quirk** as of 2026-10-05 (`custom_components/smartwings/quirks/smartwings_wm25lz.py`, since removed: `SmartWingsWM25LZCover`, cluster `ReadbackWindowCoveringCluster`) | A **v1 quirk** with the same signature as 1c. It added read-back verification and the closed-limit behaviour (both since replaced: the current quirk is a v2 quirk with no closed limit, see the README). It can reach ZHA in two ways: imported by our integration, or placed in the folder named by ZHA's `custom_quirks_path`. | **Quirk.** It is a **custom quirk** when loaded through `custom_quirks_path`, which is ZHA's own term for that option. | `custom_quirks_path` is passed through at `helpers.py:1420`. Custom quirks are imported at `zhaquirks/__init__.py:594-615`. |
| 1h | **"Home Assistant code"** | Anything under `homeassistant/`: core, the entity model, the registries, and the ZHA integration (1e). | — | — |

Two smaller points. "Quirks v2" is the declarative `QuirkBuilder` API (`zhaquirks/builder/builder.py:329`, re-exported through `zigpy/quirks/v2/__init__.py:25,48`). It is not a different library. "Custom quirk" is a quirk loaded from `custom_quirks_path`, not a separate kind of object.

### 1i. The local clone is not "upstream as it exists today"

`~/code/zha-device-handlers` is on branch `dev` (`.git/HEAD`). Its `zhaquirks/smartwings/wm25lz.py` is 286 lines and adds read-back verification. **It also inverts the position axis** (`_update_attribute` caches `100 - value`, and `_read_lift` returns `100 - value`) on the premise that "the motor reports … lift as percent OPEN" (lines 37-40 of that file). The measurements contradict that premise (Part 1 §3g; DH:248-253). The same file also treats an unreadable position as movement (`_started_moving` returns `True` on `None`), which the record identifies as a defect (DH:41-45, DH:76-78). This is the unpublished patch described at DH:389-396. It is not released code, and **it must not be submitted as it stands.** The released quirk is the 111-line file in `zha-quirks` 2.3.0. Whether the clone's change is committed could not be checked, because git commands were not permitted in this session. I also could not check whether upstream `dev` has moved past 2.3.0.

## 2. How a cover command reaches the motor

All of the following is **[source]**:

1. A dashboard tap, a voice command, a scene or an automation calls `cover.close_cover`. HA's entity component dispatches it to the entity object that ZHA owns, `ZhaCover.async_close_cover` (`homeassistant/components/zha/cover.py:142-145`).
2. That calls the zha library's `Cover.async_close_cover` (`zha/.../cover/__init__.py:660-670`). It calls `self._cluster.down_close()` and treats any status other than SUCCESS as failure.
3. `self._cluster` is `endpoint.zigpy_endpoint.in_clusters[WindowCovering.cluster_id]` (`:194`). It is the zigpy cluster object whose class was chosen by the quirk that matched the device.
4. `down_close()` resolves to `cluster.command(0x01)` (`zigpy/zcl/__init__.py:1851`).

So the **only** code every caller passes through, other than ZHA itself, is the cluster class the quirk installs. That is the layer where per-command behaviour can be changed without patching ZHA and without creating a second entity.

## 3. Why the arrangement of 2026-10-05 failed

### 3a. The released vendor quirk cannot express "stop here"

*Superseded by #54 (2026-10-06): the motor stops at the limits set with its remote for Zigbee commands too (Part 1 §3a), so no "stop here" is needed in software. Kept as the record of the reasoning at the time.*

It has no per-shade state. It declares no attribute and reads no setting. Its one behaviour is a constant mapping of command IDs (`wm25lz.py:49-54`). A close goes out as a run-to-limit frame, and the firmware runs past the stored stop (Part 1 §3a). The standard cluster offers nowhere to put the stop either, because `installed_closed_limit_lift` is read-only (`closures.py:782-784`) and the device does not honour it. Making "stop here" expressible at that layer requires three things:
1. A per-device value the cluster class can read.
2. Command logic that turns a close into a bounded go-to.
3. A way for that value to be set.

The released quirk has none of the three.

**Which layer could fix it.** The quirk layer can carry items 1 and 2. A quirk is library code that ZHA imports without any handle on Home Assistant, so it **cannot** read HA configuration, entity states or files. A file read was tried here and retired (ARCH:40-47). The value therefore has to live on the device object, as a cluster attribute in zigpy's attribute cache. zigpy persists that cache in its own database and restores it at startup (`appdb.py:771-801`). Our quirk does exactly this with manufacturer-specific attribute 0xFC01 (`CLOSED_LIMIT` and `_closed_limit()` in the repo's quirk).

**Item 3 can also live upstream [source; proven by the #6 spike, ADR 0001].** Quirks v2 can declare a `number` configuration entity bound to a cluster attribute (`QuirkBuilder.number`, `zhaquirks/builder/builder.py:762-815`). ZHA then creates that entity on the shade's own device, and its writes go through `write_attributes` (`zha/application/platforms/number/__init__.py:336-341`). On a `LocalDataCluster` that write stays local: `zhaquirks/__init__.py:161-177` stores it in the cache and sends nothing over the air. If the setting were declared that way upstream, ZHA itself would create the "Stops at" entity, and zigpy's database would persist it. The custom integration would then not need its own control; it keeps capture, clearing, the change-confirmation dialog and the missing-quirk warning (Part 3 §1b). The #6 spike verified this path for this device against real ZHA (`tests/spikes/test_quirks_v2_spike.py`); ADR 0001 adopts it, with one condition the source did not show: the attribute needs `manufacturer_code=0x1002` or zigpy loses it on restart.

### 3b. A Home Assistant entity cannot be intercepted by another integration

HA has no supported mechanism for one integration to wrap or pre-empt another integration's entity service calls. `cover.close_cover` is dispatched to the entity object that ZHA registered (step 1 above). The alternatives each break a stated requirement:
1. A template cover, a group or a wrapper entity is a parallel entity. The real `cover.*` stays callable and still runs past the stop, and every dashboard, voice target and automation has to be pointed at the substitute.
2. Patching ZHA's classes at runtime is unsupported and breaks on updates.

An integration can therefore supply the *setting* and the *user interface*. It cannot supply the *behaviour*. The behaviour has to be in the quirk (ARCH:40-42).

### 3c. Setup order: ZHA builds every device before a custom integration can register a quirk

The following was traced in source and is **[source]**. It has not been run against a real ZHA; see §4.

1. `manifest.json` in the repo declares `"dependencies": ["zha"]`. HA processes dependencies before importing a component (`homeassistant/setup.py:333`). A dependency's setup includes its config entries (`setup.py:467-482`). Only then is our module imported (`setup.py:341`).
2. ZHA's entry setup first calls `Gateway.async_from_config`. That runs the quirks provider, `zhaquirks.setup`, with `custom_quirks_path` (`zha/application/gateway.py:219-241`; `homeassistant/components/zha/__init__.py:166`). It then calls `zha_gateway.async_initialize()` (`__init__.py:197`).
3. `zhaquirks.setup` imports every zhaquirks module. This queues v1 quirks in `PENDING_LEGACY_QUIRKS` through `CustomDevice.__init_subclass__` (`zhaquirks/legacy/__init__.py:75-79`). The same function then drains them into ZHA's resolver registry with `_register_pending_quirks()`, and imports and drains custom quirks the same way (`zhaquirks/__init__.py:556-615`).
4. Initialisation loads zigpy's database. For every known device, it calls `_resolve_device`, which applies the matching quirk (`zigpy/appdb.py:776-782`). The resolver is ZHA's registry (`gateway.py:252`).
5. When our integration is imported later, our quirk class registers with zhaquirks' legacy registry and is appended to `PENDING_LEGACY_QUIRKS`. **Nothing drains that queue until `zhaquirks.setup` runs again, which happens only when ZHA itself is set up again.** Every shade has already been built with upstream's `WM25LBlinds`.

**Consequence.** A user who installs only the custom integration gets none of its behaviour after any restart. A ZHA reload applies our quirk until the next restart. ZHA's registry prepends on `register` (`zha/quirks.py:174-191`), so after a reload our later registration wins the match. A re-interview does not apply it, because the queue is not drained. The only setups that apply it on every boot are:
1. The quirk placed in `custom_quirks_path`. This is how the owner's own box works, which is why the problem did not show there.
2. The behaviour shipped in zha-quirks itself.

HA's manifest has no field that makes an integration set up *before* another one. `after_dependencies` points the other way.

**How the repo handled it then** (checked 2026-10-05; the integration now raises a Repairs issue instead, see the README). The defect was no longer silent, but it was not fixed:
1. The integration finds shades by manufacturer and model rather than by our class name (`SHADE_MODELS` and `shade_ieee` in `number.py`).
2. It marks each "Stops at" entity **unavailable** when the loaded quirk does not read the closed limit (`available` and `handler_active` in `number.py`).
3. It posts a persistent notification naming the affected shades and the two remedies (`_async_report_inactive_handler` in `number.py`).
4. It re-applies a restored value when ZHA's `zha_add_entities` signal follows a reload (`async_handler_changed`).

The README of that date stated the limitation and dropped the earlier "one re-interview" claim.

### 3d. Other defects from review R1, as the code stood on 2026-10-05

| R1 item | Then | Now (2026-10-05) |
|---|---|---|
| 1b | Close with no stop set sent unswapped `down_close` | **Fixed at the code level.** It sends the vendor quirk's swapped frame (`up_open`), asserted byte for byte against `WM25LBlinds` in the retired `tests/test_quirk_wire.py`. The physical direction on a real shade is still **open** (Part 1 §3c). Note: the new quirk (U) sends `down_close` unswapped instead (#34). |
| 2a | Capture reported success when nothing was stored | **Fixed.** Every abort raises `HomeAssistantError`. The direct-write fallback raises if nothing was stored. The notification is posted only after a successful store (`capture` in `__init__.py`). |
| 2b | "Stops at" accepted 96-100, which the quirk ignores | **Fixed.** `native_max_value` is `CLOSED_LIMIT_SANITY_MAX` (95), and restore ignores values outside 0-95 (`number.py`). |
| 2c | A stop could not be cleared and outlived the entity and the integration | **Fixed.** A `smartwings.clear_closed_limit` entity action was added. `async_removed_from_registry` clears the attribute. `async_remove_entry` clears it on every shade whose handler reads it. |
| 2d | An over-the-air UNSUPPORTED reply disabled the stop | **Fixed.** `_closed_limit()` removes zigpy's unsupported mark before reading, with a test. |
| 2e | Entity ids were rewritten on every start | **Fixed.** Only ids matching the legacy pattern (`_LEGACY_ENTITY_ID_RE` in `number.py`) are renamed, with tests for both cases. |
| **2f** | A shade resting at its stop never reports "closed" | **OPEN.** ZHA reports CLOSED only at HA position 0 (`zha/.../cover/__init__.py:417`). With Stops at 14, the target lift is 84, so the HA position is 16 and the state is "open" indefinitely. Any automation, voice query or HomeKit bridge asking "is it closed?" gets the wrong answer. The README documents this. Nothing fixes it. |

### 3e. What remained wrong or unproven in the deliverable of 2026-10-05

**3e-i. Deployed, but no result on the real shades is recorded.** A read-only SSH check of the box on 2026-10-05 found the following:
1. Home Assistant 2026.9.4.
2. Version 18 of our quirk (`QUIRK_VERSION = "v18-closed-limit-attribute"`), deployed at 10:18 that day through `custom_quirks_path`. It replaced version 17, which refused closes on shades with no stop set and read the stop from a file (ARCH:3-26).
3. Our integration installed, with nine `number.*_closed_limit` entities, all `unknown`.
4. The Office Shade's stop (14) only in `smartwings_calibration.json`, which version 18 does not read. The owner re-set it through the entity the same day.

No observation of version 18 moving a shade has been recorded. **OPEN.**

**3e-ii. The retired code's ZHA-level tests do not run ZHA.** (Since 2026-10-05 the new suite does: the #5 harness runs real Home Assistant and real ZHA over a simulated shade, and the #6 spike drives `cover.close_cover` through a real ZHA cover entity. What follows describes the retired code.) The retired `tests/test_ha_integration.py` starts a real Home Assistant through `pytest-homeassistant-custom-component`, with real config entries, registries, restore and services. It replaces the ZHA component with `MockModule("zha")` and the gateway with a `FakeGateway` (file docstring, lines 7-12). The cover is a registry entry only. So:
1. No test drives `cover.close_cover` through a real ZHA cover entity.
2. No test observes the setup order in §3c. The "upstream quirk loaded" test builds that outcome by hand.
3. No test observes the "closed" state in 2f.

**3e-iii. The command-path tests stub the position read.** The retired `tests/test_quirk_wire.py` drives the real cluster's `command()` through zigpy's real request path and decodes the frames, which is what R1 asked for. Its `_live_lift` is an `AsyncMock`, so the parsing of a real read response is not exercised. It covers the following:
1. Open as `go_to(0)`.
2. A close with no stop set, matching upstream's frame.
3. A close with a stop set, as `go_to(84)` for Stops at 14.
4. Double sends with no baseline.
5. Position commands held at the stop, in both positional and keyword form.
6. A re-send after no movement.
7. Stop passing straight through.
8. Survival of the unsupported mark.

It does not cover:
1. A shade moving in the wrong direction.
2. Two unreadable reads.
3. Every frame raising.
4. The `DeliveryError` path.
5. A double send at target.
6. The per-shade lock.

**3e-iv. The displayed position is likely stale after every move [suspected, from code].** The handler reads the position only during verification, in roughly the first 4-10 s of travel. Nothing reads again when travel ends. Neither the quirk nor the integration has a post-move read; the retired package had one at 90 s (ARCH:29-30). When ZHA's transition timer expires (up to 300 s), the state is recomputed from that early mid-travel value (`zha/.../cover/__init__.py:564-575`). The card then shows a position the shade is not in until the hourly refresh automation runs (`examples/smartwings_refresh_automation.yaml`). **What proves or disproves it:** one watched close on a real shade, then a look at the card after 5 minutes.

**3e-v. Unsupported claims and stale text remain.**
1. README lines 12-17 still describe "a Tuya Zigbee module … GPIO line" (REV 5e).
2. README line 81 still says "firmware version 2, which has not changed since at least 2023". Neither claim is in the record.
3. In the quirk, the cluster docstring says "inverted moves".
4. The `async_initialize` docstring places the read retry in `_live_lift()`; it is in `read_attributes`.
5. A comment names an automation `smartwings_hourly_position_refresh` and "nine covers", but the example's id is `smartwings_position_refresh`.
6. The closed-limit block still says "calibration file".
7. A comment still mentions "the rescue went out", for rescue code that was deleted.
8. `ConfigStatus` is imported unused, which fails ruff F401 upstream.
9. `config_flow.py` says "calibration services".
10. There is no `translations/en.json`.

**3e-vi. A class-name coupling survived.** `_handler_already_supplied()` in `__init__.py` still recognised our quirk only by the class name `SmartWingsWM25LZCover`. `find_readback_cluster` in `number.py` accepts either the class name or any cluster whose `AttributeDefs` has `closed_limit`. If the upstream version names its attribute differently, the integration will not recognise it (REV 7c).

**3e-vii. The direction of an unlimited close is unverified (Part 1 §3c).** If the vendor quirk's swap is wrong for these units, a close with no stop set raises the shade. The verification loop would then see movement away from the target, re-send three times, and raise `DeliveryError`. The shade would end up at the top, with an error shown. That outcome is safe for the fabric but wrong. Note: the new quirk (U) sends `down_close` unswapped instead (#34).

## 4. What is proven versus suspected in this part

**Proven by reading the installed source:**
1. The layer roles and terms (§1).
2. The command path (§2).
3. That the released quirk has no state (§3a).
4. That no entity interception exists other than replacing the entity (§3b).
5. The setup-order chain (§3c).
6. That quirks v2 can declare a number entity and that `LocalDataCluster` writes stay local (§3a).

**Proven by tests in the repo:** the frames our quirk sends for the cases listed in 3e-iii, and the integration's entity and registry behaviour against a stubbed gateway.

**Not proven:**
1. Any of this on the real shades (3e-i).
2. The setup order against a real ZHA (3e-ii).
3. ~~That a quirks v2 `number` on a `LocalDataCluster` works for this device (§3a).~~ Proven since by the #6 spike (ADR 0001).
4. The stale-after-move display (3e-iv).
5. The physical direction of an unlimited close (3e-vii).
