# Test plan: the reference, the integration and the letter

Issue #39. Written 2026-10-06. This is the one list of tests for the SmartWings WM25/L-Z project. It replaces the scattered lists in Part 1 §8, Part 3 §5c, the closed #4, #36 and #15's acceptance; §7 maps every old name to its new ID. Nothing in this plan has been sent to a shade by the agent that wrote it.

Revised 2026-10-06 for #54: Zigbee closes stop at the limits set with the remote (Part 1 §3a, reversed), so "Stops at" was retired. The stop and capture tests are marked retired, with their text kept; `ACCEPT-CARD-CONTROLS` is the new acceptance test for Open, Close, Stop and the slider on every shade.

Revised again on 2026-10-06 for the simplified deploy runbook (#15, `docs/deploy-runbook.md`). Acceptance is now `ACCEPT-QUIRK-LOADED` and `ACCEPT-CARD-CONTROLS` on every shade, with one restart re-check. The other acceptance tests are retired or folded into other tests, each with its reason (§4j). The safe line is now optional (§2, rule 4.6).

Every test has a descriptive ID, such as `STOP-WHILE-MOVING`, and a one-line question in plain English. Numbers like "8a" or "#4" appear only in the mapping in §7.

## 1. Purpose

### 1a. Three deliverables

| Short | Deliverable | What a test result does for it |
|---|---|---|
| **R** | **The reference** ([Part 1](1-the-devices.md)). How SmartWings Zigbee behaves; what a hub must send for it to work; where it departs from the spec; where it is within the spec but still surprising; and what "expected" should be where the spec is vague. | The result becomes a measured fact in the Part 1 section named in the test, with its evidence file and its classification: *violation*, *within spec but unexpected*, *spec is vague (our reading)*, or *conforms*. |
| **I** | **The integration** (the quirk U and the integration I, specified in [Part 3](3-what-must-be-built.md) and `openspec/specs/`). It implements everything the reference says a hub must do. | A result that changes what a hub must send becomes a requirement change in the named `openspec/specs/` capability and a GitHub issue. A result that confirms current behaviour is cited from the requirement. |
| **L** | **The letter** (the owner's private letter to SmartWings, kept outside the repository). What we did, how we made it work, and how the device deviates. | A result that settles a letter item replaces its "we do not know" with the finding, or adds an item. Results that only matter to us stay out of the letter. |

### 1b. What the spec is

Every test is judged against the **Zigbee Cluster Library, Revision 8** (document 07-5123-08; [CSA PDF](https://csa-iot.org/wp-content/uploads/2022/01/07-5123-08-Zigbee-Cluster-Library-1.pdf)). Citations give the section, the table or figure, and the PDF's own line numbers ("l."), so a reader can find the sentence. "ZCL8" below means this document. Where a test depends on the Zigbee network layer rather than the ZCL (sleeping devices, polling, group delivery), it says so; ZCL8 does not cover those, and the plan does not quote a network-layer document it has not checked.

Five things in ZCL8 shape the whole plan. Each was read in the PDF text for this plan.

1. **The shade declares itself "open loop", and the spec relaxes several rules for open-loop devices.** ConfigStatus 0x03 has bit 3 clear, which means "Lift control is Open Loop" (Table 7-42, l.11601). For an open-loop device the installed limits "are ignored" (§7.4.2.1.3.1-2, l.11624-11630) and are mandatory only for closed-loop devices (Table 7-43 note, l.11618-11622). So 0x0011 = 0xFFFF, which is also the spec's default (Table 7-43), is **within the spec** for an open-loop device. Whether running past the remote-set stop is a violation is **arguable, not airtight**, and the plan uses Part 1's qualified verdict (§3a; §9, 9i). Down/Close goes to the installed closed limit (§7.4.2.2.2, l.11673-11676), but in open loop that limit is ignored, and the spec never says that a stop set with a remote is the installed closed limit: it speaks only of limits set "using physical tools" or learned "by an installer" (Table 7-44, bit 1). What is certain is that the device is **inconsistent**: it holds a closed limit and enforces it for its remote, declares open loop and reports the limit as unset, yet positions proportionally like a closed-loop device. Since #54 it is known to enforce the remote's limits for Zigbee too, so the open question about running past the stop is closed; the inconsistency in what it declares remains.
2. **The spec's open-loop rule for Go to Lift Percentage is the opposite of what these shades do.** "If the device only supports open loop lift action then a zero percentage SHOULD be treated as a down/close command and a non-zero percentage SHOULD be treated as an up/open command" (§7.4.2.2.5, l.11701-11702). The same section maps 0 % to the open limit for everyone else, and 0x0008 counts "from the up/open position" (l.11603-11605). These shades declare open loop but behave like closed-loop devices: 0 % opens, 38 % moves partway down (Part 1 §3g). That is a SHOULD, so it is **within spec but unexpected**, and the spec is self-contradictory here.
3. **Position reporting is a SHALL even for an open-loop device that has the attribute.** "This cluster SHALL support attribute reporting ... The following attributes SHALL be reported: Current Position - Lift Percentage" (§7.4.2.5, l.11756-11759). 0x0008 is mandatory only for closed loop (Table 7-40 note, l.11566-11570), but these shades implement it and advertise it as reportable (Part 1 §2a). The radio firmware settles the verdict ([firmware analysis](evidence/firmware-analysis.md) §4): it refuses Configure Reporting with UNSUP_COMMAND (0x81), which breaches §7.4.2.5, so the binding and configuration conditions this item used to set (§2.5.11.2, l.2929-2930) no longer arise. Separately, the radio pushes its own Report Attributes for 0x0008 straight to the coordinator, ignoring bindings, whenever the motor sends a new position. Whether those pushes arrive is the one open question, and `REPORT-NONE-OBSERVED` answers it passively, with no writes.
4. **Stop is mandatory, and the shade advertises it.** Table 7-45 (l.11663) marks Stop (0x02) mandatory. Discover Commands Received is "used to discover which commands a cluster can process" (§2.5.19, l.3310-3311), and the shade lists 0x02. It then answers Stop with status 0x81, UNSUP_COMMAND, "The specified command is not supported on the device. Command not carried out" (Table 2-12, l.3736). The shade contradicts itself on the air. That is a violation with no room for interpretation.
5. **The Mode attribute's default sets the "maintenance mode" bit.** Table 7-43 gives Mode (0x0017) the default `0000 0100`, which is bit 2. Table 7-44 (l.11652) says bit 2 = 1 means "the motor cannot be moved over the network". The shades read 0x14: bit 2 (the spec's own default) plus bit 4, which is reserved. Reserved bitmap bits "SHALL be set to zero for transmission" (§2.3.1, l.2231). The bit 2 reading is **the spec's own contradiction**; bit 4 is a **minor violation** whose meaning is unknown.

### 1c. Where the fault probably lives: the serial link, not Zigbee

Community firmware analysis (§8a) reports that the WM25/L-Z is **two chips**: a Silicon Labs EFR32MG1 Zigbee radio, and a separate motor controller, which presumably also receives the 433 MHz remote. The two are joined only by a two-wire serial link (UART, reported at 9600 baud). If that is right, the stop set with the remote, the ability to halt a moving motor and the position estimate all live in the motor controller. The Zigbee radio knows only what crosses the serial link.

That changes the main hypothesis, and the plan says so plainly:

1. **Old framing (Part 1 §3a, §3d):** "the Zigbee firmware ignores the stored stop and rejects Stop."
2. **New framing, a hypothesis to test:** the motor controller implements the stop and stopping correctly, since the remote proves both. The radio firmware translates only a few Zigbee commands into serial messages: reportedly up, down and lift percentage. Its translation either bypasses the stop (for example, a lift percentage scaled to full travel) or never asks the motor controller for it, and it has no mapping for Stop. The stop may well be "implemented, but not exposed to the standard". In that case the defect sits in the **bridge between the two chips**, and a firmware fix to the radio alone could repair it.

From our side, `FW-UART-PROTOCOL` settles this once we have the radio's firmware: it reads the radio's side of the link. Tapping the wire itself would need the unit opened, which is out of scope (§2, rule 1). SmartWings can settle it directly. Until then, Part 1 and the letter keep the old, observable wording ("over Zigbee, the shade ignores the stop") and may add the two-chip report as [reported, external].

**What the radio firmware showed (2026-10-06, [firmware analysis](evidence/firmware-analysis.md)).** Two chips, confirmed, but the radio is an EFR32MG21, not an EFR32MG1, and the link is not Tuya's protocol: frames are `LEN CMD DATA… XOR` at 9600 baud. The radio **does** map Stop: it sends `03 03 00` to the motor controller, as it sends `03 01 02` for Up/Open, `03 02 01` for Down/Close and the bare percentage for Go to Lift Percentage. It passes no limit and asks for none. From what the motor sends it reads only position, battery and pairing requests; bytes it ignores and message types it drops could carry more, so this bounds what reaches Zigbee, not what the motor knows. With Disable Default Response clear (ZHA's default), every Window Covering command is answered SUCCESS and then, by a handler bug, UNSUP_COMMAND (0x81), so a reply never shows what the motor did. The bridge hypothesis therefore holds for the limit (nothing carries it to Zigbee) and fails for Stop (the radio forwards it); whether the motor controller honours the forwarded Stop is `STOP-WHILE-MOVING`'s question, judged by motion.

**#54 (2026-10-06).** The motor controller applies the remote's limits to the commands the radio forwards: go-to 100 and raw `down_close` stopped at the remote-set lower limit, reported as lift 100. So the limit lives in the motor controller and works for both paths; only its value never crosses to Zigbee. The motor also halts on the forwarded Stop (#51).

### 1d. How a result flows

1. The owner or the agent runs the test and saves the evidence file (§2, rule 6).
2. The agent updates the Part 1 section named in the test with the result, its evidence level and its classification, and updates the status table in §6 of this plan.
3. If the result changes what a hub must send, the agent opens an issue against the named `openspec/specs/` capability (deliverable I).
4. If the test feeds the letter, the agent updates the letter item, or the "Left out, and why" list.

## 2. Ground rules

1. **Network and remote only.** Every test uses Zigbee frames from the hub, the shade's own 433 MHz remote, or read-only copies of files from the box. Nothing needs extra hardware or opening a unit: no serial-line tap, no SWD or chip read, no Zigbee sniffer (owner decision, 2026-10-06).
2. **Office Shade only.** IEEE `60:83:da:ff:fe:a0:00:02`, device "Office Shade", entity `cover.smartwings_wm25_l_z`. A test that needs another shade says "needs the scope extended", and it waits until the owner extends the scope for that test by name. The owner has extended it to every shade for the integration acceptance (§4j; runbook Steps 5-6).
3. **No frame without the owner present.** The owner is at the shade with its 433 MHz remote for every frame, including reads. The agent never sends a frame, calls a service, changes Home Assistant's configuration or restarts anything. The agent may read copies of files from the box, read-only, for the offline tests.
4. **Tests that move the shade avoid the bottom.**
   1. Prefer go-to targets well above the stop: lift 20-70 (ZCL lift; 0 is fully open).
   2. Start from mid-travel set with the remote, so any wrong direction has room.
   3. The motor stops Zigbee moves at the limits set with its remote, as it does for the remote itself (#54; Part 1 §3a). The bottom is therefore only as safe as the shade's remote limit. Check the limits with the remote first (README, Install, step 4). A run to the bottom once bunched a blackout shade's fabric; that was before #54 established that the limits hold. For a test where the direction is unknown or the frame is unusual (a direction reversal, go-to 100 or more; lift value and tilt are never sent, §3b item 6.2), **press Stop on the remote as soon as the direction is clear, after 2-3 s.**
   4. The remote's Stop is the only working stop (Part 1 §3d). Check it at the start of each session: press Down, then Stop after 2 s.
   5. After any movement frame, stay with the remote for **2 minutes**. One shade started about 100 s late (Part 1 §4).
   6. **The safe line (optional).** The motor enforces its remote limits (rule 4.3), so the line is a belt-and-braces check, not a requirement. To use it, drive the shade down with the remote until the remote stops it before the session. Put a tape mark on the window frame at the bottom bar's height and record its height above the sill. Under Zigbee or Home Assistant control the bottom bar should then stop at or just above the mark. If it reaches the mark and keeps going, the owner presses the remote's Stop, and that is a failure, recorded as such. A test that names the safe line uses it on each shade it moves.
   7. **One failure ends a series.** In any test that repeats closes (the card controls on each shade, the close after a restart, the stall repeat, several shades at once), a close that fails, shows an error, moves the wrong way, or has to be stopped with the remote when it was expected to stop by itself ends the series. In session E the series is per shade. (A test whose method plans a remote Stop at the safe line, such as the stall repeat, treats that planned stop as the normal end of a run.) Record that row, mark the remaining rows `blocked`, and do not resume until the cause is understood and the owner decides.
5. **Nothing writes a setting without a recorded undo.** Every write (Zigbee attribute, reporting configuration, binding, remote programming) lists in its run sheet the value before, the value written and the exact undo, and the session ends with the undo done and read back. Writing the value already held is preferred where it answers the question (`LIMIT-WRITE-READ-ONLY`, `MODE-WRITE-SAME-VALUE`).
6. **Evidence lands in `docs/evidence/`.** Each session leaves:
   1. one test-bench JSON, `docs/evidence/sessions/<YYYY-MM-DD>-<session>.json`, with every frame sent and received (§3); and
   2. one owner observation CSV, `docs/evidence/sessions/<YYYY-MM-DD>-<session>-observed.csv`, with columns `time,test_id,step,saw,direction,start_delay_s,end_by_eye,stopped_by_remote,notes`. `saw` is what the owner saw, in words. Separate items inside a field with `;`.
   The integration acceptance keeps the runbook's own `docs/evidence/acceptance.csv` (#15). Offline tests save their working and result as `docs/evidence/offline/<test-id>.md` or `.json`.
7. **Quiet box.** During a session nothing else talks to the Office Shade: no dashboard, voice, scenes or automations on it, and start away from minute :00, when the hourly position-refresh automation reads every shade (until #15 removes it).
8. **Firmware images are not redistributed.** The reverse-engineering track (§4i) keeps any image outside the repository and publishes only findings.

## 3. Tooling: one test bench

### 3a. Why one bench

The tools so far each did one job: `discovery_user.py` (#36) asks the shade what it supports, and `hwtest_user.py` (closed #4, branch `docs/4-hw-procedure`) sent three single frames. The open tests need about forty different frames. Rather than one script per test, one general **test bench** handler is driven by **run sheets**, so each session is: install the bench once, run the listed steps, copy one JSON file off. #42 built it, and session A ran on it on 2026-10-06.

### 3b. Specification (as built)

1. **Form.** One file, [`docs/evidence/bench_user.py`](evidence/bench_user.py), installed for a session as `/config/custom_components/zha_toolkit/local/user.py`. ZHA Toolkit 1.2.2 re-imports that file on every call, so no restart is needed (discovery procedure §7.3). Removing the file is the undo.
2. **Entry point.** One action per step: `zha_toolkit.execute` with `command: user_bench_<action>`, the IEEE, a `session` name, the step's `test_id` and `step`, and the action's own fields. Toolkit 1.2.2's `execute` schema allows extra fields and passes the service call to the handler (`__init__.py:56-99`, `:901-912`). The actions:
   1. Window Covering: `up_open` (0x00), `down_close` (0x01), `stop` (0x02, with optional `disable_default_response`, `ask_for_ack` and manufacturer code), `goto` (0x05, with an optional idle or read first); the timed sequences `goto_then_stop`, `goto_twice` and `goto_then_goto`. Any of them can end with a watch of 0x0008.
   2. `identify` (Identify, Identify Query, then a read of IdentifyTime), `group_membership`, `scene_membership`.
   3. ZCL general: `read` (uncached, one attribute per frame, with optional idle and trials), `write` (guarded, item 6.3), `read_reporting`, `discover` (one page of 0x15, 0x11 or 0x13, any manufacturer code including the wildcard 0xFFFF).
   4. ZDO reads: `zdo` (Node_Desc_req, Power_Desc_req, Mgmt_Bind_req).
   5. `watch`: listen for up to 15 minutes, optionally reading 0x0008 every N s.
3. **Run sheets.** [`docs/evidence/bench-run-sheets.md`](evidence/bench-run-sheets.md): for each of sessions A-D, what to have ready, then numbered steps, each with the exact action YAML to paste into Developer tools → Actions, the safety step before every moving step (including the safe line, §2 rule 4.6), what to report, the undo for every write, and where rule 4.7 ends a series. `tests/test_bench_run_sheets.py` runs every YAML block through the bench's own checks.
4. **Frames.** Every frame goes through zigpy's `Cluster.request()` on a bare zigpy cluster (no quirk code on the path), or `Device.request()` for ZDO, with `retries=0`. zigpy 2.3.0's `request()` accepts `disable_default_response` and `ask_for_ack` (`zigpy/zcl/__init__.py:815-816`), which the Stop variants need. One frame is in flight at a time and one bench call runs at a time. The bench never re-sends on its own; a re-send is its own step.
5. **Never marks anything unsupported.** Replies are decoded from raw bytes by an application listener, as in `discovery_user.py`. Nothing reaches zigpy's attribute cache, so no attribute is marked unsupported in `zigbee.db`.
6. **Allow-lists and guards, hard-coded.**
   1. IEEE: the Office Shade only. A scope extension is a reviewed code change naming the extra IEEEs, never a call field.
   2. Commands: only those in item 2, by cluster and ID. Anything else is refused before sending. **Window Covering 0x04 (Go to Lift Value), 0x07 (Go to Tilt Value) and 0x08 (Go to Tilt Percentage) are never sent**: the radio turns them into malformed serial frames that can repeat the previous command or corrupt the next ([firmware analysis](evidence/firmware-analysis.md) §3 note 3). The bench refuses them in code, whatever a call says, and no run sheet includes them.
   3. Writes need `confirm: true`. Only 0x0102 attributes 0x0010, 0x0011 and 0x0017 and Identify 0x0000 are writable. The bench reads the value first and refuses if it cannot (or if it differs from an optional `expect_before`), writes, reads back, and returns the exact undo. No reporting configuration and no binding is written (`REPORT-CONFIGURE-AND-WAIT` is moot).
   4. Movement: every moving action needs `remote_ready: true` and `may_go_down: true`, except a go-to to lift 0 (fully open), which needs `remote_ready: true` alone. A reversed motor or a misjudged target can send any other move down, so the owner confirms each one.
7. **Full frame log.** For every frame: test ID, step, TSN, ZCL bytes, time sent, idle time since the bench's previous frame, the reply (time, bytes, decoded) or timeout or send error, and latency. Replies are matched strictly: the other direction, the request's manufacturer code (any, for the wildcard), and the request's response command or a Default Response naming its command. Every frame the shade sends that matches no request is logged too, with its time: the second reply to a Window Covering command (SUCCESS then 0x81, firmware analysis §3), tagged with the frame it answers; late replies; attribute reports, listed in the call's response for `REPORT-NONE-OBSERVED`; OTA queries. Each call keeps listening for 3 s after its last frame so a second reply or a report is not missed. (Bench version 1, which ran session A, ended a call at the first matched reply, so its log lacks those second replies.)
8. **Output.** `/config/smartwings_bench_<session>.json`, written after every frame, so an interrupted step leaves a file. Each call is appended with its fields, the bench version and the zigpy, bellows and ZHA versions; the file also holds a read-only snapshot of zigpy's cached attributes at its start. The call's summary is the action's response.
9. **Stops itself** after 3 unanswered frames in a row. Each write is its own call, so a write that does not answer SUCCESS ends there, and its read-back shows the result.

## 4. The tests

Every test carries the same fields: its question (in italics under the ID); **Feeds** (the deliverables R, I and L, with the Part 1 section or `openspec/specs/` capability); **Why** where the reason is not obvious; **Spec** (the ZCL8 clause it is judged against, or "not ZCL" and what it is judged against instead); **Method**; **Result** (done tests) or **Pass / learn**; **Moves** (whether the shade moves); **Safety** (risk and safeguard); **Who**; **Status**; **Evidence** (the file or Part 1 section, or where it will land); and **Replaces** (the old item, or "new"). "Owner" means the owner, present at the shade, running bench steps. "Agent" means an offline agent with no access to a shade.

Status words: **done** (with an evidence link), **partly**, **open**, **blocked** (on the named thing), **optional** (run only if the owner chooses), **answered by firmware** (the radio firmware's code settles it, [firmware analysis](evidence/firmware-analysis.md); running it only confirms), **moot** (the firmware shows the question does not arise), **do not run** (the firmware shows the command is unsafe).

### 4a. Identity and capabilities

#### `ID-DISCOVERY`
*What attributes and commands does the shade say it supports, including manufacturer-specific ones?*

| | |
|---|---|
| Feeds | R §2; L "Units" and ask 3; I (no hidden command to use) |
| Spec | ZCL8 §2.5.18-2.5.23 (discovery commands); §2.3.3 (manufacturer extensions, l.2268-2275); §2.5.19.1.1 (a manufacturer "may wish to hide" extensions, l.3316-3323) |
| Method | Discover Attributes Extended (0x15), Discover Commands Received (0x11) and Generated (0x13) on all eight advertised clusters plus probes 0xFC01 and 0xEF00, each plain and with manufacturer code 0x1002; then a read of each uncached attribute |
| Result | No manufacturer-specific attribute or command advertised. Window Covering (0x0102) lists commands 0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08 and attributes 0x0000, 0x0007, 0x0008 (reportable), 0x0010-0x0013, 0x0017 (writable), 0xFFFD. Identify, Groups and Scenes list no received commands (Part 1 §9, 9t). Hidden extensions remain possible (§2.5.19.1.1) |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner (done) |
| Status | Done |
| Evidence | Part 1 §2a; `docs/evidence/discovery-office-shade.json`; procedure `docs/evidence/discovery-procedure.md` |
| Replaces | #36 |

#### `ID-DISCOVER-WILDCARD`
*Does the shade admit to manufacturer-specific commands when asked with the wildcard manufacturer code?*

| | |
|---|---|
| Feeds | R §2; L ask 3 |
| Spec | ZCL8 §2.5.19.1.1 (l.3318-3322): with manufacturer ID 0xFFFF, the response carries the manufacturer code of any manufacturer-specific commands, or none if the cluster has none or the manufacturer hides them |
| Method | Discover Commands Received and Generated on 0x0102 and 0x0000 with manufacturer code 0xFFFF |
| Pass / learn | Any manufacturer code in the reply names an extension set to probe next. An empty answer is consistent with #36 and closes the question from the hub side; only `FW-MANUFACTURER-EXTENSIONS` can rule out hidden ones |
| Moves | No |
| Safety | None (general discovery commands only) |
| Who | Owner, session A |
| Status | **Answered by firmware**: no manufacturer-specific command exists ([firmware analysis](evidence/firmware-analysis.md) §2). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2 |
| Replaces | new |

#### `ID-NODE-DESCRIPTOR`
*What kind of Zigbee device is it: router or end device, and does it listen while idle?*

| | |
|---|---|
| Feeds | R §2, §3e; L "Units" item 2 and item 5 |
| Spec | Zigbee network layer (node descriptor), not ZCL |
| Method | Read from a read-only copy of `zigbee.db` |
| Result | Logical type 2 (end device); MAC capability flags 0x80, so receiver-on-when-idle is clear: a sleepy end device. Manufacturer code 0x1002, maximum buffer 82 |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent (done) |
| Status | Done |
| Evidence | Part 1 §2 "Identity" (zigbee.db copy, 2026-10-06) |
| Replaces | 8b (node-descriptor half) |

#### `ID-SIMPLE-DESCRIPTOR`
*Which clusters does endpoint 1 advertise?*

| | |
|---|---|
| Feeds | R §2; L "Units" item 3 |
| Spec | Zigbee simple descriptor; ZCL8 §7.4 for 0x0102 |
| Method | Read from a read-only copy of `zigbee.db` (endpoint and cluster tables) |
| Result | Endpoint 1, profile 0x0104, device type 0x0202. Server: 0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102. Client: 0x0003, 0x0019 |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent (done) |
| Status | Done |
| Evidence | Part 1 §2 "Identity" |
| Replaces | new (recorded) |

#### `ID-BASIC-IDENTITY`
*What do the Basic cluster's identity attributes say, and are they valid?*

| | |
|---|---|
| Feeds | R §2; L "Units" item 1 |
| Spec | ZCL8 Table 3-7 (l.3791): ZCLVersion SHALL be 8 for this revision (§3.2.2.2.1, l.3793-3795); PowerSource Table 3-8 (l.3824), where 0x00 is "Unknown" and 0x03 is "Battery"; Window Covering ClusterRevision SHALL be the highest in §7.4.1.1 (l.11552), which is 3 |
| Method | Read from a read-only copy of `zigbee.db` (the Basic and Window Covering attribute cache) |
| Result | ZCL version 8, "Smartwings", "WM25/L-Z", power source 0 (unknown), cluster revision 3. All conform. Power source 0 on a battery motor is **within spec but unexpected**: it should be 0x03 |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent (done) |
| Status | Done |
| Evidence | Part 1 §2 "Identity" |
| Replaces | new (recorded) |

#### `ID-BASIC-VERSIONS`
*Which firmware build is this: application, stack and hardware versions, date code and software build?*

| | |
|---|---|
| Feeds | R §2; L "Not yet sent" item 4 (version details); FW-VERIFY-IMAGE (which image to look for) |
| Spec | ZCL8 Table 3-7: 0x0001 ApplicationVersion, 0x0002 StackVersion, 0x0003 HWVersion, 0x0006 DateCode, 0x4000 SWBuildID, all optional (§3.2.2.2.2-3.2.2.2.7) |
| Method | Read 0x0000/0x0001, 0x0002, 0x0003, 0x0006, 0x4000 one per frame; also 0x0008-0x000E. Read 0xFFFD on each server cluster |
| Pass / learn | Any value is recorded. All unsupported is itself a result for the letter: the device gives the hub no build identity beyond OTA file version 2 |
| Moves | No |
| Safety | None. #36 did not advertise these attributes, so expect UNSUPPORTED_ATTRIBUTE (0x86); the bench does not mark them unsupported |
| Who | Owner, session A |
| Status | **Answered by firmware**: Basic holds only 0x0000, 0x0004, 0x0005, 0x0007 and 0xFFFD, so every version attribute will be UNSUPPORTED_ATTRIBUTE; the only build identity is OTA file version 2 ([firmware analysis](evidence/firmware-analysis.md) §7). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §7 |
| Replaces | the letter "Not yet sent" item 4 |

#### `ID-WINDOW-COVERING-STATE`
*What does the Window Covering cluster declare about itself: type, loop mode, limits, mode?*

| | |
|---|---|
| Feeds | R §2, §3a; L "What the units report" |
| Spec | Tables 7-40 to 7-44 (§7.4.2.1); see §1b items 1 and 5 |
| Method | Reads in the research record, a read-only copy of `zigbee.db`, and the discovery run |
| Result | Type 0 (rollershade, lift only). ConfigStatus 0x03: operational and online, open-loop lift, not reversed. InstalledOpenLimitLift 0, InstalledClosedLimitLift 0xFFFF on all nine (conforms for open loop; it is also the default). Mode 0x14 (bit 2 is the spec default; bit 4 reserved) |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent (done) |
| Status | Done |
| Evidence | Part 1 §2 and §2a (DH:386-387, DH:180; zigbee.db copy; discovery) |
| Replaces | 8d (reading half) |

#### `ID-OTA-QUERY`
*Which firmware image does the shade say it runs, and how often does it ask for a new one?*

| | |
|---|---|
| Feeds | R §2, §7g; L "Units" item 4 and ask 5; FW-VERIFY-IMAGE |
| Spec | ZCL8 §11.13.4.3 (l.23724-23728): an end device "SHALL periodically wake up and send" Query Next Image Request; §11.8.2 (l.23375-23391): the frequency is left to the application standard |
| Method | `ota_query_cache` in a read-only copy of `zigbee.db`; Query Next Image Request lines in the box log |
| Result | Current file version 2, manufacturer 0x1002, image type 0. The query arrives roughly hourly. Conforms; hourly is reasonable |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent (done) |
| Status | **Partly.** Identity done (Part 1 §2; box log of 2026-10-06). Cadence in question: the firmware re-queries 5 minutes after a "no image" answer ([firmware analysis](evidence/firmware-analysis.md) §7), and `ota_query_cache` keeps only the latest query, so "roughly hourly" needs rechecking in the box log |
| Evidence | Part 1 §2 "Identity"; box log of 2026-10-06 |
| Replaces | new (recorded) |

#### `ID-POWER-DESCRIPTOR`
*What does the shade's ZDO power descriptor say about its power source and battery level?*

| | |
|---|---|
| Feeds | R §2, §5 (power); cross-check for POWER-BATTERY-UNITS |
| Spec | Zigbee ZDO power descriptor, not ZCL |
| Method | ZDO Power_Desc_req to the shade |
| Pass / learn | Records current power mode, available and current sources, and the coarse source level. A battery motor should say "rechargeable battery" or "disposable battery", in contrast to Basic PowerSource 0 |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

### 4b. Every advertised command

#### `CMD-UP-OPEN-DIRECTION`
*Which way does a raw Up/Open (0x00) frame move the shade?*

| | |
|---|---|
| Feeds | R §3c; I `command-delivery` ("Commands go out as ZHA sends them": every open is raw 0x00 since #54); L "Left out" item 2 |
| Spec | ZCL8 §7.4.2.2.1 (l.11668-11669): move to the installed open limit "as fast as possible". If reversed, ConfigStatus bit 2 must say so (Table 7-42) |
| Method | From mid-travel set with the remote, one `cluster_command` 0x0102/0x00, no payload |
| Pass / learn | Up = conforms, and the released vendor quirk's swap is wrong for these units. Down = violation (undeclared reversal). Either way record the Default Response and the start delay |
| Moves | Yes |
| Safety | If it goes down, it runs toward the bottom. Remote Stop after 2-3 s; start from mid-travel |
| Who | Owner, session B |
| Status | **Done for the owner's units (2026-10-06, session B, owner watched):** raw `up_open` from lift 71 raised the Office Shade. Default Response SUCCESS, then 0x81 (as for every handled command, firmware analysis §3); the start was immediate, per the owner; it ran to the top, and a read afterwards returned 0 (#51). Conforms; the released quirk's swap is wrong for these units |
| Evidence | #51; Part 1 §3c |
| Replaces | 8a (up half); Part 1 §3c "What would settle up_open"; #4. Runs as the first step of `REMOTE-DIRECTION-REVERSAL` |

#### `CMD-DOWN-CLOSE-DIRECTION`
*Which way does a raw Down/Close (0x01) frame move the shade, and where does it stop?*

| | |
|---|---|
| Feeds | R §3c, §3a; I `command-delivery` ("Commands go out as ZHA sends them"; #34, #54) |
| Spec | ZCL8 §7.4.2.2.2 (l.11674-11676): move to the installed closed limit |
| Method | Indirect (done): with no stop in force on the box, every close went out as raw 0x01, and the owner reports closes work. Direct (optional): from mid-travel, one 0x01 frame, watch the direction, stop with the remote |
| Pass / learn | Down = conforms on direction. The motor stops it at the remote's lower limit, as for any Zigbee close (#54; `LIMIT-ZIGBEE-IGNORES-STOP`, reversed). The direct run adds the air-side reply and start delay |
| Moves | Yes |
| Safety | Goes down to the remote's lower limit, where the motor stops it (#54; §2, rule 4.3). The direct run needs only the direction: remote Stop after 2-3 s |
| Who | Agent (indirect, done); owner, session B (direct, optional) |
| Status | Partly: indirect only |
| Evidence | Part 1 §3c; #34 |
| Replaces | 8a (down half); Part 3 §5c item 1 (struck). The direct run is the first step of `REMOTE-DIRECTION-REVERSAL` |

#### `REMOTE-DIRECTION-REVERSAL` (high priority)
*Is the motor's direction a per-unit setting made with the remote, and can the hub see it?*

| | |
|---|---|
| Feeds | I `command-delivery` ("Commands go out as ZHA sends them"; #34, #54); R §3c; L (a new item if reversal is invisible to Zigbee) |
| Why | SmartWings' own Home Assistant guide ends by reversing the direction with the remote, which a user with 27 blinds calls "critical" for open and close to work (§8a). If the direction is a per-unit remote setting, Part 1 §3c's "raw `down_close` lowers these units" may hold only for units set up that way, and the integration cannot hard-code `down_close` for a close with no stop (#34). It must then detect the direction (for example from ConfigStatus bit 2) or always use go-to |
| Spec | Table 7-42 bit 2 (l.11601): set when the direction "has been reversed in order for Open/Up commands to match the physical installation"; Table 7-44 bit 0 (Mode: motor direction reversed); §7.4.2.1.2.7 (l.11598-11600): "the behavior causing the setting or clearing of each bit is vendor specific" |
| Method | 1. Read 0x0007 and 0x0017. 2. From mid-travel, one raw `up_open` (0x00), then from mid-travel again one raw `down_close` (0x01): note which lowers the shade (this is `CMD-UP-OPEN-DIRECTION` and `CMD-DOWN-CLOSE-DIRECTION`). 3. From mid-travel, go-to lift 30 and note the direction. 4. Apply the remote's direction-reversal sequence from SmartWings' manual. 5. Read 0x0007 and 0x0017 again. 6. Repeat steps 2 and 3. 7. Undo: reverse back with the remote; read both attributes; repeat step 2 once and confirm the original direction |
| Firmware | Nothing in the radio writes ConfigStatus or reads Mode (a network write to Mode is only stored in RAM), and no message the radio parses from the motor carries a direction ([firmware analysis](evidence/firmware-analysis.md) §8). Step 5 can only read 0x03 and 0x14: a remote reversal is invisible on Zigbee. Steps 2, 3 and 6 still matter |
| Pass / learn | (1) Which raw command lowers the shade, before and after. (2) Whether ConfigStatus bit 2 or Mode bit 0 changes with the remote reversal: if it does, the hub can detect the direction; if not, reversal is invisible to Zigbee (the reason zigbee2mqtt offers `invert_cover`). (3) Whether go-to percentage also flips: if it does not, go-to is direction-safe and closes should use it |
| Moves | Yes |
| Safety | Medium. A raw command or a reversed shade may go down toward the bottom: remote Stop after 2-3 s each time, always from mid-travel. The undo is the same remote sequence; do not end the session until step 7 confirms the original direction |
| Who | Owner, session B, first |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | `MODE-REMOTE-REVERSAL-VISIBLE` (first version of this plan) |

#### `STOP-WHILE-STILL`
*What does the shade answer to Stop (0x02) when it is not moving?*

| | |
|---|---|
| Feeds | R §3d; L item 3; I `command-delivery` ("Stop is passed through once, never synthesised, and its second reply is not an error") |
| Spec | Table 7-45 (Stop mandatory); §7.4.2.2.3 (l.11681-11682); §2.5.12.2 (l.3007-3009): an unsupported command gets UNSUP_COMMAND; Table 2-12: 0x81 means "not supported ... not carried out"; §2.5.19 (advertised means it can process it) |
| Method | One 0x0102/0x02 frame with the Disable Default Response bit clear (zigpy's default for a command to a server cluster, `zcl/__init__.py:824-825`) |
| Pass / learn | Records the replies only; nothing can show whether the motor acted. Expected from the firmware: **two** Default Responses with the same TSN, SUCCESS then 0x81 ([firmware analysis](evidence/firmware-analysis.md) §3); the bench logs the second as unsolicited. The record has 0x81 only. Neither reply says anything about the motor |
| Moves | No (nothing to stop) |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | Partly: the shade's state and the frame were not recorded |
| Evidence | Part 1 §3d (DH:227-228) |
| Replaces | Part 3 §5c item 6 (Zigbee half) |

#### `STOP-WHILE-MOVING`
*If Stop is sent while the shade is moving, does it halt, or is Stop refused and the move carries on?*

| | |
|---|---|
| Feeds | R §3d; L item 3 (confirms "refused", not "slow"); I (Stop stays passed through) |
| Spec | As `STOP-WHILE-STILL`; §7.4.2.2.3: "will stop any adjusting ... that is currently occurring" |
| Firmware | The radio forwards Stop to the motor as serial `03 03 00` ([firmware analysis](evidence/firmware-analysis.md) §3, §5). This test now decides whether the **motor** honours it |
| Method | From mid-travel, go-to lift 30 (upward). After 3 s of visible travel, one Stop frame. `watch` 0x0008 every 2 s for 60 s |
| Pass / learn | Judge by what the shade does, never by the reply: the radio forwards Stop and then answers SUCCESS and 0x81 whatever the motor does (firmware analysis §3). Halts within about 1 s (the owner sees it stop; the watched 0x0008 stops changing short of 30) = the motor honours the forwarded Stop. Carries on to 30 = the motor ignores it. Halts late = record the delay. Record both replies anyway |
| Moves | Yes (upward) |
| Safety | Low: upward toward lift 30. Remote Stop if it overshoots |
| Who | Owner, session B |
| Status | **Done, twice (#51, session B, 2026-10-06).** A go-to then Stop after 3 s halted the Office Shade (a later read returned 71, from 84); a go-to 30 from 50 with Stop at 0.5 s halted it, and it reported lift 44 at 2.5 s. The motor honours the forwarded Stop. Consequence (#54): the quirk reports a standard Stop's 0x81 as SUCCESS, so the card's Stop shows no error |
| Evidence | #51 (session B, reported by the bench); Part 1 §3d |
| Replaces | Part 3 §5c item 6 (optional "while moving") |

#### `STOP-JUST-AFTER-START`
*Is Stop refused even when it arrives in the first second of a move, right after a frame the shade has just acted on?*

| | |
|---|---|
| Feeds | R §3d, §3e (whether a recently active shade takes frames faster) |
| Spec | As `STOP-WHILE-MOVING` |
| Firmware | As `STOP-WHILE-MOVING`: Stop is forwarded at once, whatever the timing ([firmware analysis](evidence/firmware-analysis.md) §3) |
| Method | Go-to lift 30 from mid-travel, then Stop 0.5 s after the go-to's Default Response |
| Pass / learn | As `STOP-WHILE-MOVING`: judge by motion and position reads, not the reply (SUCCESS then 0x81 regardless). The same outcome as `STOP-WHILE-MOVING` means timing does not matter. The reply latency still measures how fast an awake shade answers |
| Moves | Yes (upward) |
| Safety | Low |
| Who | Owner, session B |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

#### `STOP-NO-DEFAULT-RESPONSE`
*With the "disable default response" bit set, does the shade still report its refusal of Stop?*

| | |
|---|---|
| Feeds | R §3d (conformance of the error path) |
| Spec | §2.4.1.1.4 (l.2387-2390): with the bit set, a Default Response is returned "only if there is an error"; §2.5.12.2 (l.3001-3002) |
| Method | Stop with `disable_default_response: true`, shade still |
| Pass / learn | 0x81 still returned = conforms on the error path. No reply = a second, minor violation, and it means a hub using that bit would think Stop worked |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Answered by firmware**: with the bit set the SUCCESS is suppressed and only the 0x81 is sent ([firmware analysis](evidence/firmware-analysis.md) §3). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `STOP-WITHOUT-APS-ACK`
*Does the refusal depend on how the frame is delivered (with or without an APS acknowledgement)?*

| | |
|---|---|
| Feeds | R §3d, §3e |
| Spec | Network/APS layer, not ZCL; the ZCL answer must not depend on it |
| Method | Stop with `ask_for_ack: false`, then with `ask_for_ack: true`, shade still |
| Pass / learn | Same 0x81 both ways is the expected result and closes the question. A difference points at the delivery layer (see `RADIO-FIRST-FRAME-FATE`) |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Answered by firmware**: the ZCL replies do not depend on the APS options ([firmware analysis](evidence/firmware-analysis.md) §3). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `STOP-MANUFACTURER-SPECIFIC`
*Does the shade accept Stop when it is sent as a manufacturer-specific command with its own code 0x1002?*

| | |
|---|---|
| Feeds | R §3d; L ask 3; I `command-delivery` (Stop) |
| Spec | §2.3.3 (l.2273-2275): manufacturer-specific commands carry the code; an unrecognised code means "not carried out" |
| Method | 0x0102/0x02 with manufacturer code 0x1002, shade still. If SUCCESS, repeat once while moving upward (as `STOP-WHILE-MOVING`) |
| Pass / learn | 0x81 or 0x83 = no vendor Stop at that ID. SUCCESS and a halt = a usable stop for the integration |
| Moves | No (first frame); yes only if the first succeeds |
| Safety | Low |
| Who | Owner: still trial in session A; the moving trial in session B, only if the still trial answered SUCCESS |
| Status | **Answered by firmware**: any manufacturer-specific Window Covering frame gets 0x81 and sends nothing to the motor ([firmware analysis](evidence/firmware-analysis.md) §2, §3). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2, §3 |
| Replaces | new |

#### `CMD-GOTO-PCT-MEANING`
*What do 0 % and other percentages mean on this "open loop" shade: positions, or just "open" and "close"?*

| | |
|---|---|
| Feeds | R §3g, §1 (this is the main "within spec but unexpected" item); L (an observation, not a defect); I `command-delivery` ("Commands go out as ZHA sends them") |
| Spec | §7.4.2.2.5 (l.11697-11702): mapped between the installed limits; but for an open-loop device "a zero percentage SHOULD be treated as a down/close command and a non-zero percentage SHOULD be treated as an up/open command". See §1b item 2 |
| Method | Go-tos sent by earlier handler versions, with the direction watched and the position read back (research record) |
| Result | The shade behaves as a closed-loop device: go-to 0 opens fully, go-to lift 38 moves partway down, and 90/100 read back as 10/0 in Home Assistant space. It ignores the open-loop SHOULD, which is fortunate, because that rule would make 0 % close |
| Moves | Yes (done) |
| Safety | Done; no new frame |
| Who | Done, from the record |
| Status | Done |
| Evidence | Part 1 §3g (DH:248-253, DH:270-275, DH:176-179); §9, 9d |
| Replaces | new (recorded) |

#### `CMD-GOTO-PCT-ACCURACY`
*When told to go to a percentage, how close does the shade get, and does a repeat land in the same place?*

| | |
|---|---|
| Feeds | R §3g, §4; I `command-delivery` (`AT_TARGET_TOLERANCE = 3`); until #54 also the closed-limit margin |
| Spec | §7.4.2.2.5: maps to the installed limits; no accuracy is stated. **Spec is vague**: our expected = within 2 points of target, repeatable within 1 point |
| Method | With a tape measure fixed beside the shade, record the bottom-bar height at fully open and at the remote's stop. Then go-to lift 20, 40, 60, 40, 20, 0, each from rest; after each, read 0x0008 and measure the height. Twice through |
| Pass / learn | A table of target, reported and measured position. Feeds the margin and tolerance constants |
| Moves | Yes, all above lift 60 |
| Safety | Low |
| Who | Owner, session C |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

#### `CMD-GOTO-PCT-OVER-100`
*What does the shade do with a percentage above 100?*

| | |
|---|---|
| Feeds | R §3 (conformance of the error path) |
| Spec | §7.4.2.2.5 (l.11699-11701): larger than 100, "no physical action will be taken" and INVALID_VALUE |
| Firmware | The radio forwards the byte unchanged and replies SUCCESS then 0x81; it never returns INVALID_VALUE ([firmware analysis](evidence/firmware-analysis.md) §3). Only the motor decides what 101 does |
| Method | From mid-travel, go-to lift 101 |
| Pass / learn | Conformance is answered by the firmware: the radio forwards 101 unchanged and answers SUCCESS then 0x81, never INVALID_VALUE, so the device does not conform ([firmware analysis](evidence/firmware-analysis.md) §3). If the owner chooses to run it, it learns only what the **motor** does, judged by watching and by position reads, never by the reply: no motion, a clamp to 100 (which, like any move to 100, stops at the remote's lower limit, #54) or something else. Record the replies separately |
| Moves | Unknown: the motor decides |
| Safety | A clamp would drive down to the remote's lower limit, where the motor stops it (#54). The frame is unusual, so press the remote's Stop once the direction is clear, after 2-3 s (§2, rule 4.3); the safe line is optional (§2, rule 4.6) |
| Who | Owner, by choice only (not scheduled) |
| Status | **Answered by firmware** for conformance ([firmware analysis](evidence/firmware-analysis.md) §3). The motor's behaviour is optional; the integration never sends more than 100 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `CMD-GOTO-LIFT-VALUE`
*What does Go To Lift Value (0x04), advertised but never tried, do, and in what units?*

| | |
|---|---|
| Feeds | R §3; I README Known limitations item 6 ("Set lift value" is refused while a stop is set) |
| Spec | §7.4.2.2.4 (l.11688-11691): move to the value if within the installed limits, else INVALID_VALUE. The bound is worded backwards ("not larger than InstalledOpenLimit and not smaller than InstalledClosedLimit"), and with limits 0 and 0xFFFF and open loop, which values are "in bounds" is undefined: **spec is vague** |
| Method | Not run: the bench refuses this command (§3b item 6.2). Its effect on the motor is undefined; the firmware analysis (§3 note 3) answers what the radio does with it |
| Pass / learn | Not run (never sent). Answered by the firmware: advertised but mapped to a malformed serial frame, so **inconsistent** with its own discovery (§2.5.19, l.3310-3311); Go To Lift Value is optional, so not a violation in itself |
| Moves | No (never sent) |
| Safety | Never sent: the bench refuses 0x04 and no run sheet includes it |
| Who | Nobody |
| Status | **Do not run.** The handler sends a malformed 8-byte serial frame that can repeat the previous command or corrupt the next ([firmware analysis](evidence/firmware-analysis.md) §3 note 3). Answered: advertised, SUCCESS then 0x81, no defined motion |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `CMD-TILT-PERCENTAGE`
*What does Go to Tilt Percentage (0x08), advertised by a lift-only roller shade, do?*

| | |
|---|---|
| Feeds | R §3, §9 (9s: advertised commands that should not exist); I (none: ZHA offers no tilt for type 0, `zha/application/platforms/cover/__init__.py:224-254`) |
| Spec | §7.4.2.2.7 (l.11726-11727): "If the device is only a lift control device, then the command SHOULD be ignored and a UNSUPPORTED_COMMAND status SHOULD be returned" |
| Method | Not run: the bench refuses this command (§3b item 6.2). Its effect on the motor is undefined; the firmware analysis (§3 note 3) answers what the radio does with it |
| Pass / learn | Not run (never sent). Answered by the firmware: advertised but mapped to a malformed serial frame; advertising it is **inconsistent, not a violation** (Part 1 §9, 9s) |
| Moves | No (never sent) |
| Safety | Never sent: the bench refuses 0x07 and 0x08 and no run sheet includes them |
| Who | Nobody |
| Status | **Do not run.** The handler sends a malformed 8-byte serial frame ([firmware analysis](evidence/firmware-analysis.md) §3 note 3). Answered: SUCCESS then 0x81 (Disable Default Response clear), no defined motion |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `CMD-TILT-VALUE`
*What does Go to Tilt Value (0x07), advertised by a lift-only roller shade, do?*

| | |
|---|---|
| Feeds | R §3, §9 (9s); I (none, as `CMD-TILT-PERCENTAGE`) |
| Spec | §7.4.2.2.6 (l.11710-11714): only an out-of-bounds value gets INVALID_VALUE. Unlike Go to Tilt Percentage, it has **no** sentence telling a lift-only device to reject it. **Spec is silent**; our expected = UNSUP_COMMAND (0x81), as for the percentage form. Discovery lists it as a command the shade can process (§2.5.19, l.3310-3311), so 0x81 would contradict the advertisement |
| Method | Not run: the bench refuses this command (§3b item 6.2). Its effect on the motor is undefined; the firmware analysis (§3 note 3) answers what the radio does with it |
| Pass / learn | Not run (never sent). Answered by the firmware: advertised but mapped to a malformed serial frame, inconsistent with the advertisement |
| Moves | No (never sent) |
| Safety | Never sent: the bench refuses 0x07 and 0x08 and no run sheet includes them |
| Who | Nobody |
| Status | **Do not run.** The handler sends a malformed 8-byte serial frame ([firmware analysis](evidence/firmware-analysis.md) §3 note 3). Answered: SUCCESS then 0x81 (Disable Default Response clear), no defined motion |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `CMD-DUPLICATE-GOTO`
*If the same go-to arrives twice, does the shade move once and stop at the target, or move twice as far?*

| | |
|---|---|
| Feeds | I `command-delivery` (the single re-send after the travel time, #51); R §3e |
| Spec | §7.4.2.2.5: an absolute target, so a repeat should be harmless. Not stated: **spec is vague**; expected = idempotent |
| Method | From rest at lift 50: go-to lift 30 twice, 2.5 s apart. Then, at rest on 30, go-to 30 twice more |
| Pass / learn | Lands on 30 both times = re-sending the same target is safe. A double move or a stop-and-restart is a finding for both R and I |
| Moves | Yes (upward) |
| Safety | Low |
| Who | Owner, session B |
| Status | **Done (#51, session B, 2026-10-06):** the same target twice, 2.5 s apart, moved the shade once to the target; each frame drew SUCCESS then 0x81. The at-rest half was not reported |
| Evidence | #51 (session B, reported by the bench) |
| Replaces | new |

#### `CMD-NEW-GOTO-WHILE-MOVING`
*If a new go-to arrives during a move, does the shade change target at once?*

| | |
|---|---|
| Feeds | R §3; I `command-delivery` (re-sends while the shade is already moving), `position-readback` |
| Spec | Not stated: **spec is vague**; expected = the newest command wins at once |
| Method | From lift 70, go-to 20; after 3 s of travel, go-to 50. `watch` throughout |
| Pass / learn | Ends at 50 = retargets. Ends at 20 = ignores commands while moving, which matters for re-sends |
| Moves | Yes, between 20 and 70 |
| Safety | Low |
| Who | Owner, session B |
| Status | **Done (2026-10-06, session B, owner watched):** go-to 70, then go-to 40 after 8 s: the shade reversed and went to 40. With the second go-to after 4 s it continued to 40. The newest go-to wins while moving |
| Evidence | Owner's observation, session B (relayed with #51) |
| Replaces | new |

#### `CMD-IDENTIFY`
*What does the shade do when asked to identify itself?*

| | |
|---|---|
| Feeds | R §3 (Identify behaviour); I (ZHA's Identify button) |
| Spec | ZCL8 §3.5.2.3.1 (l.4238-4245): sets IdentifyTime and starts identification; §3.5.2.3.2: Identify Query; both mandatory (Table 3-32). How a device identifies is not stated. Discovery listed no received Identify commands (Part 1 §2a; §9, 9t) |
| Method | Identify (0x0003/0x00) with time 5 s; Identify Query (0x01) during it; read IdentifyTime (0x0000) |
| Pass / learn | Record what it does (jog, LED, nothing) and whether IdentifyTime counts down. Nothing visible is within spec |
| Moves | Possibly (some motors jog) |
| Safety | A small jog. Start from mid-travel |
| Who | Owner, session B |
| Status | **Answered by firmware**: Identify has no command handler; Identify and Identify Query get 0x81 and nothing happens ([firmware analysis](evidence/firmware-analysis.md) §2). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2 |
| Replaces | new |

### 4c. Limits

#### `LIMIT-ZIGBEE-IGNORES-STOP`
*Does every Zigbee movement command ignore the stop set with the remote?*

| | |
|---|---|
| Feeds | R §3a (reversed); L item 1 (to be removed); I: the reason "Stops at" was retired (#54) |
| Spec | §7.4.2.2.2 (l.11673-11676) and §7.4.2.2.5 (l.11697-11699): Down/Close and 100 % are the installed closed limit. But the shade declares open loop, in which the installed limits are "ignored" (§7.4.2.1.3.2, l.11628-11630), and the spec does not say a remote-set stop is the installed limit. Verdict: **inconsistent, arguably a violation, not airtight** (Part 1 §3a; §9, 9i; this plan §1b item 1) |
| Method | From the record: `down_close` and go-to at the end of travel on shades with a remote-set stop, watched; then, on 2026-10-06, go-to 100 and raw `down_close` watched by the owner (#54) |
| Result | **Reversed (2026-10-06, owner watched).** Go-to 100 and raw `down_close` both stopped at the remote-programmed lower limit: the Office Shade twice for go-to 100 and once for `down_close`, and the guest blackout shade on a Home Assistant close. Position 100 is the remote limit. History: the record said both ran past the stop and bunched a blackout shade (DH:283-287, DH:223-227, office shade DH:265-268); what differed then is not known (Part 1 §3a). Intermediate go-tos are covered by `LIMIT-PERCENT-SCALE` |
| Moves | Yes (done) |
| Safety | Done. The bunching it caused is why §2 rule 4 exists |
| Who | Done, from the record |
| Status | **Done, reversed (#54, 2026-10-06, owner watching):** Zigbee closes stop at the remote limit on the two shades tried, and the shade reports that limit as lift 100. Intermediate go-tos are `LIMIT-PERCENT-SCALE` |
| Evidence | Part 1 §3a (owner's observation, 2026-10-06; history DH:283-287, DH:223-227, DH:265-268) |
| Replaces | new (recorded) |

#### `LIMIT-PERCENT-SCALE`
*Are percentages scaled to the full mechanical travel or to the travel between the remote's limits?*

| | |
|---|---|
| Feeds | R §3a; L item 1 |
| Spec | §7.4.2.2.5 (l.11698-11699): "mapped ... between InstalledOpenLimit and InstalledClosedLimit" |
| Method | With the stop where it is, go-to lift 50 and measure the height (from `CMD-GOTO-PCT-ACCURACY`). Then reprogram the remote's lower limit about 20 cm higher (zigbee2mqtt's page: move to the spot and double-press Down), go-to lift 50 again from the same start, and measure. Undo: reprogram the original limit; confirm the remote stops there |
| Pass / learn | The radio sends the percentage to the motor unscaled and knows no limit ([firmware analysis](evidence/firmware-analysis.md) §5), so any scaling is the motor controller's. Same height both times = the motor scales to full travel. A different height = the motor maps percentages between the remote's limits, so the overrun is about where 100 % lands |
| Moves | Yes, above lift 50 |
| Safety | Reprogramming the limit is a setting change; the undo is a second reprogramming with the remote. Record the original stop height first |
| Who | Owner, session C |
| Status | Partly answered (#54): 100 % lands at the remote's lower limit, so percentages run between the remote's limits at least at the end. Intermediate heights are still open, and nothing in the software depends on them now |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | Part 1 §3a "What it does not prove" (partly) |

#### `LIMIT-OPEN-END`
*Does a Zigbee open stop at the remote's upper limit, or at the mechanical top?*

| | |
|---|---|
| Feeds | R §3a (symmetry); I `command-delivery` (open is raw `up_open`, #54) |
| Spec | §7.4.2.2.1: the installed open limit |
| Method | Set an upper limit with the remote below the top (if the remote supports it, per its manual), then go-to lift 0 from mid-travel. Undo: restore the upper limit |
| Pass / learn | Stops at the remote's upper limit = Zigbee honours the open limit (as it honours the closed one, #54) |
| Moves | Yes (upward) |
| Safety | Over-travel at the top is harmless (fabric is on the tube); the setting change has a remote undo |
| Who | Owner, session C (optional if the remote cannot set an upper limit) |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

#### `LIMIT-ATTRS-AFTER-REMOTE-SET`
*When the remote sets a new lower limit, does any Zigbee attribute change?*

| | |
|---|---|
| Feeds | R §3a, §7b; L item 2; I (any attribute that changes could replace capture) |
| Spec | §7.4.2.1.3.2: InstalledClosedLimitLift, "ignored" in open loop |
| Method | Read 0x0102 attributes 0x0007, 0x0008, 0x0010, 0x0011, 0x0012, 0x0013, 0x0017, and run discovery's attribute read on 0x0102 again. Reprogram the lower limit with the remote. Repeat the reads. Undo as in `LIMIT-PERCENT-SCALE` (run together) |
| Pass / learn | No change anywhere = the limit never crosses the serial link (or is not stored on the radio). Any change = a readable limit |
| Moves | Only by the remote |
| Safety | Low: only the remote moves the shade. The new limit is undone as in `LIMIT-PERCENT-SCALE`: reprogram the original stop and confirm the remote stops there |
| Who | Owner, session C |
| Status | **Answered by firmware**: no code writes 0x0007 or 0x0010-0x0013, Mode changes only on a network write, and the only motor data the radio reads are position and battery ([firmware analysis](evidence/firmware-analysis.md) §5, §8). Only 0x0008 can change. Optional confirmation alongside `LIMIT-PERCENT-SCALE` |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §5, §8 |
| Replaces | new |

#### `LIMIT-WRITE-READ-ONLY`
*Does the shade refuse a write to the installed limits with READ_ONLY, as the spec requires?*

| | |
|---|---|
| Feeds | R §1c, §7a; L item 2 |
| Spec | Table 7-43 (access R); §2.5.3.3 (l.2574-2575): a write to a read-only attribute SHALL get READ_ONLY (0x88), checked before the value |
| Method | Write the value already held: 0x0011 = 0xFFFF, then 0x0010 = 0x0000. Read both back |
| Pass / learn | READ_ONLY = conforms. SUCCESS = the device accepts writes to its limits, which opens a question for the vendor (do not write any other value without the owner's decision) |
| Moves | No |
| Safety | None if refused. If accepted, the value is unchanged, because it is the value already held; the undo is that same value |
| Who | Owner, session A |
| Status | **Answered by firmware**: the limits are read-only in the attribute table, so a write gets READ_ONLY (0x88) ([firmware analysis](evidence/firmware-analysis.md) §2, §8). Conforms. Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2, §8 |
| Replaces | new |

#### `MODE-READ`
*What does the Mode attribute (0x0017) read, and is it writable?*

| | |
|---|---|
| Feeds | R §2; L "Left out" item 4 |
| Spec | Table 7-43 (RW, default `0000 0100`); Table 7-44; §2.3.1 (reserved bits zero) |
| Method | Explicit reads of 0x0017 on all nine (box CSVs, 2026-10-05); the cached value and the access flag in the discovery run |
| Result | 0x14 on all nine; discovery lists 0x0017 as writable |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner with the HA agent (done, reported) |
| Status | Done |
| Evidence | Part 1 §2 and §2a; `/config/q_*_23.csv` on the box [reported] |
| Replaces | 8d |

#### `MODE-WRITE-SAME-VALUE`
*Does a write of the value Mode already holds succeed?*

| | |
|---|---|
| Feeds | R §2 (is Mode really writable); the prerequisite for the other Mode tests |
| Spec | §2.5.3.3 |
| Method | Write 0x0017 = 0x14; read back |
| Pass / learn | SUCCESS = writable as advertised. READ_ONLY or another error = advertised access is wrong (minor violation) |
| Moves | No |
| Safety | None (same value) |
| Who | Owner, session A |
| Status | **Answered by firmware**: Mode is writable (SUCCESS), held in RAM only and back to 0x14 at restart ([firmware analysis](evidence/firmware-analysis.md) §2, §8). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §8 |
| Replaces | new |

#### `MODE-REVERSAL-BIT`
*Does setting Mode bit 0 reverse the motor, and does ConfigStatus then show it?*

| | |
|---|---|
| Feeds | R §2, §3c; L (if it works, hubs can fix direction themselves) |
| Spec | Table 7-44 bit 0 (motor direction reversed); Table 7-42 bit 2; §7.4.2.1.2.7 (l.11598-11600): settings change through Mode |
| Method | Write 0x0017 = 0x15. Read 0x0017 and 0x0007. From mid-travel, go-to lift 30 and watch the direction (Stop with the remote after 2 s). Undo: write 0x14, read back, repeat the go-to and confirm normal direction |
| Pass / learn | Reverses and bit 2 of ConfigStatus sets = conforms. Write accepted but no effect = the bit is not bridged to the motor controller |
| Moves | Yes |
| Safety | A reversed shade goes down when told to go up; the setting may persist or also reverse the remote. Owner decision; remote in hand |
| Who | Owner, session D, by decision |
| Status | **Answered by firmware**: no code reads Mode and no serial message follows a write, so bit 0 does nothing and ConfigStatus stays 0x03 ([firmware analysis](evidence/firmware-analysis.md) §8). Not worth a session |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §8 |
| Replaces | Part 1 §7a (partly) |

#### `MODE-LED-BIT` and `MODE-MAINTENANCE-BIT`
*Do Mode bit 3 (LED feedback) and bit 2 (maintenance: "cannot be moved over the network") do anything on this shade?*

| | |
|---|---|
| Feeds | R §2 (the 0x14 reading); see §1b item 5 |
| Spec | Table 7-44 bits 2 and 3 |
| Method | Bit 3: write 0x1C, watch for any LED during a move, undo 0x14. Bit 2: write 0x10 (bit 2 cleared), go-to lift 30 and back, undo 0x14. Read back after each |
| Pass / learn | Whether either bit has any effect. Bit 2 set yet movable is the spec's own contradiction; record what this firmware does |
| Moves | Yes (small, upward) |
| Safety | Low; each undo is a write of 0x14 |
| Who | Owner, session D, by decision |
| Status | **Answered by firmware**: neither bit does anything; Mode is not read by any code ([firmware analysis](evidence/firmware-analysis.md) §8). 0x14, bit 4 included, is the compiled default |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §8 |
| Replaces | new |

#### `MODE-CALIBRATION-BIT`
*What does Mode bit 1 ("run in calibration mode") do on this firmware?*

| | |
|---|---|
| Feeds | R §7a |
| Spec | Table 7-44 bit 1: limits set "using physical tools or ... learned by the controller" |
| Method | Not run until SmartWings gives guidance with a safe method and the exact way to restore the limits and settings afterwards. Firmware analysis (`FW-ZCL-TABLES`) can show what the radio forwards, but not what the motor controller does, so on its own it is not enough |
| Pass / learn | What bit 1 does, with the vendor's restoration carried out and checked |
| Moves | Possibly a full calibration run |
| Safety | High: could erase the remote's limits or run end to end. Part 1 §7a already says not to try it without guidance |
| Who | Owner, by decision, only after the firmware track |
| Status | **Answered by firmware**: the radio neither acts on bit 1 nor tells the motor, so a write cannot start a calibration or set a limit ([firmware analysis](evidence/firmware-analysis.md) §8). The risk this test was blocked on is gone; there is nothing to learn by running it |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §8 |
| Replaces | Part 1 §7a |

### 4d. Position and reporting

#### `POS-AXIS`
*Is 0 % fully open and 100 % fully closed, as ZCL says?*

| | |
|---|---|
| Feeds | R §3g; I `position-readback` (the cache holds the lift as sent; ZHA's `100 - lift` is the only conversion) |
| Spec | §7.4.2.1.2.8 (l.11603-11605): percentage "from the up/open position" |
| Method | Go-tos and remote moves compared with reads (research record) |
| Result | Yes, plain ZCL, with one unexplained contradicting read |
| Moves | Yes (done) |
| Safety | Done; no new frame |
| Who | Done, from the record |
| Status | Done |
| Evidence | Part 1 §3g; §9, 9o |
| Replaces | new (recorded) |

#### `POS-READ-VS-PHYSICAL`
*Does the reported position match where the shade physically is, after Zigbee moves and after remote moves?*

| | |
|---|---|
| Feeds | R §3g, §7f; I `position-readback` |
| Spec | §7.4.2.1.2.8; open loop allows a timer estimate (Table 7-42 bit 5 "Timer Controlled"). **Spec is vague** on accuracy |
| Method | Run with `CMD-GOTO-PCT-ACCURACY`: after each move, compare 0x0008 with the tape. Add three remote moves (stop by eye at about a quarter, half and three quarters) and read after each |
| Pass / learn | The error of the estimate, and whether remote moves are estimated as well as Zigbee moves |
| Moves | Yes |
| Safety | Low: Zigbee targets above lift 60; remote moves stopped by eye; safe line |
| Who | Owner, session C |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

#### `POS-TRACKS-REMOTE`
*After a move with the remote, does a read return the new position?*

| | |
|---|---|
| Feeds | R §3f; I `position-readback` ("Moves made by the remote are corrected by an on-demand refresh") |
| Spec | §7.4.2.1.2.8 |
| Method | Part of `POS-READ-VS-PHYSICAL`; also `ACCEPT-CARD-AFTER-REMOTE-MOVE` |
| Pass / learn | The read matches the remote-set position within 3 points |
| Moves | By the remote |
| Safety | Low: only the remote moves the shade |
| Who | Owner, session C |
| Status | Partly: the README states it; no recorded trial |
| Evidence | README "What the cover shows" (a claim, not a trial) |
| Replaces | Part 3 §5c item 5 (first half) |

#### `POS-DURING-TRAVEL`
*While the shade moves, does the position attribute change continuously, in steps, or only at the end?*

| | |
|---|---|
| Feeds | R §3f; I `position-readback` (stationarity); docs README "Suspected" item 4 |
| Spec | §7.4.2.1.2.8 ("actual position") |
| Method | From lift 70, go-to 10; `watch` 0x0008 every 2 s until 10 s after it stops |
| Pass / learn | A time series. If it only jumps at the end, Part 1 records it and the integration's stationarity check needs two equal reads after arrival |
| Moves | Yes (upward) |
| Safety | Low: upward travel only |
| Who | Owner, session B |
| Status | **Done (#51, session B, 2026-10-06): only at the end.** A read of 0x0008 during travel returns the lift from before the move; it changes, with no value in between, when the motor reports its position at the end of travel. Go-to 50 from 0: reads at 0.5-15.3 s all 0, from 18.3 s 50. Raw `up_open` from 71: 71 at about 5 s and 7 s. Go-to 30 from 44: 44 at 3.8 s, 30 by 8.8 s. Consequences: the quirk judges a command only after its travel time (#51), and the capture's two-read stationarity check cannot see travel (#52) |
| Evidence | #51; Part 1 §3f, §4 |
| Replaces | docs/README "Suspected" item 4 |

#### `REPORT-NONE-OBSERVED`
*Has any shade ever sent a position report?*

| | |
|---|---|
| Feeds | R §3f; L item 4 |
| Spec | §7.4.2.5 (l.11756-11759): position SHALL be reported. The verdict is already drawn from the firmware (Configure Reporting refused, [firmware analysis](evidence/firmware-analysis.md) §4); this test only asks whether the radio's own pushes arrive |
| Method | Record (done): watching the cached position and ZHA's log, over days, for Report Attributes from any shade. Re-run (passive, no writes): in session B the bench logs every unsolicited frame from the shade (§3b item 7) through the session's go-tos and at least one remote move, and for 15 minutes after the last move |
| Result | Record: none from any of nine, over days. Re-run (#51, session B): reports arrive at the end of travel |
| Pass / learn | Any Report Attributes for 0x0102/0x0008 (or 0x0001/0x0021) from the shade = the radio's pushes ([firmware analysis](evidence/firmware-analysis.md) §4) arrive, and the record's "never" was a gap in observation; record when they come (during travel, or only at the end). None through moves that changed the read position = the pushes are lost between the radio and the hub |
| Moves | No frames of its own; it watches the moves of other session B tests and one remote move |
| Safety | None |
| Who | Owner, session B (the bench does the logging) |
| Status | **Done (#51, session B, 2026-10-06): reports observed, at the end of travel only.** A go-to 30 from 50, stopped at 0.5 s: Report Attributes 0x0008 = 44 at 2.5 s. A go-to 30 from 44: 0x0008 = 30 at 6.2 s. ZHA's cover updated within about 4 s of the report. Battery 0x0021 was reported too (82 during travel, 84 after). The record's "never" was a gap in observation. A remote move has not yet been watched |
| Evidence | Part 1 §3f (DH:197, DH:233-235; #51) |
| Replaces | new (recorded) |

#### `REPORT-READ-CONFIG`
*Does the shade hold a reporting configuration for its position, and if so which one?*

| | |
|---|---|
| Feeds | R §3f; L item 4 ("we have not yet checked whether the shade accepted the configuration"); the letter "Not yet sent" item 3 |
| Spec | §2.5.9 (Read Reporting Configuration); §2.5.10.1.2 (status: SUCCESS, UNSUPPORTED_ATTRIBUTE, UNREPORTABLE_ATTRIBUTE or NOT_FOUND); §7.4.2.5 |
| Method | Read Reporting Configuration (general 0x08) on 0x0102, direction 0, attribute 0x0008. Then also for 0x0001/0x0021 (battery) |
| Pass / learn | Expected from the firmware: Default Response 0x81, because no reporting engine is linked ([firmware analysis](evidence/firmware-analysis.md) §4). Anything else would contradict the firmware analysis. No verdict depends on a binding any more |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Answered by firmware**: Read Reporting Configuration is refused with Default Response 0x81; no reporting engine is linked ([firmware analysis](evidence/firmware-analysis.md) §4). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §4 |
| Replaces | 8c; #4 (8c half); Part 1 §3f "What settles it" |

#### `REPORT-BINDING-TABLE`
*Does the shade hold a binding that tells it where to send reports?*

| | |
|---|---|
| Feeds | R §3f (a missing binding would explain silence without a reporting violation) |
| Spec | §2.5.7.3 (l.2770-2772) and §2.5.11.2 (l.2929-2930): reports go to the destination found through the binding; "If the destination ... cannot be determined, then the command SHALL not be generated" |
| Method | ZDO Mgmt_Bind_req to the shade |
| Pass / learn | Informational only: the radio's reports go straight to the coordinator and ignore bindings, and it accepts no reporting configuration ([firmware analysis](evidence/firmware-analysis.md) §4), so no binding result changes the verdict in Part 1 §3f |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Moot**: the radio's reports go straight to the coordinator and ignore bindings ([firmware analysis](evidence/firmware-analysis.md) §4). Optional |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §4 |
| Replaces | new |

#### `REPORT-CONFIGURE-AND-WAIT`
*If reporting is configured again now, does the shade then report its position during or after a move?*

| | |
|---|---|
| Feeds | R §3f; L item 4; I `position-readback` (a reporting shade would make read-back unnecessary) |
| Spec | §2.5.7.3; §2.5.11.2.1-2.5.11.2.3 (l.2931-2948); §7.4.2.5 |
| Method | Not run. The firmware refuses Configure Reporting and ignores bindings, so there is nothing to configure, bind or restore. The observation half is `REPORT-NONE-OBSERVED`'s passive re-run |
| Pass / learn | Answered by the firmware ([firmware analysis](evidence/firmware-analysis.md) §4): Configure Reporting gets Default Response 0x81 (a violation of §7.4.2.5), and the radio's own reports go straight to the coordinator whatever the bindings |
| Moves | No |
| Safety | None: nothing is sent and nothing is written |
| Who | Nobody |
| Status | **Moot** ([firmware analysis](evidence/firmware-analysis.md) §4) |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §4 |
| Replaces | new |

#### `REPORT-BATTERY-HISTORY`
*Has the shade ever sent a battery report, or are its battery values only ever read?*

| | |
|---|---|
| Feeds | R §3f, POWER; I (battery entity freshness) |
| Spec | ZCL8 §3.3.2.2.3.2 (BatteryPercentageRemaining, access RP: reportable) |
| Method | From a read-only copy of `zigbee.db` and the box log: timestamps of 0x0001/0x0020 and 0x0021 updates against times anything read them |
| Firmware | The radio pushes 0x0021 to the coordinator whenever the motor sends a changed battery value ([firmware analysis](evidence/firmware-analysis.md) §4, §6). An unmatched update in `zigbee.db` would show those pushes arrive |
| Pass / learn | Updates with no matching read = the shade does report battery, so it can report at all, which sharpens §3f |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent, offline |
| Status | Open |
| Evidence | None yet. Will be `docs/evidence/offline/REPORT-BATTERY-HISTORY.md` |
| Replaces | new |

### 4e. Radio and delivery

#### `RADIO-READ-LATENCY`
*How long does a read take to answer?*

| | |
|---|---|
| Feeds | R §4; I `command-delivery` (`READ_TIMEOUT`) |
| Spec | Not covered by ZCL8, which sets no response time; delivery to an end device is network layer |
| Method | Timed reads in the research record (`sw_verify2.py`) |
| Result | 0.8-1.9 s when answered; unanswered reads needed one retry on three of nine shades |
| Moves | No |
| Safety | None |
| Who | Done, from the record |
| Status | Partly: `RADIO-POLL-INTERVAL` measures how latency depends on idle time |
| Evidence | Part 1 §4 (DH:375) |
| Replaces | new (recorded) |

#### `RADIO-POLL-INTERVAL`
*How long can the shade sleep before a frame to it is lost or delayed: what is its poll interval?*

| | |
|---|---|
| Feeds | R §3e (the likely mechanism of the "first frame"); L item 5; I `command-delivery` (whether a cheap read first would wake it) |
| Spec | Zigbee network layer (an end device with receiver off polls its parent, which holds frames for it for a limited time). Not ZCL. ZCL8 §11.8.2 notes sleepy devices only for OTA |
| Method | Reads of 0x0102/0x0008 only. For each idle time of 5, 15, 30, 60, 120 and 300 s (bench `idle` step, then one `read`), three trials: record send result, reply or timeout, and latency |
| Firmware | Long and short poll 1000 ms ([firmware analysis](evidence/firmware-analysis.md) §9). Expect no loss up to 300 s idle; a loss would point past the radio, at the motor |
| Pass / learn | A curve of latency and loss against idle time. A sharp change (for example, fine up to 7 s idle, lost after) dates the shade's poll period and explains why frame 1 fails and frame 2 works |
| Moves | No |
| Safety | None. About 45 minutes; the owner may sit nearby |
| Who | Owner, session A |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | 8b (partly) |

#### `RADIO-FIRST-FRAME-FATE`
*What happens to the first command after the shade has been idle: is it acknowledged, answered, executed late, or lost?*

| | |
|---|---|
| Feeds | R §3e (decides violation versus delivery defect); L item 5; I `command-delivery` |
| Spec | §2.5.12.2 (a Default Response SHALL follow a unicast command); if SUCCESS is returned the command should have been carried out (Table 2-12, SUCCESS = "Operation was successful"). Delivery itself is network layer |
| Method | Idle 10 minutes. One go-to lift 40 from lift 60 (upward). Bench logs send result, Default Response or timeout, and every unsolicited report; judge movement by the owner's observation, the end-of-travel report, or a read after the travel time, never by a read during travel (it returns the old lift, #51). Repeat three times, alternating 40 and 60. Then three times with a read 3 s before the go-to |
| Firmware | The radio sends SUCCESS before it writes the serial frame, once, with no wake line, acknowledgement or retry ([firmware analysis](evidence/firmware-analysis.md) §3, §9). So case (2) is the expected one, and it would place the loss at the motor controller |
| Pass / learn | (1) Send fails or no reply, and no movement = lost before the application: delivery defect. (2) SUCCESS and no movement = acknowledged but not executed: violation. (3) SUCCESS and a late start = executed late. Whether a read first fixes it decides if the quirk's re-sends could be replaced by one wake-up read |
| Moves | Yes (between 40 and 60) |
| Safety | Low |
| Who | Owner, session B |
| Status | **Reopened (#51): re-measure with arrival-time reads.** The recorded effect ("frame 1 produced no movement") was judged by reads 2.5-4 s after the frame, which return the pre-move lift during travel, so it is confounded (Part 1 §3e). The reply to frame 1 was never logged |
| Evidence | Part 1 §3e, §4 |
| Replaces | 8b; Part 1 §3e "What settles it" item 1 |

#### `RADIO-LATE-START`
*How often does an accepted command start late, and how late?*

| | |
|---|---|
| Feeds | R §3e, §4; I `command-delivery` (the re-send after the travel time), `position-readback` |
| Spec | §7.4.2.2.1-2 "as fast as possible"; **spec is vague** on how fast. Expected = within 2 s |
| Method | From every movement step in sessions B and C: the delay from the go-to's reply to the owner's "started" mark. Reads cannot show it: during travel they return the old lift (#51) |
| Pass / learn | The distribution of start delays. Any delay that pushes arrival past the quirk's estimate (`FULL_TRAVEL_S` share plus `ARRIVAL_MARGIN_S`) draws its one re-send, which is harmless (`CMD-DUPLICATE-GOTO`) |
| Moves | (uses other tests' moves) |
| Safety | As the tests whose moves it uses |
| Who | Owner (sessions B, C); agent tabulates |
| Status | Open (one event of about 100 s on record, Part 1 §4) |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/`; one earlier event in Part 1 §4 |
| Replaces | new |

#### `RADIO-PARENT-AND-ROUTE`
*Which device is the shade's parent, and how good is the link?*

| | |
|---|---|
| Feeds | R §3e (whether a router's frame-holding explains loss); I (none) |
| Spec | Zigbee network layer |
| Method | From a read-only copy of `zigbee.db` (neighbour and route tables) and ZHA's last topology scan: the shade's parent, LQI and RSSI, and the parent's model |
| Pass / learn | Parent = coordinator or a named router. If a router, its make bears on how long it holds frames |
| Moves | No |
| Safety | None: offline, no frame is sent |
| Who | Agent, offline |
| Status | Open |
| Evidence | None yet. Will be `docs/evidence/offline/RADIO-PARENT-AND-ROUTE.md` |
| Replaces | new |

### 4f. Power

#### `POWER-BATTERY-UNITS`
*Does the shade report battery percentage in the spec's half-percent units, or in whole percent?*

| | |
|---|---|
| Feeds | R §6; L item 6; I (the quirk keeps the vendor quirk's doubling) |
| Spec | ZCL8 §3.3.2.2.3.2 (l.3999-4002): half-percent, 0xC8 = 100 %; §3.3.2.2.3.1 (l.3996-3997): BatteryVoltage in 100 mV |
| Method | Read 0x0001/0x0020 and 0x0021 (raw, through the bench, not ZHA's doubled value) just after a full charge, and again before the next charge |
| Firmware | The radio copies the motor's byte into 0x0021 unscaled and never sets 0x0020 ([firmware analysis](evidence/firmware-analysis.md) §6). The cached 168 is the vendor quirk's doubling of 84, so whole percent is expected |
| Pass / learn | 0x0021 near 200 at full charge = spec units (and the doubling quirk is wrong). Near 100 = whole percent, a violation the doubling corrects. Voltage gives a cross-check |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A and once later |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | the letter item 6 |

#### `POWER-CHARGE-COMPARISON`
*Do voltage and percentage move together across a charge?*

| | |
|---|---|
| Feeds | R §6 |
| Spec | As `POWER-BATTERY-UNITS` |
| Method | Read 0x0020 and 0x0021 before charging, during, and after; note the charger's indicator |
| Pass / learn | Whether 0x0021 tracks 0x0020 across the charge. A steady ratio confirms the units found in `POWER-BATTERY-UNITS` |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, alongside a normal charge |
| Status | Open |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

### 4g. Groups and scenes

The community reports the radio firmware has no group or scene support (§8a), yet the shade advertises Groups (0x0004) and Scenes (0x0005). Home Assistant does not use either for this shade: ZHA builds group entities only for lights, switches and fans (`@register_group_entity` appears only in `zha/application/platforms/light`, `switch.py` and `fan`), and Home Assistant scenes are sent as ordinary commands. So only the two reads below are run; group commands and scene recall are not tested (owner decision, 2026-10-06).

#### `GROUP-MEMBERSHIP-READ`
*Does the Groups cluster answer at all, and is the shade in any group?*

| | |
|---|---|
| Feeds | R §2 (advertised versus working); checks the community claim |
| Spec | ZCL8 §3.6.2.3.4 (Get Group Membership, l.4413; Table 3-37 marks it mandatory); NameSupport attribute (§3.6.2.2.1). Discovery listed no received Groups commands (Part 1 §2a; §9, 9t), so this checks whether a mandatory command answers anyway |
| Method | Get Group Membership with an empty list; read 0x0004/0x0000 |
| Pass / learn | A valid response = groups at least answer, and discovery's empty list was incomplete. UNSUP_COMMAND = a mandatory command missing (Table 3-37), a violation, which settles Part 1 §9, 9t |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Answered by firmware**: Groups has no command handler; Get Group Membership gets 0x81 ([firmware analysis](evidence/firmware-analysis.md) §2). Advertised but missing, as #1184 said. Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2 |
| Replaces | new |

#### `SCENE-TABLE-READ`
*Does the Scenes cluster answer, and what does it hold?*

| | |
|---|---|
| Feeds | R §2; checks the community claim |
| Spec | ZCL8 §3.7.2.2 (attributes), §3.7.2.4.8 (Get Scene Membership, l.4789; Table 3-42 marks it mandatory). Discovery listed no received Scenes commands (Part 1 §2a; §9, 9t) |
| Method | Read SceneCount, CurrentScene, CurrentGroup, SceneValid, NameSupport; Get Scene Membership for group 0x0000 |
| Pass / learn | A valid response = scenes at least answer. UNSUP_COMMAND = a mandatory command missing, which settles 9t |
| Moves | No |
| Safety | None: nothing moves. The owner is present with the remote (§2, rule 3) |
| Who | Owner, session A |
| Status | **Answered by firmware**: Scenes has no command handler; the attributes read their defaults (all 0) ([firmware analysis](evidence/firmware-analysis.md) §2). Optional confirmation |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2 |
| Replaces | new |

### 4h. Repeatability (needs the scope extended)

#### `REPEAT-DOWN-CLOSE-STALL`
*Does a run-to-limit close (`down_close`) or open (`up_open`) stall partway on "Right master blackout", and how often?*

| | |
|---|---|
| Feeds | R §3b; L "Left out" item 1 |
| Spec | §7.4.2.2.2 (l.11673-11676): run to the installed closed limit |
| Method | Ten `down_close` runs from fully open, and ten `up_open` runs from fully closed (old 8e, revived by #54: opens are now raw `up_open`), on "Right master blackout" and on one sibling, counting stalls. Each `down_close` run ends with a planned remote Stop at the safe line; that planned stop is the normal end of a run, not a failure. A stalled `up_open` would mean the card's Open can stop short; position 100 (a go-to 0) still opens it |
| Pass / learn | Stalls out of the runs actually attempted per shade (up to ten; the series ends at the first stall, error, or unplanned stop, rule 4.7). A stall short of the safe line with no obstruction = a run-to-limit that does not reach its limit |
| Moves | Yes, downward |
| Safety | Bottom overrun: safe line on each shade, remote Stop before the bar passes it. The first stall, error, or unplanned stop ends the series (§2, rule 4.7) |
| Who | Owner; **needs the scope extended** to those two shades |
| Status | Open (scope) |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new; 8e (revived by #54, see §7) |

#### `REPEAT-TRAVEL-TIMES`
*How long does each shade take for full travel, up and down?*

| | |
|---|---|
| Feeds | R §4; I `command-delivery` and `position-readback` (`FULL_TRAVEL_S = 70`) |
| Spec | Not covered by ZCL8 beyond "as fast as possible" (§7.4.2.2.1-2) |
| Method | Agent: extract travel times from the about 150 CSV files in `/config` (read-only copies). Owner: time any shade the CSVs miss, by stopwatch, stopping at the remote's stop |
| Pass / learn | A time per shade and direction. Any over 70 s goes on #10 |
| Moves | Yes (owner part) |
| Safety | Owner part: closes stopped at the safe line by the remote |
| Who | Agent offline, then owner; **needs the scope extended** for shades other than the Office Shade |
| Status | Partly: 30-70 s overall, not per shade; needs the scope extended |
| Evidence | Part 1 §4 |
| Replaces | 8f |

#### `MULTI-SHADE-OPEN-CLOSE-ERROR`
*When several shades are opened or closed at once, which frame draws the UNSUP_COMMAND error that users see, while the shades still complete their travel?*

| | |
|---|---|
| Feeds | R §3d, §3e; I `command-delivery` (an error from a command that worked must not be reported as a failure, nor trigger a re-send); L (if the error is Stop or a duplicate frame) |
| Why | A user with 27 blinds on ZHA reports that open or close to 6-10 blinds at once often returns `unsupported_cluster_command` after travel begins, while the blinds still complete (§8a). 0x81 is the status these shades give Stop (Part 1 §3d), so the error may come from a frame other than the open or close itself |
| Spec | §2.5.12.2 (l.3007-3009): UNSUP_COMMAND goes back for the command that is not supported, and the Default Response carries that command's ID; Table 2-12 |
| Method | With the integration deployed and every shade's remote limits checked (runbook Step 5), debug logging on for `zigpy.zcl`, `zigpy.device`, `bellows.zigbee.application` and the quirk (`wm25lz`): close, then open, the chosen shades at once from one Home Assistant action. Record each frame sent and every Default Response with its command ID and TSN. Use only shades that each have a person beside them holding that shade's own remote: one person per commanded shade, no exceptions. Repeating with the stock vendor quirk is a separate owner decision (it would need the deploy undone) |
| Firmware | Every open, close and go-to draws SUCCESS then 0x81 with the same TSN ([firmware analysis](evidence/firmware-analysis.md) §3). The error users see is most likely the second reply to the command itself, kept when the first is lost |
| Pass / learn | The command ID in the 0x81 reply names the frame: 0x02 means something sends Stop; 0x00, 0x01 or 0x05 means the shade refuses a command it is executing. No error with our quirk is also a result |
| Moves | Yes, several shades |
| Safety | Every commanded shade is watched by someone holding its remote, with its safe line marked. Any shade that has to be stopped at its line ends the test (§2, rule 4.7) |
| Who | Owner, plus one helper for each additional commanded shade (one person per shade); **needs the scope extended** to the shades used |
| Status | Open (scope) |
| Evidence | None yet. Will be the session's bench JSON and observation CSV in `docs/evidence/sessions/` |
| Replaces | new |

#### `REPEAT-IGNORES-IDENTICAL-MOVES`
*Does a shade sometimes ignore repeated identical moves until it is nudged the other way?*

| | |
|---|---|
| Feeds | R §3h; README Troubleshooting item 6 |
| Spec | Not covered by the spec (Part 1 §9, 9p) |
| Method | Opportunistic: if any session sees a shade answer reads but ignore repeated identical moves, record the frames and try a small opposite move before the remote |
| Pass / learn | The frames and conditions of any recurrence, and whether a small opposite move frees it |
| Moves | Yes |
| Safety | As the session in which it happens |
| Who | Owner, whenever it happens |
| Status | Open (cannot be scheduled) |
| Evidence | Part 1 §3h (one event) |
| Replaces | new (Part 1 §3h) |

### 4i. Firmware reverse engineering (offline, no shade)

This track reads the **radio's** firmware. It can answer what the radio does with each Zigbee command and what crosses the serial link to the motor controller. It **cannot** answer the limit logic itself, which by the community's account lives in the motor controller (§1c). The motor controller's firmware is a separate chip and is out of scope. The whole track is offline analysis of an image someone sends us; nothing here opens a unit.

**Legal note.** This is reverse engineering of a device the owner owns, for interoperability, which US law (17 U.S.C. §1201(f)) and EU law (Software Directive 2009/24/EC, Article 6) both provide for in some form. The image is not redistributed; findings are. This is not legal advice; the owner decides.

#### `FW-OBTAIN-IMAGE`
*Can we get the radio's firmware image?*

| | |
|---|---|
| Feeds | Every FW test |
| Spec | ZCL8 §11.4 (the OTA file format, if SmartWings sends an OTA image) |
| Method | (1) The owner is asking a community member in zigpy discussion [#1184](https://github.com/zigpy/zigpy/discussions/1184) for the radio firmware; the dumps were exchanged privately there. (2) Fallback: ask SmartWings (the letter ask 5). Reading the chip over SWD is out of scope (§2, rule 1) |
| Pass / learn | An image in hand, or a recorded refusal |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Owner (asking); agent drafts any follow-up |
| Status | **Done.** A full flash dump (Intel HEX and S-record, same content) from a community member in zigpy discussion [#1184](https://github.com/zigpy/zigpy/discussions/1184), received by the owner 2026-10-06; kept outside the repository. Hashes in [firmware analysis](evidence/firmware-analysis.md) §0 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §0 |
| Replaces | new |

#### `FW-VERIFY-IMAGE`
*Is the image we got really this device's firmware, in the version our shades run?*

| | |
|---|---|
| Feeds | All FW findings (they apply only if it matches) |
| Spec | ZCL8 §11.4.2 (OTA header): file identifier 0x0BEEF11E (l.23016-23020), manufacturer code (§11.4.2.5), image type (§11.4.2.6), file version (§11.4.2.7), min/max hardware version (§11.4.2.13-14) |
| Method | For an OTA file: parse the header; expect manufacturer 0x1002, image type 0, file version 2 (`ID-OTA-QUERY`). For a flash dump: find the same values and the Basic strings "Smartwings" and "WM25/L-Z" in the image |
| Pass / learn | A match, or a recorded difference (for example an older or newer version) |
| Result | Manufacturer 0x1002, image type 0, file version 2 in the OTA client; "Smartwings" and "WM25/L-Z" in the Basic defaults; the same eight clusters as #36. Matches the Office Shade |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §0, §7 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §0, §7 |
| Replaces | new |

#### `FW-UNWRAP`
*What container is the image in, and is it encrypted or signed?*

| | |
|---|---|
| Feeds | `FW-IDENTIFY-MCU` onwards |
| Spec | ZCL8 §11.4.3-11.4.4 (sub-elements; tag 0x0000 is the upgrade image, Table 11-9); §11.4.6-11.4.9 (signature tags) |
| Method | Take the tag 0x0000 sub-element. Identify the Silicon Labs bootloader format: GBL (Gecko Bootloader, header tag 0x03A617EB) or the older EBL. List its tags. If an encryption tag is present the program data is unreadable without the key: stop and record. Note any signature |
| Pass / learn | The container type, its tag list, and whether the program is encrypted (which ends the track) |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §1 |
| Result | A raw dump of the whole 768 KiB flash, not an OTA file: no container, no encryption. The current application (version 2) is unsigned; a stale signed version 1 image tail remains in flash |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §1 |
| Replaces | new |

#### `FW-IDENTIFY-MCU`
*Which exact chip and SDK version is it?*

| | |
|---|---|
| Feeds | `FW-GHIDRA-LOAD` (the right memory map) |
| Spec | Not ZCL (vendor hardware). ZCL8 §11.4.2.13-14 (hardware versions in the OTA header) as a cross-check |
| Method | Vector table (initial stack pointer gives RAM size; reset vector gives flash base), Silicon Labs application-properties structure, SDK and EmberZNet version strings, peripheral addresses used. Expect EFR32MG1 [reported, external]. Manufacturer code 0x1002 is, as far as we know, the code assigned to Ember (now Silicon Labs) and often left as the SDK default; confirm against the CSA manufacturer-code list |
| Pass / learn | The chip part and SDK version, or "unknown" with the reason |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §1, §7 |
| Result | **EFR32MG21** (Series 2, Cortex-M33, 768 KiB), not EFR32MG1. Gecko Bootloader 1.12; EmberZNet 6.9.1 (Gecko SDK 3.1); application at 0x4000, NVM3 at 0x5A000. 0x1002 is the SDK default code (Ember/Silicon Labs) |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §1 |
| Replaces | new |

#### `FW-GHIDRA-LOAD`
*Can the image be disassembled with correct memory and peripheral names?*

| | |
|---|---|
| Feeds | Every later FW test |
| Spec | Not ZCL (tooling) |
| Method | Ghidra 12.1.4 headless, `ARM:LE:32:Cortex`, raw image at 0, every function decompiled; Capstone for exact listings. No SVD or SDK signatures were needed: the framework functions were recognised by behaviour |
| Pass / learn | A disassembly with peripherals named and SDK library functions identified |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §0 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §0 |
| Replaces | new |

#### `FW-ZCL-TABLES`
*Which clusters, attributes and commands does the firmware really implement?*

| | |
|---|---|
| Feeds | R §2, §3d; L ask 3; `MODE-CALIBRATION-BIT` |
| Spec | ZCL8 Tables 7-39 to 7-45 and 3-7, 3-32, 3-37, 3-42 (what should be there), against Part 1 §2a (what is advertised) |
| Method | Find the generated attribute metadata table (attribute ID, type, size, mask, default per entry) and the cluster table; the Window Covering command parser (a switch on IDs 0x00-0x08); what the Mode write callback does with each bit; whether Groups and Scenes have handlers or only table entries |
| Pass / learn | A list to compare with #36. Confirms or refutes "no group or scene support" |
| Result | One endpoint, eight clusters, 32 attributes, the same as #36. Mode (0x0017) is writable, defaults to 0x14 and is RAM-only: no callback, no serial message. Groups, Scenes and Identify have table entries and no command handlers (every command 0x81) |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §2, §8 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2, §8 |
| Replaces | new |

#### `FW-STOP-HANDLER`
*Why is Stop rejected: no case in the parser, or a case that returns UNSUP_COMMAND, and is there a serial "stop" it could have used?*

| | |
|---|---|
| Feeds | R §3d; L item 3 (a precise, fixable cause) |
| Spec | Table 7-45 (Stop mandatory); §7.4.2.2.3; §2.5.12.2 (l.3007-3009) |
| Method | Follow 0x02 through the Window Covering parser; list the serial messages the radio can build (`FW-UART-PROTOCOL`) and whether one is a stop |
| Pass / learn | The code path that produces 0x81, and whether a serial stop message exists that Stop could have used |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §3 |
| Result | Stop has its own case and sends serial `03 03 00` to the motor. Every Window Covering handler sends Default Response SUCCESS (when Disable Default Response is clear, as ZHA sends them), then returns "not handled", so the framework sends a second Default Response 0x81 with the same TSN. 0x04, 0x07 and 0x08 send malformed serial frames |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §3 |
| Replaces | new |

#### `FW-MANUFACTURER-EXTENSIONS`
*Does the firmware hide manufacturer-specific attributes or commands that discovery did not show?*

| | |
|---|---|
| Feeds | R §2; L ask 3; I (a hidden limit or stop command) |
| Spec | §2.3.3; §2.5.19.1.1 |
| Method | Entries flagged manufacturer-specific in the attribute and command tables, and their manufacturer codes |
| Pass / learn | Any hidden attribute or command, with its manufacturer code. None found turns Part 1 §2a's "none advertised" into "none implemented" |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §2 |
| Result | None: no manufacturer-specific attribute, command or cluster in the tables, and manufacturer-specific Window Covering frames are refused with 0x81 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §2 |
| Replaces | new |

#### `FW-UART-PROTOCOL`
*What serial protocol does the radio speak to the motor controller, and which Zigbee command becomes which serial message?*

| | |
|---|---|
| Feeds | R §3a, §3d, §3f (the bridge, §1c); L (a precise request for the radio firmware); I (none directly) |
| Spec | Not ZCL (a vendor-internal link) |
| Method | Find the USART set-up (expected 9600 baud, TX pin 6, RX pin 7 [reported, external]), the frame builder and parser, the header, version byte and checksum. **Hypothesis only**: the Tuya MCU serial protocol (header 0x55 0xAA, a version byte, command, length, data, one-byte checksum); "_TZE200" reportedly appears in NVM. Do not assert it until the code shows it. Map each Zigbee command (0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08, Mode writes) to the message it sends |
| Pass / learn | A table of Zigbee command to serial message. Whether up, down and percentage carry or bypass a limit; whether any message stops |
| Result | Not Tuya. Frame `LEN CMD DATA… XOR`, 9600 8N1, USART0 on PA05 (TX) and PA06 (RX). Up/Open `03 01 02`, Down/Close `03 02 01`, Stop `03 03 00`, Go to Lift Percentage `0d f1 … PP 00 CS` (unscaled). No message carries a limit, stop position or direction |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §5 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §5 |
| Replaces | new |

#### `FW-LIMIT-AND-POSITION-PATH`
*Does the motor controller ever send the radio its limit or its position, and what does the radio do with it?*

| | |
|---|---|
| Feeds | R §3a, §3f, §7b; L items 2 and 4 |
| Spec | §7.4.2.1.3.2 (0x0011), §7.4.2.5 (reporting) |
| Method | In the serial parser, which incoming messages update 0x0008, 0x0010, 0x0011 or anything stored; whether a position message triggers a Zigbee report; where limits are kept (if at all) on the radio's side |
| Pass / learn | Which serial messages, if any, carry the limit or the position, and what the radio does with them |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §4, §5 |
| Result | From what the motor sends, the radio reads only position (0xF5, byte 4), battery (0xF8, byte 2) and pairing requests; it writes 0x0008 or 0x0021 and pushes its own Report Attributes straight to the coordinator. Nothing it reads carries a limit, stop or direction; bytes it ignores and message types it drops could, but cannot reach Zigbee. No code writes 0x0007 or 0x0010-0x0013. Configure Reporting is refused (0x81) |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §4, §5 |
| Replaces | new |

#### `FW-SLEEP-AND-POLL`
*How long does the radio sleep between polls, and does it poll faster after activity?*

| | |
|---|---|
| Feeds | R §3e; L item 5 |
| Spec | Zigbee network layer (polling); ZCL8 §11.13.4.3 (l.23724-23728) for the OTA query |
| Method | Find the long and short poll intervals and the OTA query interval in the end-device configuration |
| Pass / learn | A firmware value to compare with `RADIO-POLL-INTERVAL` |
| Result | Long and short poll 1000 ms (defaults, never changed outside an OTA download); 3 s wake timeout. OTA: next query 5 min after "no image", server rediscovery after 10 min |
| Moves | No (offline) |
| Safety | None: offline, no frame is sent; the image stays outside the repository (§2, rule 8) |
| Who | Agent |
| Status | **Done.** [firmware analysis](evidence/firmware-analysis.md) §7, §9 |
| Evidence | [firmware analysis](evidence/firmware-analysis.md) §7, §9 |
| Replaces | new |

### 4j. Integration acceptance on the box (after deploy)

These are Part 3 §5c items 2-7, run by the owner with the deploy runbook (#15, `docs/deploy-runbook.md`). The runbook holds the exact steps, and each test here names its runbook step and its `acceptance.csv` rows. They need the integration deployed. Two run:

1. `ACCEPT-QUIRK-LOADED` (runbook Step 4.5).
2. `ACCEPT-CARD-CONTROLS`, on every shade after each shade's remote limits are checked (Steps 5-6), with one restart re-check.

The tests of "Stops at" (capture, close at the stop, clear, high stop, removal) are retired with it (#54). The simplified runbook does not run `ACCEPT-TEN-OPENS-TEN-CLOSES`, `ACCEPT-CARD-AFTER-REMOTE-MOVE`, `ACCEPT-READBACK-NO-REFRESH`, `ACCEPT-TRAVEL-TIME` or `ACCEPT-ALL-NINE`. Each is folded into the test that now answers its question, with the reason given in its Status.

#### `ACCEPT-QUIRK-LOADED`
*After install and restart, is our quirk the one ZHA loaded for the shade?*

| | |
|---|---|
| Feeds | I `bundled-quirk-install`, `integration-core` |
| Spec | Not ZCL. Part 3 §5b item 1 on the box; `bundled-quirk-install`; `integration-core` ("Missing-quirk Repairs issue") |
| Method | Runbook Step 4.5: Repairs, the quirk file's marker line, and ZHA's "Loaded custom quirks" log warning; row `quirk-loaded` |
| Pass / learn | No "SmartWings quirk not loaded" or other SmartWings Repairs issue; `wm25lz.py` starts with the integration's marker line; ZHA logs that it loaded custom quirks |
| Moves | No |
| Safety | None: nothing moves. Restarts follow the runbook, with its Step 0 backup in hand |
| Who | Owner, session E |
| Status | Open (needs deploy) |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | #15 Step 4 |

#### `ACCEPT-CAPTURE-WITH-REMOTE`
*Does capturing the stop where the remote leaves the shade store the right value?*

| | |
|---|---|
| Feeds | I `closed-limit-capture`; R §7b |
| Spec | Not ZCL. Part 3 §5c item 2; `closed-limit-capture` ("Capture stores the shade's live raw position as its closed limit", "Capture sends no movement commands") |
| Method | Runbook Step 5; row `5-capture`. Expect about 14 |
| Pass / learn | Capture returns a value within 2 of 14 (the earlier stop) and **Stops at** shows it |
| Moves | By the remote only |
| Safety | Low: only the remote moves the shade. Mark the safe line now, at the bar's height (§2, rule 4.6) |
| Who | Owner |
| Status | **Retired (#54)**: there is no stop to capture; the remote's own limits apply |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 2 (capture half); #13 hand-over |

#### `ACCEPT-CLOSE-STOPS-AT-STOP`
*With a stop captured, does a close from the dashboard and by voice stop at or above it, with smooth fabric, and read Closed?*

| | |
|---|---|
| Feeds | I `closed-limit-enforcement`; L "What we built" |
| Spec | Not ZCL. Part 3 §5c item 2 and §2h; `closed-limit-enforcement` ("Close and positions honour the closed limit") |
| Method | Runbook item 2; rows `2-dashboard`, `2-voice` |
| Pass / learn | Stops at or just above the safe line, fabric smooth, card Closed at 0 within 2 minutes |
| Moves | Yes, down to the stop |
| Safety | The bar must not pass the safe line: the owner presses the remote's Stop before it does, records the row as failed, and stops: no further close in session E (or E2) runs until the cause is understood and the owner decides to continue (§2, rules 4.6-4.7) |
| Who | Owner |
| Status | **Retired (#54)**: replaced by `ACCEPT-CARD-CONTROLS`, where a close stops at the remote's lower limit |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 2 |

#### `ACCEPT-TEN-OPENS-TEN-CLOSES`
*Over ten opens and ten closes, how many needed re-sends, and were there any silent failures?*

| | |
|---|---|
| Feeds | I `command-delivery`; R §3e (frame counts with the real quirk); L item 5 and "What we built" |
| Spec | Not ZCL. Part 3 §5c item 3; `command-delivery`. Opens are raw `up_open` and closes raw `down_close` since #54 |
| Method | Not in the runbook (see Status). Before #15's simplification: runbook item 3; rows `3-open-1` … `3-close-10`, `3-summary` |
| Pass / learn | Zero silent failures; counts of re-sent and failed commands |
| Moves | Yes |
| Safety | Safe line on every close. The first failure, error or remote stop ends the series; the remaining rows are `blocked` (§2, rule 4.7) |
| Who | Owner |
| Status | **Folded into `ACCEPT-CARD-CONTROLS`** (#15 runbook simplified): counting re-sends needs the quirk's debug log, which the owner-facing runbook dropped. Silent failures show in `ACCEPT-CARD-CONTROLS`, whose Open and Close run on every shade before and after a restart. Repeated runs are `REPEAT-DOWN-CLOSE-STALL` |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 3 |

#### `ACCEPT-STOP-KEPT-AFTER-RESTART`
*After a Home Assistant restart, is the captured stop still in force on the first close?*

| | |
|---|---|
| Feeds | I `stops-at-control` ("In force across restart and ZHA reload") |
| Spec | Not ZCL. Part 3 §5c item 4; `stops-at-control` ("In force across restart and ZHA reload") |
| Method | Runbook item 4; rows `4-stop-kept`, `4-close` |
| Pass / learn | **Stops at** still shows N, and the first close stops at or just above the safe line |
| Moves | Yes |
| Safety | Safe line. If the close passes it, stop with the remote and halt acceptance until the cause is found (§2, rule 4.7) |
| Who | Owner |
| Status | **Retired (#54)**: nothing is stored; the restart check is in `ACCEPT-CARD-CONTROLS` |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 4; #15 criterion |

#### `ACCEPT-CARD-AFTER-REMOTE-MOVE`
*After a move with the remote and a refresh, does the card show the real position?*

| | |
|---|---|
| Feeds | I `position-readback`; R §3f |
| Spec | Not ZCL. Part 3 §5c item 5; `position-readback` ("Moves made by the remote are corrected by an on-demand refresh") |
| Method | Not in the runbook (see Status). Before #15's simplification: runbook item 5.1; row `5-remote-refresh` |
| Pass / learn | The card shows the runbook table's value within 3 points after the refresh |
| Moves | By the remote |
| Safety | Low: only the remote moves the shade |
| Who | Owner |
| Status | **Folded into `POS-TRACKS-REMOTE`** (#15 runbook simplified): the same question, asked with the bench in session C; the runbook does not run it |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 5 (first half); #10 hand-over |

#### `ACCEPT-READBACK-NO-REFRESH`
*After a commanded move, with no manual refresh, is the card right at 5 minutes?*

| | |
|---|---|
| Feeds | I `position-readback` |
| Spec | Not ZCL. Part 3 §5c item 5 and §2i; `position-readback` |
| Method | Not in the runbook (see Status). Before #15's simplification: runbook items 5.2-5.3; rows `5-commanded-5min`, `5-close-5min` |
| Pass / learn | The card is right at 5 minutes; at most 8 reads; any WARNING noted |
| Moves | Yes |
| Safety | The close in runbook item 5.3 stops at the safe line at the latest (§2, rule 4.6) |
| Who | Owner |
| Status | **Folded into `ACCEPT-CARD-CONTROLS`** (#15 runbook simplified): its pass condition includes the card ending at the right position within 2 minutes, with no refresh. The 5-minute check and the read counts are not run |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 5 (second half) |

#### `ACCEPT-TRAVEL-TIME`
*How long does the Office Shade take for full travel each way?*

| | |
|---|---|
| Feeds | I (`FULL_TRAVEL_S`); R §4 |
| Spec | Not covered by ZCL8; judged against the quirk's `FULL_TRAVEL_S = 70` |
| Method | Not in the runbook (see Status). Before #15's simplification: runbook item 5.4; row `5-travel-time` |
| Pass / learn | Both times recorded; over 70 s goes on #10 |
| Moves | Yes |
| Safety | The timed close ends at the stop; safe line |
| Who | Owner |
| Status | **Folded into `REPEAT-TRAVEL-TIMES`** (#15 runbook simplified): travel times per shade come from the research CSVs and the owner's stopwatch there; the runbook does not time moves |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | 8f (Office Shade) |

#### `ACCEPT-STOP-SHOWS-REFUSAL`
*Does the card's Stop show ZHA's error and leave the shade alone?*

| | |
|---|---|
| Feeds | I `closed-limit-enforcement` ("Stop is passed through and never synthesised"); R §3d |
| Spec | Part 3 §5c item 6 and §2l; `closed-limit-enforcement` ("Stop is passed through and never synthesised"); ZCL8 Table 7-45 |
| Method | Runbook item 6; rows `6-still`, `6-moving` |
| Pass / learn | "Failed to stop cover" is shown. The radio forwards Stop to the motor before it answers 0x81 ([firmware analysis](evidence/firmware-analysis.md) §3), so the error says nothing about the motor: for `6-moving`, judge by watching whether the shade halts or carries on to its target, and record which. Carrying on matches the record; a halt means the motor honours the forwarded Stop, which is a finding for R and for `closed-limit-enforcement`, not a failure of the integration |
| Moves | `6-moving` only |
| Safety | For `6-moving`, use an upward move, so carrying on is harmless; remote in hand |
| Who | Owner |
| Status | **Retired (#54)**: the motor halts on Stop (#51) and the quirk reports its 0x81 as SUCCESS; `ACCEPT-CARD-CONTROLS` checks Stop with no error |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 6 |

#### `ACCEPT-CLEAR-THEN-CLOSE`
*After clearing the stop, does a close go down as the stock close (`down_close`), and is the stop then set again?*

| | |
|---|---|
| Feeds | I `closed-limit-capture` ("Clear removes the closed limit and restores stock behaviour"); R §3a, §3c |
| Spec | Not ZCL. Part 3 §5c item 7; `closed-limit-capture` ("Clear removes the closed limit and restores stock behaviour"); `closed-limit-enforcement` ("Stock behaviour when no closed limit is set") |
| Method | Runbook item 7; rows `7`, `7-reset` |
| Pass / learn | The shade moves down (the stock `down_close`, #34) and is stopped at the safe line; **Stops at** is set again afterwards |
| Moves | Yes, downward |
| Safety | With no stop it runs toward the bottom: the owner presses the remote's Stop before the bar reaches the safe line, every time |
| Who | Owner |
| Status | **Retired (#54)**: there is no stop to clear |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 7 |

#### `ACCEPT-HIGH-STOP-BAND`
*With a high stop (91-95), does a close read Closed, and how coarse does the slider become?*

| | |
|---|---|
| Feeds | I `closed-limit-enforcement` ("The displayed position is scaled to the closed limit"); README Known limitations item 5 |
| Spec | Not ZCL. Judged against the README's stated behaviour: the closed band is 1 point wide for stops 91-94 and empty at 95; a position lands within 1 point for stops up to 62 and within up to 25 points at 94-95 |
| Method | Clear the stop. Type 94 into **Stops at** (typing works only while no stop is set). From fully open, close from the card; read the card and `current_position`. Then set position 50 and record where the shade lands and what the card shows. Undo: clear, then capture the real stop with the remote as in `ACCEPT-CAPTURE-WITH-REMOTE`, and check **Stops at** shows it |
| Pass / learn | The close stops near the top and the card reads Closed; the set-position lands within 25 points. Anything else is a README or quirk defect |
| Moves | Yes, near the top |
| Safety | Low: a stop of 94 is near fully open. Safe line as always; while the stop is 94, no other close is made |
| Who | Owner, session E |
| Status | **Retired (#54)**: there is no closed band |
| Evidence | None yet. Will be rows `high-stop-*` in `docs/evidence/acceptance.csv` |
| Replaces | new (README Known limitations item 5) |

#### `ACCEPT-LIFT-VALUE-REFUSED`
*Is Go To Lift Value from ZHA's device panel refused without moving the shade?*

| | |
|---|---|
| Feeds | I `command-delivery` ("Commands the radio mangles are refused unsent"); README Known limitations item 4 |
| Spec | Not ZCL for the refusal (the quirk refuses it). ZCL8 §7.4.2.2.4 for why its units cannot be bounded |
| Method | **Do not send to a shade.** Go To Lift Value (0x04) reaches the radio as a malformed serial frame ([firmware analysis](evidence/firmware-analysis.md) §3 note 3), so a live check that the quirk refuses it would, if the refusal failed, put that frame on the motor. The refusal is verified offline instead: #47's quirk tests `test_mangled_commands_are_refused_unsent` and `test_mangled_commands_are_refused_on_every_send_path` (`tests/quirk/test_smartwings.py`) send 0x04, 0x07 and 0x08 through every path, with and without a stop, and assert that no frame leaves |
| Pass / learn | Pending: answered once #47 is merged and its offline tests (the quirk answers UNSUP_COMMAND and no frame is sent) are present and passing on main |
| Moves | No (nothing is sent) |
| Safety | None: offline only. The live panel command must not be tried |
| Who | Agent (CI) |
| Status | **Do not run live.** Answered offline by the #47 tests once #47 is merged |
| Evidence | #47: `tests/quirk/test_smartwings.py` |
| Replaces | new (README Known limitations item 6) |

#### `ACCEPT-REMOVE-INTEGRATION-CLEARS-STOPS`
*Removing the integration while ZHA runs: is every stop cleared?*

| | |
|---|---|
| Feeds | I `stops-at-control` ("No stop outlives the integration or its visible control"); README "Uninstalling" |
| Spec | Not ZCL. Judged against the README and `stops-at-control` |
| Method | With the stop captured and ZHA running, delete the SmartWings entry (Settings → Devices & services). Check **Stops at** reads Unknown (the quirk is still loaded) and, in a read-only copy of `zigbee.db`, that no 0xFC01 value remains for the shade. Undo: add the integration again, restart if Repairs asks, and capture the stop with the remote |
| Pass / learn | Stop cleared, nothing left in `zigbee.db` |
| Moves | No |
| Safety | No close while the stop is cleared: with no stop a close runs toward the bottom. Runbook Step 0 backup in hand |
| Who | Owner, session E2 |
| Status | **Retired (#54)**: nothing is stored to clear |
| Evidence | None yet. Will be row `remove-integration` in `docs/evidence/acceptance.csv` |
| Replaces | new (README "Uninstalling") |

#### `ACCEPT-REMOVE-INTEGRATION-ZHA-STOPPED`
*Removing the integration while ZHA is not running: do the stops stay in force, and does the log name the shades?*

| | |
|---|---|
| Feeds | I `stops-at-control`; README Known limitations item 7 |
| Spec | Not ZCL. Judged against the README |
| Method | With the stop captured, disable the ZHA entry, delete the SmartWings entry, then enable ZHA again. Check that **Stops at** still shows the stop and that one warning in the log names the Office Shade. Undo: add the integration with ZHA running, then remove it again (or clear the stop), add it back, and capture the stop with the remote |
| Pass / learn | Stop kept and shown; one warning naming the shade |
| Moves | No |
| Safety | No close during the test. Restarts and reloads follow the runbook, with its Step 0 backup in hand |
| Who | Owner, session E2 |
| Status | **Retired (#54)**: nothing is stored to keep |
| Evidence | None yet. Will be row `remove-integration-zha-stopped` in `docs/evidence/acceptance.csv` |
| Replaces | new (README Known limitations item 7) |

#### `ACCEPT-REMOVE-QUIRK-KEEPS-STOP`
*If the quirk is not loaded while a stop is stored, is the stop kept in ZHA's database and back in force when the quirk returns?*

| | |
|---|---|
| Feeds | I `closed-limit-contract` ("Clearing removes the stop for good"; the stop lives in `zigbee.db`); README Known limitations item 8 |
| Spec | Not ZCL. Judged against the README |
| Method | Before the session, the agent confirms against `bundled-quirk-install` how to reach the state the README describes (the quirk not loaded while a stop is stored; the integration otherwise reinstalls the quirk). The owner then reaches it, restarts, and checks: no **Stops at** control; the shade on the vendor quirk; the stop still in a read-only copy of `zigbee.db`. Then restores the quirk, restarts, and checks **Stops at** shows the old value |
| Pass / learn | Stop kept while the quirk is absent, and in force again when it returns |
| Moves | No |
| Safety | **Do not close the shade while the quirk is absent**: the vendor quirk sends a close as raw `up_open`, whose direction is unknown, and no stop is in force. Step 0 backup in hand |
| Who | Agent (state the steps), then owner, session E2 |
| Status | **Retired (#54)**: nothing is stored to keep |
| Evidence | None yet. Will be row `remove-quirk` in `docs/evidence/acceptance.csv` |
| Replaces | new (README Known limitations item 8) |

#### `ACCEPT-CARD-CONTROLS`
*On every shade's card, do Open, Close, Stop and the position slider work, stop at the remote's limits and show no error, before and after a restart?*

| | |
|---|---|
| Feeds | I `command-delivery` ("Commands go out as ZHA sends them", "Stop is passed through once, never synthesised, and its second reply is not an error"); R §3a, §3d; L "What we built" |
| Spec | Not ZCL. Part 3 §2a, §2l, §5c items 2, 4 and 6 |
| Method | Runbook Step 6, per shade, from the card: Close from fully open; Open; slider to 50; Open, then Stop about halfway up. After all shades, one restart, then Close and Open once on each. Rows `card-<shade>-close`, `-open`, `-slider-50`, `-stop`, `-restart-close`, `-restart-open`; each shade's remote limits are checked first (Step 5, rows `limits-<shade>`) |
| Pass / learn | Every control moves the shade the right way; Close stops at the remote's lower limit with smooth fabric, Open at its upper limit, the slider at about 50 %; Stop halts the shade; no error is shown for any control; the card ends at the right position within 2 minutes. Any error, wrong direction or overrun ends the series for that shade (§2, rule 4.7) |
| Moves | Yes |
| Safety | Remote in hand at each shade; its limits checked with the remote first (runbook Step 5; README Install, step 4). The safe line is optional (§2, rule 4.6) |
| Who | Owner, session E, on every shade (scope extended by the owner) |
| Status | Open (needs deploy) |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c items 2, 4 and 6 as revised by #54; `ACCEPT-CLOSE-STOPS-AT-STOP`, `ACCEPT-STOP-SHOWS-REFUSAL`, `ACCEPT-STOP-KEPT-AFTER-RESTART` |

#### `ACCEPT-ALL-NINE`
*Does the ten-and-ten trial pass on every shade?*

| | |
|---|---|
| Feeds | I (Part 3 §5c asks for all nine); L "What we built" |
| Spec | Not ZCL. Part 3 §5c item 3 (the card controls on every shade are `ACCEPT-CARD-CONTROLS`) |
| Method | Not in the runbook (see Status). Before #15's simplification: runbook item 3 on each of the other eight |
| Pass / learn | As those tests, on each shade |
| Moves | Yes |
| Safety | A safe line marked on each shade before its first close; rule 4.7 applies per shade |
| Who | Owner; **needs the scope extended** |
| Status | **Folded into `ACCEPT-CARD-CONTROLS`** (#15 runbook simplified): the card controls run on every shade (ten since 2026-10-06), and the ten-and-ten trial is folded too (`ACCEPT-TEN-OPENS-TEN-CLOSES`) |
| Evidence | None yet. Will be the rows named in Method, in `docs/evidence/acceptance.csv` |
| Replaces | Part 3 §5c item 3 ("on each of the nine"); until #54 also items 2 and 4 |

## 5. Sessions

Each session starts with the remote check (§2, rule 4.4) and the bench installed (§3), and ends with every undo done, the bench removed, and the JSON and CSV copied into `docs/evidence/sessions/`.

| Session | Time | Have ready | Tests |
|---|---|---|---|
| **A. Ask, don't move** | about 75 min, mostly waiting (`RADIO-POLL-INTERVAL`) | Remote; bench; run sheet A; shade at rest mid-travel; shade freshly charged if possible | `ID-DISCOVER-WILDCARD`, `ID-BASIC-VERSIONS`, `ID-POWER-DESCRIPTOR`, `STOP-WHILE-STILL`, `STOP-NO-DEFAULT-RESPONSE`, `STOP-WITHOUT-APS-ACK`, `STOP-MANUFACTURER-SPECIFIC`, `LIMIT-WRITE-READ-ONLY`, `MODE-WRITE-SAME-VALUE`, `REPORT-READ-CONFIG`, `REPORT-BINDING-TABLE`, `POWER-BATTERY-UNITS`, `GROUP-MEMBERSHIP-READ`, `SCENE-TABLE-READ`, `RADIO-POLL-INTERVAL` |
| **B. Every command, from mid-travel** | about 2 h | Remote and its manual (direction-reversal sequence); safe line marked; bench; run sheet B; stopwatch; a second person or phone video helps for start delays | `REMOTE-DIRECTION-REVERSAL` first (it includes `CMD-UP-OPEN-DIRECTION` and `CMD-DOWN-CLOSE-DIRECTION`), `STOP-WHILE-MOVING`, `STOP-JUST-AFTER-START`, `CMD-DUPLICATE-GOTO`, `CMD-NEW-GOTO-WHILE-MOVING`, `POS-DURING-TRAVEL`, `RADIO-FIRST-FRAME-FATE` (10-minute idles, with nothing sent to the shade during them), `REPORT-NONE-OBSERVED` (passive: the bench logs every unsolicited frame through the session's moves and one remote move), `RADIO-LATE-START` |
| **C. Position and limits, with a tape measure** | about 90 min | Remote and its manual (limit programming); safe line marked; tape measure fixed beside the shade; bench; run sheet C | `CMD-GOTO-PCT-ACCURACY`, `POS-READ-VS-PHYSICAL`, `POS-TRACKS-REMOTE`, `LIMIT-PERCENT-SCALE` with `LIMIT-ATTRS-AFTER-REMOTE-SET`, `LIMIT-OPEN-END` |
| **D. Settings experiments (not needed)** | — | Nothing: **no run sheet**, because the firmware answers all three tests (§4c; [firmware analysis](evidence/firmware-analysis.md) §8) | `MODE-LED-BIT`, `MODE-MAINTENANCE-BIT`, `MODE-REVERSAL-BIT` (all answered by firmware) |
| **E. Integration acceptance** | about 45 min, plus about 10 min per shade (runbook Steps 0-6) | The deploy runbook; each shade's remote; `acceptance.csv` | `ACCEPT-QUIRK-LOADED`, `ACCEPT-CARD-CONTROLS` (every shade, with the restart re-check) |
| ~~**E2. Removal behaviour**~~ | — | — | Retired with "Stops at" (#54): nothing is stored, so removal has nothing to clear or keep |
| **F. Other shades (scope extended)** | about 2 h | Scope extension by name; remote for each shade; a safe line marked on each where the test names it; a helper with a remote per extra shade for `MULTI-SHADE-OPEN-CLOSE-ERROR` | `MULTI-SHADE-OPEN-CLOSE-ERROR`, `REPEAT-DOWN-CLOSE-STALL`, `REPEAT-TRAVEL-TIMES` (owner part) |
| **Offline track** (agent, any time) | — | Read-only copies of `zigbee.db`, the box log and `/config/*.csv`; the image once obtained | `RADIO-PARENT-AND-ROUTE`, `REPORT-BATTERY-HISTORY`, `REPEAT-TRAVEL-TIMES` (CSV part), the `FW-*` chain; the bench (built, #42) |

Order: offline track and session A first (nothing moves, and A's answers reshape B). B before C. D has no run sheet. The firmware analysis answers most of A and all of D (status **answered by firmware**): those steps are optional confirmations, and session D is not needed. `CMD-GOTO-LIFT-VALUE`, `CMD-TILT-VALUE` and `CMD-TILT-PERCENTAGE` are removed from B because their frames are unsafe (§3b item 6.2), and `STOP-MANUFACTURER-SPECIFIC`'s moving trial, `CMD-IDENTIFY` and `CMD-GOTO-PCT-OVER-100` because the firmware answers them (§4b). `REPORT-CONFIGURE-AND-WAIT` is moot; B only watches for the radio's own reports. `ACCEPT-LIFT-VALUE-REFUSED` is removed from E: it is checked offline, never on a shade. E is the deploy itself, run with the runbook, independent of A-D. F when the owner extends the scope. There is no hardware session: every test is network and remote only (§2, rule 1).

## 6. Status table

R = reference (Part 1), I = integration, L = the owner's letter (outside the repository).

| Test ID | Area | Status | Feeds | Evidence |
|---|---|---|---|---|
| `ID-DISCOVERY` | Identity | done | R, L, I | Part 1 §2a; `docs/evidence/discovery-office-shade.json` |
| `ID-DISCOVER-WILDCARD` | Identity | answered by firmware | R, L | firmware analysis §2 |
| `ID-NODE-DESCRIPTOR` | Identity | done | R, L | Part 1 §2 |
| `ID-SIMPLE-DESCRIPTOR` | Identity | done | R, L | Part 1 §2 |
| `ID-BASIC-IDENTITY` | Identity | done | R, L | Part 1 §2 |
| `ID-BASIC-VERSIONS` | Identity | answered by firmware | R, L | firmware analysis §7 |
| `ID-WINDOW-COVERING-STATE` | Identity | done | R, L | Part 1 §2 |
| `ID-OTA-QUERY` | Identity | partly | R, L | Part 1 §2; firmware analysis §7 |
| `ID-POWER-DESCRIPTOR` | Identity | open | R | — |
| `CMD-UP-OPEN-DIRECTION` | Commands | done (raises the owner's units) | R, I, L | — |
| `REMOTE-DIRECTION-REVERSAL` | Commands | open (high priority) | R, I, L | — |
| `CMD-DOWN-CLOSE-DIRECTION` | Commands | partly | R, I | Part 1 §3c; #34 |
| `STOP-WHILE-STILL` | Commands | partly | R, L, I | Part 1 §3d (DH:227-228) |
| `STOP-WHILE-MOVING` | Commands | done (#51: the motor halts; #54: no error shown) | R, L, I | firmware analysis §3 |
| `STOP-JUST-AFTER-START` | Commands | open | R | — |
| `STOP-NO-DEFAULT-RESPONSE` | Commands | answered by firmware | R | firmware analysis §3 |
| `STOP-WITHOUT-APS-ACK` | Commands | answered by firmware | R | firmware analysis §3 |
| `STOP-MANUFACTURER-SPECIFIC` | Commands | answered by firmware | R, L, I | firmware analysis §3 |
| `CMD-GOTO-PCT-MEANING` | Commands | done | R, L, I | Part 1 §3g |
| `CMD-GOTO-PCT-ACCURACY` | Commands | open | R, I | — |
| `CMD-GOTO-PCT-OVER-100` | Commands | answered by firmware (motor trial optional) | R | firmware analysis §3 |
| `CMD-GOTO-LIFT-VALUE` | Commands | answered by firmware; do not run | R, I | firmware analysis §3 |
| `CMD-TILT-VALUE` | Commands | answered by firmware; do not run | R | firmware analysis §3 |
| `CMD-TILT-PERCENTAGE` | Commands | answered by firmware; do not run | R | firmware analysis §3 |
| `CMD-DUPLICATE-GOTO` | Commands | done (#51: moves once) | I, R | — |
| `CMD-NEW-GOTO-WHILE-MOVING` | Commands | done (newest go-to wins) | R, I | — |
| `CMD-IDENTIFY` | Commands | answered by firmware | R, I | firmware analysis §2 |
| `LIMIT-ZIGBEE-IGNORES-STOP` | Limits | done, reversed (#54: closes stop at the remote limit) | R, L, I | Part 1 §3a |
| `LIMIT-PERCENT-SCALE` | Limits | partly (#54: 100 % is the remote's lower limit) | R, L, I | — |
| `LIMIT-OPEN-END` | Limits | open | R, I | — |
| `LIMIT-ATTRS-AFTER-REMOTE-SET` | Limits | answered by firmware | R, L, I | firmware analysis §5, §8 |
| `LIMIT-WRITE-READ-ONLY` | Limits | answered by firmware | R, L | firmware analysis §8 |
| `MODE-READ` | Limits | done | R, L | Part 1 §2; `/config/q_*_23.csv` [reported] |
| `MODE-WRITE-SAME-VALUE` | Limits | answered by firmware | R | firmware analysis §8 |
| `MODE-REVERSAL-BIT` | Limits | answered by firmware | R, L | firmware analysis §8 |
| `MODE-LED-BIT` | Limits | answered by firmware | R | firmware analysis §8 |
| `MODE-MAINTENANCE-BIT` | Limits | answered by firmware | R | firmware analysis §8 |
| `MODE-CALIBRATION-BIT` | Limits | answered by firmware | R | firmware analysis §8 |
| `POS-AXIS` | Position | done | R, I | Part 1 §3g |
| `POS-READ-VS-PHYSICAL` | Position | open | R, I | — |
| `POS-TRACKS-REMOTE` | Position | partly | R, I | README "What the cover shows" (no trial) |
| `POS-DURING-TRAVEL` | Position | done (#51: only at the end) | R, I | — |
| `REPORT-NONE-OBSERVED` | Reporting | done (#51: reported at the end of travel) | R, L | Part 1 §3f; firmware analysis §4 |
| `REPORT-READ-CONFIG` | Reporting | answered by firmware | R, L | firmware analysis §4 |
| `REPORT-BINDING-TABLE` | Reporting | moot (firmware) | R | firmware analysis §4 |
| `REPORT-CONFIGURE-AND-WAIT` | Reporting | moot (firmware) | R, L, I | firmware analysis §4 |
| `REPORT-BATTERY-HISTORY` | Reporting | open | R | — |
| `RADIO-READ-LATENCY` | Radio | partly | R, I | Part 1 §4 |
| `RADIO-POLL-INTERVAL` | Radio | open | R, L, I | — |
| `RADIO-FIRST-FRAME-FATE` | Radio | reopened (#51: re-measure with arrival-time reads) | R, L, I | Part 1 §3e |
| `RADIO-LATE-START` | Radio | open | R, I | Part 1 §4 (one event) |
| `RADIO-PARENT-AND-ROUTE` | Radio | open | R | — |
| `POWER-BATTERY-UNITS` | Power | open | R, L, I | — |
| `POWER-CHARGE-COMPARISON` | Power | open | R | — |
| `GROUP-MEMBERSHIP-READ` | Groups/scenes | answered by firmware | R | firmware analysis §2 |
| `SCENE-TABLE-READ` | Groups/scenes | answered by firmware | R | firmware analysis §2 |
| `REPEAT-DOWN-CLOSE-STALL` | Repeatability | open (scope) | R, I | — |
| `REPEAT-TRAVEL-TIMES` | Repeatability | partly (scope) | R, I | Part 1 §4 |
| `MULTI-SHADE-OPEN-CLOSE-ERROR` | Repeatability | open (scope); explained by firmware | R, I, L | firmware analysis §3 |
| `REPEAT-IGNORES-IDENTICAL-MOVES` | Repeatability | open (opportunistic) | R | Part 1 §3h |
| `FW-OBTAIN-IMAGE` | Firmware | done | all FW | `docs/evidence/firmware-analysis.md` |
| `FW-VERIFY-IMAGE` | Firmware | done | R | `docs/evidence/firmware-analysis.md` |
| `FW-UNWRAP` | Firmware | done | R | `docs/evidence/firmware-analysis.md` |
| `FW-IDENTIFY-MCU` | Firmware | done | R | `docs/evidence/firmware-analysis.md` |
| `FW-GHIDRA-LOAD` | Firmware | done | R | `docs/evidence/firmware-analysis.md` |
| `FW-ZCL-TABLES` | Firmware | done | R, L | `docs/evidence/firmware-analysis.md` |
| `FW-STOP-HANDLER` | Firmware | done | R, L | `docs/evidence/firmware-analysis.md` |
| `FW-MANUFACTURER-EXTENSIONS` | Firmware | done | R, L, I | `docs/evidence/firmware-analysis.md` |
| `FW-UART-PROTOCOL` | Firmware | done | R, L | `docs/evidence/firmware-analysis.md` |
| `FW-LIMIT-AND-POSITION-PATH` | Firmware | done | R, L | `docs/evidence/firmware-analysis.md` |
| `FW-SLEEP-AND-POLL` | Firmware | done | R, L | `docs/evidence/firmware-analysis.md` |
| `ACCEPT-QUIRK-LOADED` | Acceptance | open (deploy) | I | — |
| `ACCEPT-CAPTURE-WITH-REMOTE` | Acceptance | retired (#54) | I | — |
| `ACCEPT-CLOSE-STOPS-AT-STOP` | Acceptance | retired (#54) | I, L | — |
| `ACCEPT-TEN-OPENS-TEN-CLOSES` | Acceptance | folded into `ACCEPT-CARD-CONTROLS` (#15) | I, R, L | — |
| `ACCEPT-STOP-KEPT-AFTER-RESTART` | Acceptance | retired (#54) | I | — |
| `ACCEPT-CARD-AFTER-REMOTE-MOVE` | Acceptance | folded into `POS-TRACKS-REMOTE` (#15) | I, R | — |
| `ACCEPT-READBACK-NO-REFRESH` | Acceptance | folded into `ACCEPT-CARD-CONTROLS` (#15) | I | — |
| `ACCEPT-TRAVEL-TIME` | Acceptance | folded into `REPEAT-TRAVEL-TIMES` (#15) | I, R | — |
| `ACCEPT-STOP-SHOWS-REFUSAL` | Acceptance | retired (#54) | I, R | — |
| `ACCEPT-CLEAR-THEN-CLOSE` | Acceptance | retired (#54) | I, R | — |
| `ACCEPT-HIGH-STOP-BAND` | Acceptance | retired (#54) | I | — |
| `ACCEPT-LIFT-VALUE-REFUSED` | Acceptance | do not run live; offline (#47 tests) | I | #47 `tests/quirk/test_smartwings.py` |
| `ACCEPT-REMOVE-INTEGRATION-CLEARS-STOPS` | Acceptance | retired (#54) | I | — |
| `ACCEPT-REMOVE-INTEGRATION-ZHA-STOPPED` | Acceptance | retired (#54) | I | — |
| `ACCEPT-REMOVE-QUIRK-KEEPS-STOP` | Acceptance | retired (#54) | I | — |
| `ACCEPT-CARD-CONTROLS` | Acceptance | open (deploy; every shade) | I, R, L | — |
| `ACCEPT-ALL-NINE` | Acceptance | folded into `ACCEPT-CARD-CONTROLS` (#15) | I, L | — |

## 7. Old names, mapped

Nothing from the earlier lists is dropped.

| Old name | Where it was | New ID(s) |
|---|---|---|
| 8a | Part 1 §8; #4; hardware-test procedure | `CMD-UP-OPEN-DIRECTION`, `CMD-DOWN-CLOSE-DIRECTION` |
| 8b | Part 1 §8 | `RADIO-FIRST-FRAME-FATE`, `ID-NODE-DESCRIPTOR`, `RADIO-POLL-INTERVAL` |
| 8c | Part 1 §8; #4; hardware-test procedure | `REPORT-READ-CONFIG` |
| 8d | Part 1 §8 | `MODE-READ`, `ID-WINDOW-COVERING-STATE` |
| 8e | Part 1 §8 | Deferred on 2026-10-06 while every open was a go-to 0; **revived by #54**, which sends opens as raw `up_open`: the `up_open` runs are now in `REPEAT-DOWN-CLOSE-STALL` |
| 8f | Part 1 §8 | `REPEAT-TRAVEL-TIMES`, `ACCEPT-TRAVEL-TIME` |
| #4 | closed issue; branch `docs/4-hw-procedure` | 8a and 8c above |
| #36 | discovery issue; branch `docs/36-discovery` | `ID-DISCOVERY` |
| Part 3 §5c item 1 | struck (8a not needed) | `CMD-DOWN-CLOSE-DIRECTION` (indirect, done) |
| Part 3 §5c item 2 | acceptance | `ACCEPT-CARD-CONTROLS` (until #54: `ACCEPT-CAPTURE-WITH-REMOTE`, `ACCEPT-CLOSE-STOPS-AT-STOP`, retired) |
| Part 3 §5c item 3 | acceptance | `ACCEPT-CARD-CONTROLS` (`ACCEPT-TEN-OPENS-TEN-CLOSES` folded into it, #15) |
| Part 3 §5c item 4 | acceptance | `ACCEPT-CARD-CONTROLS` (until #54: `ACCEPT-STOP-KEPT-AFTER-RESTART`, retired) |
| Part 3 §5c item 5 | acceptance | `ACCEPT-CARD-CONTROLS` (card right within 2 minutes), `POS-TRACKS-REMOTE` (`ACCEPT-READBACK-NO-REFRESH` and `ACCEPT-CARD-AFTER-REMOTE-MOVE` folded, #15) |
| Part 3 §5c item 6 | acceptance | `ACCEPT-CARD-CONTROLS`, `STOP-WHILE-STILL`, `STOP-WHILE-MOVING` (until #54: `ACCEPT-STOP-SHOWS-REFUSAL`, retired) |
| Part 3 §5c item 7 | acceptance | Retired with "Stops at" (#54; was `ACCEPT-CLEAR-THEN-CLOSE`) |
| Part 3 §5c "on each of the nine" | acceptance | `ACCEPT-CARD-CONTROLS` on every shade (`ACCEPT-ALL-NINE` folded into it, #15) |
| #15 runbook Steps 4-6 | `docs/deploy-runbook.md` | `ACCEPT-QUIRK-LOADED` (Step 4.5), `ACCEPT-CARD-CONTROLS` (Steps 5-6) |
| Part 1 §3c "What would settle up_open" | Part 1 | `CMD-UP-OPEN-DIRECTION` |
| Part 1 §3e "What settles it" 1-2 | Part 1 | `RADIO-FIRST-FRAME-FATE`, `ID-NODE-DESCRIPTOR` |
| Part 1 §3e "What settles it" 3 (sniffer capture) | Part 1 | Dropped: needs extra hardware (§2, rule 1). `RADIO-POLL-INTERVAL`, `RADIO-FIRST-FRAME-FATE` and `FW-SLEEP-AND-POLL` answer it from the hub and the firmware |
| Part 1 §3f "What settles it" | Part 1 | `REPORT-NONE-OBSERVED` (passive re-run); `REPORT-READ-CONFIG` and `REPORT-BINDING-TABLE` as optional confirmations; `REPORT-CONFIGURE-AND-WAIT` (moot) |
| Part 1 §3h | Part 1 | `REPEAT-IGNORES-IDENTICAL-MOVES` |
| Part 1 §7a (calibration bit) | Part 1 | `MODE-CALIBRATION-BIT`, `MODE-REVERSAL-BIT` |
| `MODE-REMOTE-REVERSAL-VISIBLE` | first version of this plan | `REMOTE-DIRECTION-REVERSAL` |
| `GROUP-MULTICAST`, `SCENE-STORE-RECALL` | first version of this plan | Dropped (owner decision, 2026-10-06): Home Assistant uses neither for these shades. `GROUP-MEMBERSHIP-READ` and `SCENE-TABLE-READ` remain |
| `RADIO-SNIFFER-CAPTURE`, `UART-SNIFF` | first version of this plan | Dropped: need extra hardware or an opened unit (§2, rule 1) |
| the letter item 6 (battery units) | letter | `POWER-BATTERY-UNITS` |
| the letter "Not yet sent" item 3 | letter | `REPORT-READ-CONFIG` |
| the letter "Not yet sent" item 4 | letter | `ID-BASIC-VERSIONS` |
| README Known limitations items 5-8 (before #54) | README | `ACCEPT-LIFT-VALUE-REFUSED` (now item 4); the others, and README "Uninstalling", were about "Stops at" and are retired with their tests (#54) |
| `CMD-TILT-VALUE` and `CMD-TILT-PERCENTAGE` (one entry) | first version of this plan | Split into `CMD-TILT-PERCENTAGE` and `CMD-TILT-VALUE` |
| docs/README "Suspected" item 4 | index | `POS-DURING-TRAVEL`, `ACCEPT-READBACK-NO-REFRESH` |

## 8. Prior community work

### 8a. Sources

| Source | What it says | Level |
|---|---|---|
| zigpy discussion [#1184](https://github.com/zigpy/zigpy/discussions/1184), "Smartwings WM25L-Z - Firmware and Device", March 2023. The owner checked it on 2026-10-06 | The device is a Silicon Labs EFR32MG1 Zigbee module plus a separate motor controller (called Tuya there), joined only by a two-wire UART plus power and ground. tube0013 (2023-03-21), from firmware analysis: UART at 9600 baud, TX pin 6, RX pin 7. MattWestb: the serial protocol has "some protocol version" and "some CRC checksum"; the frame format was not decoded. "_TZE200" found in NVM. tube0013: "the zigbee module is just programmed to do up/down and lift percent along with reporting lift percent. it doesn't seem to do anything else"; the firmware lacks group and scene support. The dumps were exchanged privately by email; no image is public | [reported, external] |
| Home Assistant community, ["SmartWings Zigbee ZHA lessons learned"](https://community.home-assistant.io/t/smartwings-zigbee-zha-lessons-learned/910917), jsbrown, 2025-07-14 (27 blinds on ZHA) | SmartWings' own Home Assistant setup guide ends by reversing the open/close direction with the remote, which the poster calls "critical for cover.open_cover cover.close_cover to work". Open or close sent to 6-10 blinds at once often returns `unsupported_cluster_command` after travel begins, while the blinds still complete. Recommends `cover.set_position` | [reported, external] |
| zigbee2mqtt device page, [WM25L-Z](https://www.zigbee2mqtt.io/devices/WM25L-Z.html) | Exposes cover position 0-100 and battery. Offers an `invert_cover` option. The end position is set by moving to the spot and double-pressing Up or Down on the remote; direction is reversed with the remote's programming sequence. It lists Stop generically, which is not evidence that Stop works | [reported, external] |

### 8b. Claims to verify, and the test that does it

| Claim | Conflicts with | Settled by |
|---|---|---|
| Two chips joined by a 9600-baud UART | Nothing; it explains §3a and §3d (§1c) | `FW-IDENTIFY-MCU`, `FW-UART-PROTOCOL`: **confirmed**, 9600 8N1; but the radio is an EFR32MG21, not an EFR32MG1 |
| The radio does only up, down and lift percentage | #36: the shade advertises Stop, Go To Lift Value and both tilt commands | `FW-STOP-HANDLER`, `FW-UART-PROTOCOL`: **partly wrong**. Up, down, **stop** and lift percentage are forwarded properly; lift value and both tilts send malformed frames. Whether the motor halts on the forwarded Stop: `STOP-WHILE-MOVING` |
| The radio "reports lift percent" | Part 1 §3f: no report seen from any of nine | `FW-LIMIT-AND-POSITION-PATH`: **confirmed in code**; it pushes its own reports to the coordinator whenever the motor sends a new position, and refuses Configure Reporting. Why none were seen: `REPORT-NONE-OBSERVED` (re-run) |
| No group or scene support | #36: Groups (0x0004) and Scenes (0x0005) are advertised | `FW-ZCL-TABLES`: **confirmed**; table entries only, every command 0x81 |
| Tuya-style serial protocol ("_TZE200") | Nothing yet; a hypothesis | `FW-UART-PROTOCOL`: **refuted**; `LEN CMD DATA XOR` with no header. The `_TZE200` strings are in an NVM area left by an earlier Tuya firmware |
| `invert_cover` exists | Part 1 §3g: these shades follow the ZCL axis | `POS-AXIS` (done); `REMOTE-DIRECTION-REVERSAL` (whether a remote reversal is visible) |
| Direction is reversed with the remote at setup, per SmartWings' guide | Part 1 §3c: raw `down_close` lowers the box's shades (#34), which may hold only for units set up that way | `REMOTE-DIRECTION-REVERSAL` |
| Simultaneous open/close returns `unsupported_cluster_command` while the blinds complete | Part 1 §3d: 0x81 is the answer to Stop; open and close themselves are not known to draw it | `FW-STOP-HANDLER`: **explained**; with Disable Default Response clear every command draws SUCCESS then 0x81, so a lost SUCCESS leaves the 0x81. `MULTI-SHADE-OPEN-CLOSE-ERROR` confirms |
| Remote programming of the end position | — | Used as the method in `LIMIT-PERCENT-SCALE` and `LIMIT-ATTRS-AFTER-REMOTE-SET` |

## 9. Sources

1. ZCL Revision 8 (07-5123-08), sections and PDF line numbers as cited. The PDF is not committed.
2. [Part 1](1-the-devices.md), [Part 3](3-what-must-be-built.md) §5c, the README "Known limitations", `openspec/specs/*`.
3. Branches: `docs/36-discovery` (`docs/evidence/discovery-procedure.md`, `discovery_user.py`), `docs/4-hw-procedure` (`docs/evidence/hardware-test-procedure.md`, closed #4). The deploy runbook is `docs/deploy-runbook.md`.
4. zigpy 2.3.0 `zigpy/zcl/__init__.py:806-860` (`Cluster.request`, with `ask_for_ack` and `disable_default_response` at `:815-816`); zha 2.3.0 `zha/application/platforms/cover/__init__.py:224-254` (no tilt features for type 0); the quirk's constants in `quirk/zhaquirks/smartwings/wm25lz.py:190-221`.
