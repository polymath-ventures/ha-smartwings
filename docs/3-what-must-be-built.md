# Part 3: What must be built

This is a specification. It states what must be true of the finished software, not how to build it. Where a requirement follows from a measurement or a review finding, the source is cited (DH, ARCH and REV as in Part 1 §0). Where it depends on a decision the owner has not yet made, it is marked **DECISION**.

Written 2026-10-05. Revised 2026-10-06 for #54: the motor stops Zigbee commands at the limits set with its remote (Part 1 §3a, reversed), so the closed-limit requirements ("Stops at") are retired. Retired items keep their number and say so; their text is in the repository history and in OpenSpec's archived changes.

## 1. The two deliverables and the boundary between them

### 1a. Deliverable U: a change to the SmartWings quirk in zha-device-handlers

U is the behaviour. It lives in `zhaquirks/smartwings/wm25lz.py`, or a successor, in `zigpy/zha-device-handlers`. Once released in zha-quirks and pinned by Home Assistant, it reaches every ZHA user with nothing to install. It owns:

1. Delivery: making a command actually take effect on this hardware (Part 1 §3e).
2. ~~The closed limit's effect.~~ Retired (#54): the motor stops every command at its remote-set limits.
3. Stock behaviour: commands go out as ZHA sends them, without the vendor quirk's swap (§3a).
4. Keeping the cached position truthful after its own commands.
5. Declaring its quirk ID (§1c). (Until #54: declaring the "Stops at" control.)

### 1b. Deliverable I: our custom integration, `polymath-ventures/ha-smartwings`

I installs and monitors U. It owns:

1. ~~Capturing, clearing and changing each shade's stop.~~ Retired (#54): limits are set with the remote.
2. Telling the user, by shade, when U is not the quirk ZHA loaded.
3. Until U is released, offering U's code for `custom_quirks_path`.

### 1c. The boundary is a quirk ID, not a code dependency

U declares one quirk ID, `smartwings.wm25lz`, with `QuirkBuilder.exposes_feature()`. ZHA lists it in the device's `exposes_features`. It is the only thing I relies on to tell that U is the quirk ZHA loaded for a shade, and to tell that zha-quirks ships U (its registry entry's quirk definition). I keeps its own copy of the ID, and a test keeps the two equal.

I must not identify U by a Python class name, module path or cluster class name. That coupling existed in `_handler_already_supplied()` and in `find_readback_cluster`'s class-name branch (REV 7c).

Until #54 the boundary was a per-device setting on a local-only cluster (0xFC01) that U declared as ZHA's "Stops at" control ([ADR 0001](decisions/0001-quirk-v2-hosts-stops-at.md), superseded). It is gone with "Stops at"; U adds no cluster and no entity.

## 2. The user-visible contract

**2a. The card's controls work.** Open, Close, Stop and the position slider on each shade's card move it, stop it at the limits set with its remote, and show no error for the firmware's double reply (#54). Each shade's limits are its own, set with its remote as SmartWings' guide describes; Home Assistant can neither read nor set them (Part 1 §7a, §7b).

**2b-2f. Retired (#54).** Setting a stop by number (2b) or by capture (2c), clearing it (2d), "never set" (2e) and surviving restarts (2f) all concerned "Stops at", which is gone. Nothing is stored, so nothing has to survive, be cleared or outlive the integration.

**2g. Works through the ordinary cover entity.** Everything applies to every route into the shade's real `cover.*` entity: dashboard buttons and slider, voice assistants, scenes, scripts, automations, HomeKit and other bridges, and direct `cover.*` service calls. Nobody has to re-point anything. Open, close and positions go out as ZHA sends them, and the motor stops each at its remote-set limits.

**2h. "Closed" means at the lower limit.** The shade reports lift 100, which ZHA shows as position 0 and "closed", at the lower limit set with its remote (#54). Until #54 this read "closed means at the stop", with the slider rescaled to a stop the hub kept; that is retired.

**2i. The displayed position is the real position.** After any command completes, and after any movement by the remote that a refresh observes, the cover shows the position the shade is actually in. "Completes" means the shade has stopped travelling, not "the command was accepted". A position read early in travel must not stand as the final position (Part 2 §3e-iv).

**2j. One press is one action.** The user presses once. Making a command take effect on this hardware is U's job, including the re-send that is the actual wake protocol (Part 1 §3e). A one-shot implementation looks broken (DH:183-184). Whether the shade moved can only be judged once its travel should be over: a read during travel returns the lift from before the move, and the shade reports its position only when travel ends (#51; Part 1 §3f). So the re-send follows the estimated travel time, not a read taken mid-travel, and only when neither the shade's report nor a read by then shows travel toward the target.

**2k. Failure is visible.** If a command cannot be delivered, because the radio never answers its frame, the command fails through ZHA's standard failure path: the service call raises ZHA's error and the entity does not animate (owner decision 2026-10-05: match stock Home Assistant behaviour; DH:83-87). A frame the radio accepted returns at once, as with any ZHA cover; whether the motor acted is known only after the travel time (#51), so the cover animates as stock ZHA does, and position readback (#10) then shows where the shade really is. A shade that has still not moved after the one re-send is logged at WARNING, with no error raised after the call has returned.

**2l. Stop.** Stop is passed to the device once, unchanged. The motor halts on it (#51; Part 1 §3d), so the firmware's 0x81 that comes with it is no refusal: U reports it as SUCCESS, as for any movement, and the user sees no error (#54). No substitute stop is synthesised. A go-to built from a stale read is a move command, not a stop (Part 1 §3d). That a synthesised stop once reversed a shade is recorded only in a code comment and is unmeasured.

**2m. A missing handler is not silent.** If the quirk ZHA loaded for a shade is not U, ZHA uses the released vendor quirk, which swaps the Open and Close commands for these shades and sends each command once. A notification names each affected shade and says how to fix it.

## 3. Constraints on any acceptable implementation

**3a. U sends what ZHA sends.** Open goes out as `up_open`, close as `down_close` and a position as `go_to_lift_percentage` with ZHA's lift, unchanged; the motor stops each at its remote-set limits (#54). U may add delivery re-sends and the read-back. The one departure from the released quirk is that its swap of `up_open` and `down_close` is not used: raw `down_close` lowers these units (Part 1 §3c, #34) and raw `up_open` raised the Office Shade (#51). Until #54 every open went out as `go_to_lift_percentage(0)` (owner's decision, 2026-10-05) to avoid the one-unit run-to-limit stall (Part 1 §3b); that was retired with the closed limit, and a set position of 100 still sends a go-to 0 if the stall recurs.

**3b. U reads nothing outside the device object.** No file access, no environment variables, no Home Assistant imports, configuration or state, and no network other than the device itself.

**3c. U meets upstream norms.** It passes zha-device-handlers' lint and test suite. It contains no fleet-specific text: no entity ids, no automation names, no "nine covers". It contains no narration of our review process. Normal operation does not log at WARNING. Its comments match its code (REV 3c, 5a-5c).

**3d. No parallel entities.** No template covers, wrapper covers or groups standing in for the real cover. Neither U nor I adds an entity (#54; until then, the one "Stops at" control).

**3e. Retired (#54).** One authoritative store for each stop: there is no stored stop.

**3f. No ordering assumptions.** Correctness must not depend on the order in which Home Assistant sets up integrations. Where the order makes U absent, the user must be told (2m).

**3g. Bounded latency.** Every command returns success or failure within a documented worst case. The bound includes every frame, re-send of a lost frame and wait before the command returns, and it is asserted by a test; the re-send after the travel time (§2j) comes after the command has returned and never delays it. The per-shade serialisation of commands must not let one stuck shade delay another.

**3h. Standard vocabulary.** Shipped identifiers, logs, notifications and documentation use the protocol's terms (installed closed limit, lift percentage) and the remote's own ("limits"). No coined terms.

**3i. No shell, and no file-based bridge.** No `shell_command` (DH:79-82, DH:311-314). No file carries a value between Home Assistant and the quirk (DH:306-310). I may install its quirk file into `custom_quirks_path` (#18).

## 4. Failure modes that must be impossible by construction

"By construction" means the structure of the code rules each one out. Each has a test that would fail if it came back, except F13 and F14. Those two are general faults with no single site to test, so they are review-checklist items under §5e. Sources are in the last column.

| # | Must be impossible | Source |
|---|---|---|
| F1 | A value used in the wrong coordinate space. Conversion between HA position and ZCL lift happens in exactly one place: ZHA's `100 - lift`; U converts nothing (#54). | DH:61-65, DH:111-117 |
| F2 | The command interceptor re-entering itself while holding its own lock, which deadlocks the shade. | DH:66-70 |
| F3 | An unreadable position counted as movement. | DH:41-45, DH:76-78 |
| F4 | Movement away from the target counted as success. | DH:44-46 |
| F5 | A command the radio accepted that did not move the shade, left without a re-send once its travel should be over, or with a position shown that the shade is not in. (Until #51 this read "reporting success for a command after which the shade did not move"; no reply and no read during travel can tell that, Part 1 §3f.) | DH:83-87; #51 |
| F6 | A command judged moved where there is no cached baseline, or where the cache already claims the target. Without a baseline, only a lift at the target once travel should be over counts as arrival. | DH:47-51; #51 |
| F7 | Retired with "Stops at" (#54). ~~The control accepting a value U ignores, or U honouring a value the control cannot show. Both use one shared range.~~ | REV 2b |
| F8 | Retired with "Stops at" (#54). ~~A capture or set that reports success without storing.~~ | REV 2a |
| F9 | Retired with "Stops at" (#54). ~~A stop outliving the integration, or staying in force unseen after its control is removed or disabled.~~ | REV 2c |
| F10 | Retired with "Stops at" (#54). ~~Anything outside U and I disabling the stop silently, for example zigpy marking the setting unsupported after an over-the-air reply, or ZHA's cluster-management panel reading or writing it.~~ | REV 2d |
| F11 | Retired with "Stops at" (#54). ~~A user-chosen entity id being renamed.~~ | REV 2e |
| F12 | An absent U going unnoticed (2m). | REV 1a |
| F13 | A guard that fails into "allowed", where an exception in a check yields the permissive answer. Review checklist, §5e. | DH:118-121 |
| F14 | A test or check passing because its input was missing. Review checklist, §5e. | DH:122-124 |
| F15 | Retired with "Stops at" (#54). ~~A restored default creating a stop nobody set.~~ | Review finding, not an observed failure (DH:130-134, DH:318-323) |
| F16 | A synthesised stop, meaning a go-to built from a stale read. | Part 1 §3d (a code comment; unmeasured) |
| F17 | An early-travel reading displayed as the final position. | Part 2 §3e-iv |
| F18 | Swapping the lift *value* to fix a command-ID problem, or the reverse. | DH:111-113 |

## 5. Definition of done

### 5a. Tests of U's command path

These run in zha-device-handlers' own suite against the real cluster class and zigpy's real request path, asserting the decoded frames. The retired implementation's `tests/test_quirk_wire.py` did this for part of the list. Each case below must exist:

1. Open sent as `up_open` and close as `down_close`, each compared with the released quirk's swapped frame (§3a).
2. A position sent as the released quirk sends it, in both positional and keyword argument forms.
3. ~~Close with a stop.~~ Retired (#54).
4. ~~A position above, at and below the stop.~~ Retired (#54).
5. Stop, passed through once and unverified, its 0x81 reported as SUCCESS (§2l).
6. A re-send after no travel by the estimated travel time.
7. No re-send after travel, or after a read during travel that returns the lift from before the move (#51).
8. Movement in the wrong direction (F4).
9. Two unreadable reads (F3).
10. Every frame raising.
11. A command whose frames are both lost failing through ZHA's path; a shade that never moves re-sent once, then warned about, with no error after the call (F5).
12. One frame with no baseline and at the target, judged by the readback (F6).
13. Concurrent commands on one shade serialised and on two shades not serialised (§3g).
14. The worst-case duration bound (§3g).
15. ~~The unsupported mark (F10).~~ Retired (#54).
16. ~~The unset value and the out-of-range value (F7, F15).~~ Retired (#54).
17. Parsing a real `read_attributes` response, not a stubbed `_live_lift`.

### 5b. Tests that start a real Home Assistant with the real ZHA

These must load the real `homeassistant.components.zha` and the real zha library, with a zigpy database containing a WM25/L-Z and a radio stub at the zigpy application layer. The #5 harness (`tests/zha_harness/`) provides this: the environment installs `aiousbwatcher` and ZHA's other requirements, and the new suite does not use the `MockModule("zha")` stub that the retired suite had. These tests must assert on what the **entity layer** produced: the `cover.*` state and attributes and the frames on the wire. The simulated motor honours its remote-set limits: lift 100 is the lower limit (#54). At minimum:

1. **Setup order.** With only I installed, restart; the notification names the shade (2m). With U supplied through `custom_quirks_path`, restart; U is active and its quirk ID is in ZHA's `exposes_features`. After U's release, assert the same with no extra installation.
2. **End to end.** Call `cover.open_cover`, `cover.close_cover`, `cover.set_cover_position` and `cover.stop_cover` on the real ZHA cover entity. Assert the frames (`up_open`, `down_close`, the go-to with ZHA's lift, one Stop), no error under the firmware's double reply in either order, and the `cover.*` state after the simulated motor reports arrival or halts (2a, 2h, 2i, 2l).
3. **Restart.** The controls and the displayed position are correct after a full Home Assistant restart, including zigpy's database and HA's restore state.
4. **ZHA reload.** Covers the same assertions as the restart test.
5-7. ~~Capture; clear and removal; range and change.~~ Retired with "Stops at" (#54).

### 5c. Acceptance on the real shades

The pass criterion is physical observation, recorded per shade by IEEE in a results file, one row per trial:

1. ~~Part 1 test 8a run, and its result recorded, before any close with no stop set is allowed in production.~~ Not required: the owner decided test 8a is not needed and closed #4. The close is settled by the indirect evidence in Part 1 §3c (#34), and raw `up_open` raised the Office Shade (#51).
2. On each of the nine: Open, Close, Stop and the slider from the shade's card, and a close by voice. The shade stops at its remote-set limits, the fabric is visually unbunched, no error is shown, and the cover reads per 2h. (Until #54: capture a stop and close to it.)
3. On each: open and close ten times each. Count the commands that needed more than one frame and the commands that failed. Zero silent failures.
4. Restart Home Assistant and repeat one close per shade without re-setting anything.
5. Move a shade with the remote, run the refresh, and confirm the card is correct. Separately, after a commanded move, the card is correct at 5 minutes with no manual refresh (2i).
6. Stop halts a moving shade and shows no error (2l).
7. ~~Clear one stop and observe stock behaviour.~~ Retired (#54).

### 5d. Documentation

The README and code comments contain only claims the record supports (Part 2 §3e-v). Each known limitation is stated with its cause (Part 1).

### 5e. Review bar

An adversarial review of U and I, run after the last fix, finds no rank-1 or rank-2 defect. Every fix in the final round is re-read as it now stands. Three consecutive rounds here had their worst defect introduced by the previous round's fix (DH:97-102).

The review also checks every guard and every check in U and I against two items from §4:
1. F13: an exception inside a guard must not yield the permissive answer.
2. F14: a test or check must fail, not pass, when its input is missing.

### 5f. Upstream

U is submitted as a PR to `zigpy/zha-device-handlers` with the evidence for every behaviour change. That PR is a public action under the owner's identity and needs the owner's explicit go-ahead (DH:398-399). U is done when it is released in a zha-quirks version that Home Assistant pins. Until then, I's README must say that `custom_quirks_path` is required.
