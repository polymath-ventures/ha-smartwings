# Part 1: The devices

SmartWings WM25/L-Z Zigbee roller-shade motors: what the Zigbee WindowCovering cluster requires, where these motors depart from it, and what the hub cannot do about it.

Written 2026-10-05. Measurements are from nine installed units in one house, taken 2026-10-03 and 2026-10-04. Results of tests run on 2026-10-05 were reported by the HA agent and are tagged **[reported]**. On 2026-10-06 the Office Shade's discovery run (#36) was added as §2a, and every **[spec]** claim was checked against the ZCL revision 8 text (§9). Later on 2026-10-06 the radio module's firmware was analysed (#43); its findings are tagged **[firmware]** and summarised in §2b. That evening, bench session B on the Office Shade measured what a read returns during travel, that the shade reports its position when travel ends, and that it halts on Stop (#51); §3c-§3f and §4 carry those measurements, cited as #51. Later that day, with the owner watching, Zigbee closes stopped at the limits set with the remote on two shades, which reverses §3a (#54).

## 0. Sources and how claims are marked

| Short name | Path |
|---|---|
| DH | `~/.hermes/profiles/ha/skills/smart-home/home-assistant/references/smartwings-device-handler.md` (the research record) |
| ARCH | `~/.hermes/profiles/ha/skills/smart-home/home-assistant/references/smartwings-calibration-architecture.md` |
| REV | `~/.hermes/profiles/ha/cache/scratch/claude_harden_r1b.txt` (review R1) |
| zigpy | `venv314/.../site-packages/zigpy/zcl/clusters/closures.py` (zigpy 2.3.0) |
| zha-cover | `venv314/.../site-packages/zha/application/platforms/cover/__init__.py` (zha 2.3.0) |
| UPQ | `venv314/.../site-packages/zhaquirks/smartwings/wm25lz.py` (zha-quirks 2.3.0, the released vendor quirk) |
| ZCL8 | Zigbee Cluster Library Specification, Revision 8, CSA document 07-5123-08 (December 2019), <https://csa-iot.org/wp-content/uploads/2022/01/07-5123-08-Zigbee-Cluster-Library-1.pdf> (SHA-256 `ad536e1d95a40ca2…`). Not in the repo (copyright). Cited by section, table and the PDF's own margin line number, written L11680; the line numbers run continuously through the document. |
| HACT | Home Assistant community thread "SmartWings Zigbee + ZHA lessons learned", first post by jsbrown, 2025-07-14: <https://community.home-assistant.io/t/smartwings-zigbee-zha-lessons-learned/910917>. The poster has 27 SmartWings blinds on ZHA (Home Assistant 2025.7, Sonoff Zigbee 3.0 Dongle V2 Plus). Read 2026-10-06. |
| DISC | `docs/evidence/discovery-office-shade.json` (the #36 discovery run on the Office Shade, 2026-10-06). Cited by JSON line, or by frame number `n` in `frames`. |
| FA | `docs/evidence/firmware-analysis.md` (#43): analysis of a full flash dump of one WM25/L-Z radio module, application version 2, the version our shades report. Cited by section; it cites flash addresses. |

Each claim carries one of these tags:

| Tag | Meaning |
|---|---|
| **[measured]** | Observed on the real shades; the record line is cited. |
| **[source]** | Read in the installed library code; file and line are cited. |
| **[spec]** | Paraphrase of the ZCL specification's Window Covering cluster (chapter 7, Closures; §7.4 in revisions 7 and 8) or its foundation chapter 2. Checked against the ZCL8 text on 2026-10-06; §9 gives the section, table and line for each claim and a verdict. |
| **[suspected]** | Consistent with the evidence but not proven. What would prove it is stated alongside. |
| **[open]** | Unresolved. The record contradicts itself, or nobody has run the test. |
| **[reported]** | Reported by the HA agent on 2026-10-05, not independently verified. Where the agent named an evidence file on the box, it is cited. With the qualifier "external", **[reported, external]**, it is a third party's public report on their own units (for example HACT), not checked on ours. |
| **[unmeasured]** | Stated only in a code comment. No measurement in the record supports it. |
| **[firmware]** | Read in the radio module's firmware (FA, which gives the flash address). It shows what the **radio** does; the motor controller behind it is a separate chip whose firmware we do not have. |

A tag may carry a qualifier after a comma, such as **[measured, once]** or **[measured, contradictory]**. The qualifier limits the tag; it does not change its meaning.

## 1. What a compliant WindowCovering device must do

### 1a. Commands (server side, cluster 0x0102)

| ID | zigpy name | Spec status (ZCL8 Table 7-45) | What it must do [spec] |
|---|---|---|---|
| 0x00 | `up_open` | mandatory | Move the lift to InstalledOpenLimit – Lift, as fast as possible (§7.4.2.2.1, L11667-11669). |
| 0x01 | `down_close` | mandatory | Move the lift to InstalledClosedLimit – Lift, as fast as possible (§7.4.2.2.2, L11673-11676). |
| 0x02 | `stop` | mandatory | "Stop any adjusting to the physical tilt and lift that is currently occurring" (§7.4.2.2.3, L11680-11682). |
| 0x04 | `go_to_lift_value` | optional | Move to an absolute lift value in cm, the units of the installed limits; out of bounds returns INVALID_VALUE (§7.4.2.2.4, L11687-11691). |
| 0x05 | `go_to_lift_percentage` | optional in the table, but "the device must support either the Go To Lift Percentage or the Go To Tilt Percentage command" (L11704-11705). A lift-only device SHOULD reject Go to Tilt Percentage with UNSUPPORTED_COMMAND (L11726-11727), so for it Go to Lift Percentage is the one that satisfies L11704-11705. | Move to a percentage mapped between InstalledOpenLimit and InstalledClosedLimit; over 100 returns INVALID_VALUE. An open-loop lift device SHOULD treat 0 % as Down/Close and any other value as Up/Open (§7.4.2.2.5, L11696-11705). The percentage runs from the up/open position (§7.4.2.1.2.8, L11603-11605), so 0 % is the open limit and 100 % the closed limit. |

The IDs and payload schemas are at zigpy `closures.py:808-827` **[source]**. The `go_to_lift_percentage` field is named `percentage_lift_value` (uint8) at `:816-819`. Table 7-45 also lists Go to Tilt Value (0x07) and Go to Tilt Percentage (0x08), both optional.

### 1b. Attributes that matter here

| ID | zigpy name | Type / access | Meaning |
|---|---|---|---|
| 0x0000 | `window_covering_type` | enum8, r, mandatory | 0 = roller shade (`:706-716`, `:747-749`) |
| 0x0007 | `config_status` | bitmap8, r, mandatory | Bits at `:719-726`: 0x01 Operational, 0x02 Online, 0x04 Open/Up commands reversed, 0x08 closed-loop lift, 0x10 closed-loop tilt, 0x20 encoder-controlled lift, 0x40 encoder-controlled tilt. These match ZCL8 Table 7-42 (L11601); bit 3 clear means "Lift control is Open Loop". |
| 0x0008 | `current_position_lift_percentage` | uint8, access `rps`: readable, **reportable**, scene (`:772-774`). ZCL8 Table 7-40: access RSP, default 0xFF, M\*: mandatory only with closed-loop lift control (L11566-11570). | 0 = fully open, 100 = fully closed |
| 0x0010 | `installed_open_limit_lift` | uint16, **read-only** (`:779-781`). ZCL8 Table 7-43: R, cm, default 0x0000, M\*. | Open end of travel, in cm, not percent. "Ignored if the device is running in Open Loop Control" (§7.4.2.1.3.1, L11624-11626). |
| 0x0011 | `installed_closed_limit_lift` | uint16, **read-only** (`:782-784`). ZCL8 Table 7-43: R, cm, **default 0xffff**, M\*. | Closed end of travel, likewise ignored in open loop (§7.4.2.1.3.2, L11628-11630). 0xFFFF is the spec's default, confirmed **[spec]**. |
| 0x0017 | `window_covering_mode` | bitmap8, rw, mandatory (`:798-800`). ZCL8 Table 7-43: RW, M, **default 0000 0100**. | Bits at `:729-733`, matching ZCL8 Table 7-44: 0x01 motor direction reversed, 0x02 run in calibration mode, 0x04 maintenance mode ("the motor cannot be moved over the network"), 0x08 LED feedback. Table 7-44 defines no bit above bit 3. |

**[source]** The lift axis convention is restated by ZHA itself: "In ZCL 0 is fully open, 100 is fully closed" (zha-cover `:336-337`, `:751-753`).

### 1c. The two things the spec gives the hub, and the one it withholds

A compliant device gives the hub two guarantees. First, the run-to-limit commands and 100 % both mean "the installed closed limit". Second, the device can report its position when it changes. The spec does not give the hub a standard way to set the installed limits. Both limit attributes are read-only (`:779-784`; ZCL8 Table 7-43). They are set at installation by a means the spec leaves to the manufacturer, which here is the 433 MHz remote. This gap is why a hub cannot repair item 3a, even in principle.

**Spec check [spec].** Both guarantees hold only for a **closed-loop** lift device. In open loop the installed limits are "ignored" (§7.4.2.1.3.1-2, L11624-11630), CurrentPositionLiftPercentage is not required (Table 7-40 note, L11566-11570; §7.4.2.1.2.8, L11603-11607), though once implemented it SHALL be reported (§7.4.2.5, L11755-11760; see 3f), and Go to Lift Percentage SHOULD collapse to open or close (L11701-11702). The spec's only word on how limits get set is the Mode calibration bit: "limits are either setup using physical tools or limits are learned by the controller based on physical setup of the Window Covering by an installer" (Table 7-44, bit 1). No command or writable attribute sets them. The gap is real: the spec does not cover it.

## 2. What these motors declare about themselves

| Reading | Value | Interpretation | Evidence |
|---|---|---|---|
| `config_status` | 3 on all nine | 0x01 Operational + 0x02 Online. The reversal bit (0x04) is **clear**. The closed-loop and encoder bits are **clear**, so by its own declaration this is an open-loop lift device. | DH:386, DH:103-110 **[measured]**; bit values zigpy `:719-726` **[source]**. **[firmware]** 0x03 is the compiled default and nothing ever writes it, so it can never show a reversal (FA §2, §8) |
| `window_covering_type` | 0 | Roller shade | DH:387 **[measured]** |
| `installed_open_limit_lift` | 0 | — | DH:180 **[measured]** |
| `installed_closed_limit_lift` | 65535 on all nine | The spec's default (ZCL8 Table 7-43). It does **not** reflect the stop configured with the remote. **Not a violation** by itself: the device declares open loop, and in open loop this attribute is "ignored" (§7.4.2.1.3.2, L11628-11630). See §9. | DH:180-182, DH:302-304 **[measured]**. **[firmware]** No code writes 0x0010-0x0013, and nothing the radio reads from the motor carries a limit (FA §5) |
| `window_covering_mode` (0x0017) | 20 (0x14) on all nine | 0x14 has bit 2 (0x04) set. Read literally against Table 7-44, the value says the motor is in **maintenance mode**, in which "the motor cannot be moved over the network". Yet the shades still accept movement over the network. **The spec is ambiguous here**: Table 7-43's default for Mode is 0000 0100, which itself sets bit 2. The shade reports the spec's default, and that default contradicts the bit's stated meaning. 0x10 (bit 4) is undefined in Table 7-44 and so reserved (§1.6.2, L2113-2117), and a reserved bit of a bitmap attribute "SHALL be set to zero for transmission" (§2.3.1, L2229-2231). So 0x14 is the default plus one reserved bit. Bit 2 is a spec ambiguity, not evidence of a fault. Bit 4, a separate matter, is a minor violation. What bit 4 does on this firmware is **[open]**. | DH:180 **[measured]**, as "mode" with no attribute ID. Test 8d re-read 0x0017 explicitly and got 20 on all nine (`/config/q_*_23.csv` on the box) **[reported]**. The Office Shade's cached value is 20 (DISC line 482). **[firmware]** 0x14, bit 4 included, is the compiled default. A write is stored in RAM only: nothing reads it, nothing is sent to the motor, and it reverts at restart (FA §2, §8). So no Mode bit does anything on this firmware. |
| attribute 0x000E | unsupported (HTTP 500 via zha_toolkit) | **Not a defect.** 0x000E is not a ZCL WindowCovering attribute (zigpy defines none at that ID, and ZCL8 Tables 7-40 and 7-43 list none). "Percent100ths" is a Matter attribute. Discovery does not list it either (§2a). | DH:385 **[measured]**; zigpy `:745-806` **[source]** |

Note on DH:171-175. That passage says `config_status = 3` means "the Open_up_commands_reversed bit IS set". That is wrong, and the same record corrects it at DH:103-110. Three is 0x01 | 0x02.

**Identity [measured].** As stored in a read-only copy of the box's `zigbee.db`, 2026-10-06. The owner's letter to SmartWings (kept outside the repository) cites these values.

| Source | Field | Value |
|---|---|---|
| Basic (0x0000) | 0x0000 ZCL version | 8 |
| Basic (0x0000) | 0x0004 manufacturer name | "Smartwings" |
| Basic (0x0000) | 0x0005 model identifier | "WM25/L-Z" |
| Basic (0x0000) | 0x0007 power source | 0 (unknown) |
| Basic (0x0000) | 0xFFFD cluster revision | 3 |
| Node descriptor | manufacturer code | 4098 (0x1002) |
| Node descriptor | logical type | 2 (end device) |
| Node descriptor | MAC capability flags | 0x80: allocate address only, so receiver-on-when-idle (0x08) is clear and the receiver is off when idle |
| Simple descriptor | endpoint, profile, device type | 1, 260 (0x0104), 0x0202 (Window Covering) |
| Simple descriptor | server (input) clusters | 0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102 |
| Simple descriptor | client (output) clusters | 0x0003, 0x0019 |
| OTA (0x0019) | 0x0002 current file version | 2 |
| `ota_query_cache` | image type, manufacturer | 0, 4098 |

### 2a. Discovery (2026-10-06)

The owner ran the #36 procedure (`docs/evidence/discovery-procedure.md`, handler `docs/evidence/discovery_user.py`) on the Office Shade only, IEEE `60:83:da:ff:fe:a0:00:02`, from 12:35:27 to 12:36:30 UTC on 2026-10-06. It sent only ZCL general commands: Discover Attributes Extended, Discover Commands Received, Discover Commands Generated and one Read Attributes. The shade answered all 61 frames. None went unanswered, none was re-sent, and the run did not stop early (DISC lines 10-17). Nothing moved (owner, present at the shade). The output is DISC. Everything in this section is **[measured]** on one shade of nine.

1. **No manufacturer-specific attributes or commands are advertised.** Each of the eight clusters on endpoint 1 answered all three discoveries in one complete page, both plain and with manufacturer code 0x1002. Every list asked for with 0x1002 came back empty (the `found_per_cluster` summary at DISC lines 18-99; for example, the 0x0102 `manufacturer_0x1002` block at lines 566-583). The probes of 0xFC01 and 0xEF00, which the shade does not advertise, came back as empty, complete lists both ways (DISC lines 722-814; frames 49-60). The shade did not answer them with UNSUPPORTED_CLUSTER. So a cluster it lacks looks the same as a cluster with no extensions. **Read this as "none advertised", not "none exist".** The spec mentions hiding extensions in one place only, in the Discover Commands Received Response with the 0xFFFF wildcard manufacturer code. There the response's manufacturer code "will not be present if the cluster supports no manufacturer-specific extensions, or the manufacturer wishes to hide the fact that it supports extensions" (§2.5.19.1.1, L3316-3323). This run used 0x1002, not the wildcard. The spec defines no hiding for attribute discovery (§2.5.23.1.1, L3418-3423) or for generated-command discovery (§2.5.21). So the empty lists are what the shade advertises; whether undisclosed extensions exist is not something discovery can settle. Item 4 also shows that this firmware's discovery lists are not a complete inventory.
2. **Window Covering (0x0102) attributes** (frame 31; DISC lines 496-546; cached values at lines 478-493). Access control bits are those of §2.5.23.1.5, Figure 2-41 (L3435-3438): 0x01 readable, 0x02 writable, 0x04 reportable.

   | ID | Type | Access | Cached value | Note |
   |---|---|---|---|---|
   | 0x0000 | enum8 (0x30) | 0x05 readable, reportable | 0 | Rollershade (Table 7-41) |
   | 0x0007 | map8 (0x18) | 0x05 | 3 | Operational, Online; lift control **open loop** (Table 7-42, bit 3 = 0) |
   | 0x0008 | uint8 (0x20) | 0x05: **reportable** | 84 | Matches Table 7-40's RSP |
   | 0x0010 | uint16 (0x21) | 0x05 | 0 | Spec default (Table 7-43) |
   | 0x0011 | uint16 (0x21) | 0x05 | 65535 | Spec default 0xffff (Table 7-43) |
   | 0x0012 | uint16 (0x21) | 0x05 | 0 | Tilt limit on a lift-only shade, at its default. Allowed, unused. |
   | 0x0013 | uint16 (0x21) | 0x05 | 65535 | Same |
   | 0x0017 | map8 (0x18) | 0x07 readable, writable, reportable | 20 (0x14) | See §2 |
   | 0xFFFD | uint16 (0x21) | 0x05 | 3 | Read in frame 61 (DISC line 2876). Revision 3 is the highest in the cluster's revision table (§7.4.1.1, L11552). |

   The types match Tables 7-40 and 7-43. Nothing else is listed: none of 0x0001-0x0006, 0x0009, 0x0014-0x0016 or 0x0018-0x0019, and nothing at 0x000E (§2).
3. **Window Covering commands received: 0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08** (frame 32, raw `08 22 12 01 00 01 02 04 05 07 08`; DISC lines 547-559). The shade lists Stop (0x02) as a command the cluster "can process" (§2.5.18.2, L3302-3303), yet it answers Stop with 0x81 (3d). It also lists Go to Tilt Value and Go to Tilt Percentage (0x07, 0x08), although it declares itself a lift-only roller shade. A lift-only device SHOULD answer Go to Tilt Percentage with UNSUPPORTED_COMMAND (§7.4.2.2.7, L11726-11727). Neither tilt command was sent. Commands generated: none (frame 33). That is consistent with §7.4.2.3 (L11730-11733), under which the server answers only with Default Response.
4. **Identify (0x0003), Groups (0x0004) and Scenes (0x0005) list no received commands** (frames 14, 20 and 26: discovery complete, no IDs). Yet ZCL8 makes Identify and Identify Query mandatory (Table 3-32, L4237), along with Add Group and View Group (Table 3-37, L4366) and Add Scene through Recall Scene (Table 3-42, L4622). §2.5.18.3 (L3305-3308) asks for the commands that the cluster processes. The same clusters do list the response commands they generate (frames 15, 21 and 27). Either these received-command lists are incomplete or the mandatory commands are missing. **[firmware]** The commands are missing: these clusters have attribute-table entries but no command handlers, and every server command to them gets 0x81 (FA §2). It does not affect the shade's use as a cover.
5. **Every frame was answered at its first attempt**: 61 of 61, with no re-sends. Replies took 0.21-3.73 s, almost all about 1 s (`elapsed_s` in each frame). These were general commands sent back to back, about one a second. This does not settle 3e, which concerns the first frame after the shade has been idle, and move commands.
6. **Other frames the shade sent** (`unmatched_frames`, DISC lines 2911-2931).
   1. At 12:35:43 UTC, an OTA Query Next Image Request (cluster 0x0019, command 0x01), raw `01 09 01 00 02 10 00 00 02 00 00 00`: field control 0x00, manufacturer code 0x1002, image type 0x0000, file version 0x00000002. This is routine OTA polling, and it matches the identity table above. The same shade also queried at 07:35:49 EDT (11:35:49 UTC) that morning **[measured]**. The evidence is the `ota_query_cache_v15` row for IEEE `60:83:da:ff:fe:a0:00:02` in the read-only copy of the box's `zigbee.db` taken on 2026-10-06 (the copy behind §2's identity table): endpoint 1, manufacturer_code 4098, image_type 0, current_file_version 2, last_updated 1791286549.41. The other eight SmartWings rows in that table carry the same values, with last_updated between 07:35:47 and 07:35:54 EDT.
   2. At 12:36:29 UTC, a second copy of the reply to frame 60 (0xEF00 Discover Commands Generated with code 0x1002, same TSN 0x3e, raw `0c 02 10 3e 14 01`), about 1 s after the first. It is a late duplicate and harmless.

**What the run did not cover.** It sent no cluster-specific command, so it neither re-tests Stop (3d) nor tests the tilt commands. It did not read the reporting configuration (8c).

### 2b. What the radio firmware shows (2026-10-06)

FA analyses a full flash dump of one radio module running application version 2, manufacturer 0x1002, image type 0, the same identity our shades report. Everything here is **[firmware]**: what the radio does. The motor controller is a separate chip, and what it does with what the radio sends is not in this image.

1. **Two chips, confirmed.** The radio is a Silicon Labs EFR32MG21 (Series 2, Cortex-M33) running EmberZNet 6.9.1, not the EFR32MG1 reported in #1184. It talks to the motor controller over a 9600-baud UART with frames `LEN CMD DATA… XOR`. It is not Tuya's MCU protocol (FA §1, §5).
2. **Every advertised Window Covering command is forwarded.** Up/Open, Down/Close and **Stop** become serial `03 01 02`, `03 02 01` and `03 03 00`. Go to Lift Percentage becomes a frame carrying the percentage byte unchanged. Go to Lift Value and both tilt commands send malformed frames and must never be used (FA §3).
3. **Every one of them is answered twice** when the Disable Default Response bit is clear, as ZHA sends them. Each handler sends Default Response SUCCESS, then returns "not handled", so the framework sends a second Default Response, 0x81, with the same TSN. With the bit set only the 0x81 is sent (FA §3). This is where Stop's 0x81 comes from (3d), and it explains HACT's intermittent `unsupported_cluster_command` on open and close (3c).
4. **The radio handles no limit and no direction.** It sends none to the motor and reads none from the motor's messages. No code writes 0x0007 or 0x0010-0x0013; a network write to 0x0017 is stored in RAM, and nothing reads it or forwards it (FA §5, §8). This shows what the radio processes, not everything the motor sends: the radio ignores some bytes of the position message and drops unknown message types, and those could carry more.
5. **Reporting is the radio's own.** Configure Reporting and Read Reporting Configuration are refused with 0x81. Instead, whenever the motor sends a new position or battery value, the radio writes it and pushes a Report Attributes straight to the coordinator (FA §4). See 3f.
6. **Groups, Scenes and Identify have no command handlers** (FA §2). See §2a item 4.
7. **Battery** 0x0021 is the motor's byte copied unchanged; 0x0020 is never set (FA §6).
8. **Polling.** Long and short poll intervals are 1 s (FA §9).

## 3. Where the motors depart from the cluster, item by item

### 3a. The limits set with the remote are honoured over Zigbee (reversed 2026-10-06)

**[measured] Reversed (#54, 2026-10-06, owner watching).** On the Office Shade, `go_to_lift_percentage(100)`, sent twice, and a raw `down_close` (0x01) both stopped at the lower limit programmed with the remote, and the shade then reported that position as lift 100. On the guest blackout, Home Assistant's own close stopped at its remote limit too. So the motor scales Zigbee positions between the limits set with its remote, with lift 100 at the lower limit, and enforces those limits for Zigbee commands as it does for the remote. A shade that closes too far is fixed by programming its limits with the remote, as SmartWings' remote programming guide for roller shades describes: hold DOWN and STOP for 5 s, move the shade, hold DOWN and STOP for 2 s to save the lower limit; the same with UP for the upper one. The software's own closed limit ("Stops at": the 0xFC01 setting, lift scaling, capture) rested on the premise below and was retired (#54).

**[suspected] What the earlier overruns were.** What differed when the record saw the shade run past the stop (below) is not known: a limit not yet programmed at the time, a different handler or command form, or a limit reprogrammed since are all possible. Nothing depends on settling this now. `LIMIT-ZIGBEE-IGNORES-STOP` is done with this reversed result.

**[measured] Still inconsistent.** The device holds and enforces its limits, yet it declares open-loop lift and reports `installed_closed_limit_lift` as 65535 (unset) (§2). Nothing in the radio reads or writes the limits (FA §5, §8), so the hub can neither read nor set them; only the remote can.

The rest of this section is the 2026-10-05 text, kept as the history of the retired premise.

**What was observed [measured, superseded by #54].** Each user sets a stop with the SmartWings 433 MHz remote, and the remote stops the shade there every time. Over Zigbee, the shade drives past that stop with **either** command form: run-to-limit (`down_close`) and an absolute `go_to_lift_percentage` at the end of travel. On a blackout shade it went far enough that the fabric bunched (DH:283-287; DH:223-227 for the go-to case, which led to version 8 reverting the version 7 translation; DH:265-268 for the office shade). Meanwhile `installed_closed_limit_lift` reads 65535 (§2).

**What this proves.** The remote talks to the motor's controller directly, and the motor stops correctly when commanded that way. So the mechanics, the battery, the limit switch or encoder, and the stored stop are all fine. The fault lies in how commands arriving over Zigbee are executed.

**What it does not prove.** Two mechanisms fit the evidence, and from the hub they cannot be told apart. In the first, the Zigbee module's percentage scale is anchored to the motor's full mechanical travel rather than to the stored stop. In the second, the motor applies the stored stop only to commands from its own radio path. A vendor engineer can tell them apart in minutes.

**Classification (2026-10-05; superseded for the behaviour by #54, still apt for the reporting): inconsistent, arguably a violation, not airtight [spec, checked].** Down/Close moves the lift to InstalledClosedLimit – Lift (§7.4.2.2.2, L11673-11676), and Go to Lift Percentage maps onto the installed limits (§7.4.2.2.5, L11697-11699). But the device declares open-loop lift (§2a item 2; Table 7-42 bit 3), and in open loop the installed limits are "ignored" (§7.4.2.1.3.2, L11628-11630) and 0xFFFF is their default (Table 7-43). The case for a violation rests on reading the remote-set stop as the installed closed limit. The spec says only that limits are set "using physical tools" or learned "based on physical setup ... by an installer" (Table 7-44, bit 1); it does not say a remote-set stop is one. The device is plainly inconsistent with itself. It holds a closed limit and enforces it for its own remote. It declares open loop and reports the limit as unset over Zigbee. Yet it executes percentages proportionally and reports a position, as a closed-loop device would, rather than collapsing them to open or close as an open-loop device SHOULD (L11701-11702). A correct closed-loop device would set bit 3, report the stop in 0x0011, stop there on `down_close` and scale percentages to it. Put this to the vendor as an inconsistency and a request, not as a clause breached.

### 3b. Run-to-limit and absolute commands behave differently on some units

**[measured]** On one unit ("Right master blackout"), `open_cover` (wire `up_open` or swapped, see 3c) stalled partway three times: at 58, then 45 → 60. `set_cover_position(100)`, an absolute go-to lift 0, reached the top first time within 15 s. The same `open_cover` worked on three sibling shades, so this is per-unit (DH:210-222). The remote drives the same shade to both ends perfectly (DH:213-216). A community thread reports the same symptom (DH:221-222). That thread is cited secondhand in DH, so I have not checked it myself.

**Classification: violation if it reproduces [spec, checked].** A run-to-limit command that stops short with no obstruction does not reach the installed limit. Up/Open moves the lift to InstalledOpenLimit – Lift "as fast as possible" (§7.4.2.2.1, L11667-11669); the open limit reads 0, its default (Table 7-43). Unlike the closed limit in 3a, the open end is not in dispute. The sample is one unit, observed on one day. Neither the cause nor the reproduction rate is known **[open]**.

**Consequence for software.** Until #54 the handler sent every open as an absolute go-to lift 0, to avoid this stall, and every close with a stop set as a go-to short of the stop (3a). Since #54 the motor is known to stop at its remote-set limits (3a) and raw `up_open` raised the one unit tried (3c), so U sends open and close as ZHA does, `up_open` and `down_close`. If the stall recurs, a set position of 100 (a go-to lift 0) still reaches the top; the stall count is `REPEAT-DOWN-CLOSE-STALL` in the test plan, which now counts `up_open` runs too.

### 3c. Which way `up_open` and `down_close` move these units: `down_close` lowers them

**[source]** The released vendor quirk swaps `up_open` and `down_close` for **every** unit (UPQ `:49-54`). It has no condition, and it does not touch the lift axis or percentages.

**[measured, contradictory]** The record says both that "with the swap, `open_cover` from HA raises the shades" (DH:171-175) and that "with the swap applied anyway, `close_cover` drove a shade to the fully-UP end" (DH:255-259). These may have been taken under different handler versions. Neither passage records which wire command ID was sent.

**If the swap is needed, it is a violation [spec, checked].** The device would be running Up/Open as down while declaring neither `config_status` bit 0x04 (Table 7-42, bit 2: "Open/Up Commands have been reversed") nor `mode` bit 0x01 (Table 7-44, bit 0: "motor direction is reversed"). If the swap is not needed, the vendor quirk is wrong for these units. For Down/Close the swap is not needed (below), so there is no violation there.

**[measured, indirect]** Raw `down_close` (0x01) lowers these units (issue #34, read-only look at the owner's box, 2026-10-06). The deployed v18 quirk (`/config/custom_zha_quirks/smartwings_wm25lz_readback.py`, header `:30`, `command()` `:296-414`) does not swap: with no closed limit in force it sends `down_close` (0x01) unchanged. No closed limit is in force on any shade (no 0xFC01 row in `zigbee.db`), so every close from Home Assistant on the box goes out as raw 0x01, and the owner reports that closes from Home Assistant work. The frame was not captured on the air, hence "indirect". The vendor quirk's swap sends a close as raw `up_open` (0x00), whose direction on these units is unobserved, while raw `down_close` (0x01) is known to lower them; so the swap is not used for a close.

**[measured]** Raw `up_open` (0x00) raises the Office Shade: sent from lift 71, the shade travelled to the top, the owner watching, and a read afterwards returned 0 (#51, session B, 2026-10-06).

**Status.** Resolved for the owner's units: raw `down_close` lowers them **[measured, indirect]** and raw `up_open` raises them **[measured]** (`CMD-UP-OPEN-DIRECTION`). The vendor quirk's swap is wrong for them. U sends open as `up_open` and close as `down_close`, both unswapped, as ZHA sends them (#34, #54). Until #54 every open was `go_to_lift_percentage(0)`, while raw `up_open`'s direction was unobserved. The earlier (retired) handler sent the swapped frame, `up_open`, for a close with no closed limit (`ReadbackWindowCoveringCluster.command` in the retired `custom_components/smartwings/quirks/smartwings_wm25lz.py`).

**[reported, external]** HACT reports three things about other people's units.
1. SmartWings' own Home Assistant setup guide ends with a step that reverses the open/close state. The poster calls that step "critical for cover.open_cover cover.close_cover to work". The post does not say how the reversal is done, and the guide itself has not been read here.
2. Sending `cover.open_cover` or `cover.close_cover` to many blinds at once (usually 6-10) "will often, after the blinds begin their travel", return an `unsupported_cluster_command` error. "The blinds will complete the operation successful, but the automation will break." Compare 3d and 3e.
3. The post recommends `cover.set_position` instead of open/close.

Item 1 raises a hypothesis, not a finding: the post says a setup step reverses the open/close *state*, which may mean the direction of raw `up_open` and `down_close` is a per-unit setting the installer can reverse rather than a fixed property of the firmware. The post does not show which commands or settings that step changes. Our box evidence (raw `down_close` lowers) therefore holds for the owner's units as they are currently programmed. It would not necessarily hold after one of them is re-paired or reprogrammed. If such a reversal were in force, ZCL8 would expect `config_status` bit 2 or `mode` bit 0 to show it (Table 7-42, Table 7-44). On the owner's units both bits are clear (§2). **[firmware]** This radio firmware never sets them: nothing writes `config_status` (fixed at 0x03), a network write to `mode` is stored in RAM but nothing reads it, and no message the radio parses from the motor carries a direction (FA §5, §8). So if a remote-set reversal lives in the motor controller, the hub cannot detect it from these attributes. (The radio ignores some bytes and message types from the motor, so the motor may know more than it can pass on.)

**What would settle `up_open`.** Put a shade mid-travel. Send one raw `up_open` (0x00) frame from ZHA's "Manage Zigbee device" panel or `zha_toolkit` and watch it. Record the frame, the IEEE and the direction.

### 3d. Stop is rejected

**[measured]** The firmware answers Stop (0x02) with `UNSUP_CLUSTER_COMMAND` (0x81) (DH:227-228). The handler passes Stop straight through (`command`, the "pass straight through" branch). ZHA then raises `ZHAException("Failed to stop cover: …")` (zha-cover `:728-735` **[source]**), so the user sees an error. The remote stops a moving shade correctly, so again the motor can do it.

**[measured]** The shade advertises Stop. Its Discover Commands Received list for 0x0102 includes 0x02 (§2a item 3; DISC frame 32).

**[firmware]** The radio does not refuse Stop. With the Disable Default Response bit clear (ZHA's default), its Stop handler sends Default Response SUCCESS, writes the serial stop `03 03 00` to the motor controller, and returns "not handled", so the framework then sends a second Default Response, 0x81, with the same TSN. Up/Open, Down/Close and the go-to commands have the same bug (FA §3). A hub that matches replies by TSN keeps whichever arrives first; the record shows 0x81 for Stop but does not say whether a SUCCESS also arrived. Whether the motor halts on `03 03 00` is a motor-controller question that the radio's code cannot answer: `STOP-WHILE-MOVING` in the test plan does.

**[measured, twice] The motor halts on Zigbee Stop (#51, session B, 2026-10-06).** A go-to followed by Stop 3 s later halted the Office Shade; a later read returned 71, from 84. A go-to 30 from 50 followed by Stop at 0.5 s halted it, and the shade reported lift 44 at 2.5 s after the go-to (3f). So "over Zigbee the shade ignores the stop" is wrong for this unit: the motor halts, and only the reply is wrong.

**Consequence for software (#54).** Because the motor halts on a standard Stop, U reports Stop's 0x81 as SUCCESS, as it does for movements, so Home Assistant's Stop shows no error. A manufacturer-specific Stop is refused by the radio and not forwarded (FA §2), so its 0x81 still reaches the caller.

**Classification: protocol violation [spec, checked]. This is the one airtight violation**, and the firmware widens it: every Window Covering command, not only Stop, is answered UNSUP_COMMAND straight after SUCCESS (FA §3). Stop is mandatory (Table 7-45, L11663). On receipt, the device "will stop any adjusting to the physical tilt and lift that is currently occurring" (§7.4.2.2.3, L11680-11682). Status 0x81 means "The specified command is not supported on the device. Command not carried out" (Table 2-12, L3736; ZCL8 names it UNSUP_COMMAND, with UNSUP_CLUSTER_COMMAND the deprecated name). The spec reserves it for a command that "is not supported on the device" (§2.5.12.2, L3007-3009). So the shade rejects, as unsupported, a mandatory command that its own discovery says it processes. A correct device halts and replies SUCCESS.

**Why the hub cannot substitute.** A "go to where you are now" substitute was built and then removed on 2026-10-04. A stale read plus a go-to is a move command, not a stop. That reasoning is the basis for passing Stop through.

**[unmeasured]** The only record that the substitute misbehaved is the comment above the Stop branch in `command` (the retired `custom_components/smartwings/quirks/smartwings_wm25lz.py:412-420`). It says the position read taken mid-travel was stale, so the shade reversed direction instead of halting. The research record does not mention the event. DH:66-70, cited here before, is about a different defect: the command interceptor calling itself and deadlocking.

### 3e. The first frame of a command is routinely not acted on, and re-sending is what works

**[measured]** In the final verified batch of three commands (close, position, open), the first frame produced movement **zero** times. Every command needed frame 2 or frame 3 (DH:183-184, DH:376-378). Earlier, one `open_cover` did nothing on frame 1 and worked on a re-send (DH:381-382). Reads show the same pattern. Without one retry on attribute reads, Home Assistant's on-demand refresh failed on three of nine shades (the `read_attributes` docstring in the handler). Reads that do land answer in 0.8-1.9 s (DH:375).

**What "dropped" means here.** The evidence is "no movement within the verification window, then movement after a re-send". The window is 2.5 s plus 1.5 s, with one extra 1.5 s look if a read fails (constants at the top of the handler). It is **not** known whether frame 1 reached the module or was acknowledged. A late start also looks like a drop: one shade took about 100 s to begin moving after accepting a command (DH:203-205).

**[measured] The window could not see movement, so the count is confounded (#51).** A read of the position during travel returns the lift from before the move until the motor reports its position at the end of travel (3f). Every "no movement" above was judged by reads 2.5 s and 4 s after the frame, inside that blind window, on moves of 30-70 s. A shade that was travelling on frame 1 would have read as unmoved, and the re-send would then have looked like the frame that worked. So "the first frame produced movement zero times" (§4) does not show that frame 1 was ignored. That some first frames are ignored is still reported (DH:381-382 describes one open that did nothing until a re-send), but how often is unknown: `RADIO-FIRST-FRAME-FATE` must be re-measured with reads taken after the travel time, or by watching the shade. The quirk now judges a command only after its travel time and re-sends once (#51).

**Classification: depends on the unknown [open].**
1. If frame 1 is acknowledged with ZCL SUCCESS and not executed, it is a violation. A device must not report success for a command it did not carry out. **[spec, checked]** On receipt of a command, the device "SHALL attempt to parse and execute the command" (§2.3.2, L2234-2235), and SUCCESS means "Operation was successful" (Table 2-12, L3736).
2. If frame 1 never reaches the application, it is a delivery problem. For a battery device that may be how it polls its parent, which is a power-management issue rather than a ZCL violation. It is still a defect, because the device is not usable without application-level retry. **[spec, checked]** The ZCL does not cover delivery below the application layer.

**[measured]** In the discovery run every one of 61 general-command frames was answered first time (§2a item 5). Those frames came back to back, not after an idle period, so this does not decide between 1 and 2.

**[suspected]** The README in the repo explains this with a Tuya module that wakes the motor over a GPIO line. Nothing in the record supports that explanation (REV 5e). Treat it as unproven. **[firmware]** The radio has no wake line to the motor controller. It sends SUCCESS first, then writes the serial frame once, with no acknowledgement from the motor and no retry, and it polls its parent every second (FA §3, §5, §9). So a SUCCESS never shows that the motor acted, and a first frame lost after idle is more likely lost between the radio and a sleeping motor controller than on the Zigbee side **[suspected]**. `RADIO-FIRST-FRAME-FATE` can tell: SUCCESS with no movement points there.

**[reported]** The coordinator is the Home Assistant Yellow's onboard EZSP radio, driven by bellows. All nine shades are end devices with receiver-on-when-idle clear. The stored node descriptor agrees: logical type 2 (end device), MAC capability flags 0x80, with receiver-on-when-idle (0x08) clear (§2, **[measured]**). That fits item 2 of the classification above: a parent holds frames for an end device that is not listening until it polls. It does not show what happened to frame 1.

**What settles it.**
1. Log, at debug level, zigpy's response to frame 1: Default Response status or timeout.
2. Read the node descriptor: logical type, receiver-on-when-idle, MAC capability flags. Reported done (above).
3. If needed, take one sniffer capture of an idle-then-command sequence.

### 3f. Position is reported only when travel ends, and Configure Reporting is refused

**[source]** ZHA binds the cluster and configures reporting for `current_position_lift_percentage` with min 0 s, max 900 s, change 1 (zha-cover `:151-160`). A conforming device that accepted that configuration, and held a binding for the cluster to the coordinator, would report on every 1-point change and at least every 15 minutes; without a resolvable destination it generates no report (ZCL8 Table 2-4, L2689; §2.5.11.2, L2929-2930).

**[measured, superseded]** Before #51 no position report had been observed from any of the nine. The record says, "These motors never push updates" (DH:197, DH:233-235). That is wrong: see the next paragraph. The cached position stays at whatever was last read or reported. After a restart, Home Assistant shows the remembered value until something reads again or the shade reports (DH:194-198, DH:261-263, DH:383-384).

**[measured] The shade reports its position when travel ends, and only then (#51, session B, 2026-10-06, Office Shade).**
1. Reports arrive at the end of travel. A go-to 30 from 50, stopped at 0.5 s: a Report Attributes for 0x0102/0x0008 with lift 44 arrived 2.5 s after the go-to. A go-to 30 from 44: a report with lift 30 arrived 6.2 s after it. ZHA took the report as any attribute report: the cover entity showed 56 (100 − 44) within about 4 s of it. Battery (0x0001/0x0021) was reported too, 82 during travel and 84 after.
2. Reads during travel return the lift from before the move. A go-to 50 from lift 0 (20:26:21.8Z): reads of 0x0008 at 0.5, 3.4, 5.4, 7.4, 9.4, 11.5, 13.3 and 15.3 s all returned 0; from 18.3 s on they returned 50, with no value in between. Raw `up_open` from lift 71: reads about 5 s and 7 s in returned 71; after the shade reached the top a read returned 0. In the 44 → 30 move, a read 3.8 s in returned 44; by 8.8 s, 30.
3. A duplicate go-to, the same target twice 2.5 s apart, moved the shade once to the target; each frame drew SUCCESS then 0x81.

This fits the firmware (next paragraph): the motor controller sends its position when it stops (at its target, where it stalls, or on Stop), and the radio both stores it for reads and pushes it. Nothing showed a position sent during travel.

**[measured]** The shade advertises 0x0008 as reportable: access control 0x05 in Discover Attributes Extended (§2a item 2; DISC frame 31).

**[firmware] What the radio does (FA §4).** It has no reporting engine. Configure Reporting and Read Reporting Configuration are both answered with Default Response 0x81 (UNSUP_COMMAND), so ZHA's configuration at pairing was refused and no configuration exists to read back. Bindings play no part. Separately, every time the motor controller sends the radio a new position, the radio writes 0x0008 and unicasts its own Report Attributes for it straight to the coordinator (node 0x0000, endpoint 1); the same happens for battery. A read of 0x0008 returns the last position the motor sent; the radio never asks the motor for one.

**Classification: violation [spec, firmware].** Bit 0x08 in `config_status` is clear, so the device declares itself open-loop, and for an open-loop device the spec does not require the position attribute at all (Table 7-40 note, L11566-11570; §7.4.2.1.2.8, L11603-11607). But this device implements it and advertises it as reportable, and then "This cluster SHALL support attribute reporting ... The following attributes SHALL be reported: Current Position - Lift Percentage" (§7.4.2.5, L11755-11760). Refusing Configure Reporting for that attribute as an unsupported command breaches §7.4.2.5. The binding question that this section used to turn on (Table 2-4, L2689; §2.5.11.2, L2929-2930) does not arise: no configuration is ever accepted, and the radio's own pushes ignore bindings.

**Settled: why no push had been seen.** The motor sends its position once, at the end of travel, and the radio pushes it then (#51). Earlier sessions did not log unsolicited frames, so the pushes were not looked for. Whether a move made with the remote is reported the same way has not been checked.

### 3g. Two coordinate spaces: a hazard for software, not a device defect

ZCL lift is 0 = open, 100 = closed. Home Assistant cover position is 0 = closed, 100 = open. ZHA converts with `100 - lift` in both directions (zha-cover `:346-347`, `:754`) **[source]**.

**[measured]** The motors follow ZCL. A shade held fully up by its remote reads 0. `set_cover_position(90)` reads back 10, and `set_cover_position(100)` reads back 0. A go-to of lift 38 drove a shade visibly downward (DH:248-253, DH:270-275, DH:176-179). One reading contradicts this: a shade "reported as UP read 100". It is unexplained and may have been a cached value (DH:186-192) **[open]**.

Note on DH:379-380. That passage lists "`close` → motor 0 / HA 0 … Motor and HA agree in every case" as a verified end state "after the axis fix". It is the superseded misreading that the motor reports percent open. Plain ZCL gives lift 100 at HA position 0, so the two cannot agree. The same record retracts that reading at DH:270-275, and the measurements above contradict it. Do not cite DH:379-380 for the axis.

**This is not a violation [spec, checked].** CurrentPositionLiftPercentage is the position "from the up/open position" (§7.4.2.1.2.8, L11603-11605), so 0 = open is the spec's axis. One oddity sits in the spec itself: its open-loop rule for Go to Lift Percentage treats "a zero percentage" as Down/Close (L11701-11702), the opposite sense. The motors do not apply that rule (3a). The axis became the most expensive source of bugs in our code. One example: a stop stored in Home Assistant space and used directly as a lift sends the shade the opposite way (DH:61-65, DH:111-117). Every value that crosses the boundary has to name its space.

### 3h. A shade that answers reads but ignores repeated identical moves

**[measured, once]** "Right master blackout" kept reporting its position. It ignored `open_cover`, a device re-initialise, and repeated raw up frames. A small move in the opposite direction freed it, and the next command then took about 100 s to start (DH:200-208). The remote freed a similar earlier case on the office shade. **Unexplained.** It is recorded as an observation, not a protocol claim. The spec does not cover it, beyond the general rule that a device "SHALL attempt to parse and execute" each command (§2.3.2, L2234-2235).

## 4. Measured timings

| Quantity | Value | Evidence | Sample |
|---|---|---|---|
| Live attribute read, when answered | 0.8-1.9 s | DH:375 | nine shades, several sessions |
| Full travel | 30-70 s | ARCH:28-30 | not recorded per shade |
| Absolute go-to from mid-travel (about 45-60) to the top | ≤15 s | DH:218-222 | one shade |
| Delay before a stuck shade started moving | about 100 s | DH:203-205 | one event |
| First frame produced movement | 0 of 3 in the final batch; "every command in the verified batches needed frame 2 or 3". **Confounded**: judged by reads 2.5-4 s after the frame, which return the pre-move lift during travel (3e) | DH:183-184, DH:376-378 | small batches; no per-frame table survives in the record |
| Read of 0x0008 during travel | Returns the lift from before the move until travel ends: 0 at every read for 15.3 s of a go-to 0 → 50, then 50 from 18.3 s; 71 at about 5 s and 7 s of a raw `up_open` from 71; 44 at 3.8 s of a go-to 44 → 30, 30 by 8.8 s | #51 | one shade, three moves |
| Report of 0x0008 after travel ends | 2.5 s after a go-to 50 → 30 that was stopped at 0.5 s (value 44); 6.2 s after a go-to 44 → 30 (value 30); ZHA's cover updated within about 4 s of the report | #51 | one shade, two moves |

The test harness that produced these is `~/.hermes/profiles/ha/cache/scratch/sw_verify2.py` (DH:360-371). The record says its results went to `sw_verify2_results.csv` (DH:365). **[reported]** That file no longer exists. The surviving raw evidence is about 150 CSV files in `/config` on the box. Any number given to the vendor should come from those files, not from this summary.

**Consequence in ZHA [source].** ZHA does not know travel time. After a command it shows "opening"/"closing" for up to 300 s × the fraction of travel requested (`LIFT_MOVEMENT_TIMEOUT_RANGE = 300`, zha-cover `:64`, used at `:516-521`) unless a position update arrives first. The shade's report at the end of travel is such an update (3f, #51).

## 5. Summary: violations versus oddities

The class column follows the spec check in §9.

| # | Behaviour | Class | Confidence |
|---|---|---|---|
| 3a | Limits set with the remote are enforced over Zigbee too, with lift 100 at the lower limit; yet 0x0011 reports 65535 and open loop is declared | Inconsistent, not a violation: the device holds and enforces limits it reports as unset. (Until #54 the record said Zigbee ignored them.) | Measured on two shades (#54) |
| 3b | Run-to-limit stalls short on one unit | Violation if it reproduces | One unit |
| 3c | Up/Open and Down/Close possibly reversed, undeclared | Not reversed | Down/Close lowers (measured, indirect); Up/Open raised the one unit tried (#51) |
| 3d | Stop answered with 0x81 (UNSUP_COMMAND), though discovery lists Stop | **Violation, airtight.** Every Window Covering command gets SUCCESS then 0x81 (firmware) | Measured; Stop advertised in discovery (§2a); cause read in the firmware (FA §3). The radio forwards Stop to the motor, and the motor halted on it twice (#51) |
| 3e | First frame not acted on | Violation if ACKed then ignored; otherwise a delivery defect | Effect reported, but the count was judged by reads that cannot see travel, so it is confounded (#51); mechanism open. The radio always answers SUCCESS before it writes the serial frame, once and unacknowledged (FA §3) |
| 3f | Position reported only at the end of travel; reads during travel return the old lift | **Violation**: Configure Reporting is refused with 0x81 (firmware) | Measured (#51); refusal and push path read in the firmware (FA §4) |
| 3g | ZCL and HA position axes are opposite | Not a defect; both conventions are correct | Measured, one stray read |
| 3h | Ignores repeated identical moves until nudged | Unexplained; not covered by the spec | One shade |
| §2 | `window_covering_mode` (0x0017) reads 0x14 | Bit 2: the value indicates maintenance mode (Table 7-44), yet the shade accepts network movement. The spec is ambiguous, because its default sets that bit. Reserved bit 4 set: a separate, minor violation. | Reported on all nine (test 8d); 20 cached on the Office Shade (§2a) |
| §2a | Identify, Groups and Scenes list no received commands | **Violation**: the mandatory commands are missing (firmware) | Discovery on one shade; no handlers in the firmware (FA §2) |

## 6. What a correct device would do

A conforming WM25/L-Z would do items 2, 3 and 5. Item 4 applies only if the swap turns out to be needed. Item 1 is what we ask for, but the spec does not require it of a device that declares open loop (3a, §9).

1. Declare closed-loop lift (`config_status` bit 0x08) and report the remote-set limits in `installed_open_limit_lift` and `installed_closed_limit_lift`. It already stops at them on `down_close` and at 100 % (3a, #54).
2. Halt on Stop and reply SUCCESS.
3. Execute the first frame it acknowledges.
4. Move Up/Open upward, or else set `config_status` bit 0x04.
5. Honour a Configure Reporting request for 0x0008 and report position during and at the end of travel.

With those five, the stock ZHA cover entity would work with no device handler at all. The doubled battery percentage (`DoublingPowerConfigurationCluster` in UPQ `:101`) is a separate, already-handled quirk and is out of scope here.

## 7. What we cannot do from the hub, and why

**7a. Set the limits.** The motor honours the limits set with its remote (3a, #54), but no standard command sets an installed limit, and both limit attributes are read-only (zigpy `:779-784`; ZCL8 Table 7-43). `window_covering_mode` is writable and has a "run in calibration mode" bit (`:729-733`, `:798-800`; ZCL8 Table 7-44, bit 1). Discovery confirms that 0x0017 is the only writable Window Covering attribute and that no manufacturer-specific attribute is advertised (§2a). **[firmware]** It does nothing: the radio stores a Mode write in RAM, never reads it and sends nothing to the motor (FA §8). So the calibration bit can neither start a calibration nor set a limit, and no other path from the hub to the limit exists in the radio.

**7b. Read the limits.** The module reports 65535. Where a shade stops is known only to its motor and the person who programmed its remote.

**7c. Read Stop's reply as a result.** Stop may be answered 0x81 (3d), though the radio forwards it to the motor and the motor halted on it in both tests (#51), so the reply says nothing; U reports a standard Stop's 0x81 as SUCCESS (#54). A go-to built from a stale read is a move command, not a stop.

**7d. Learn the position during travel.** The shade pushes its position only when travel ends, and a read during travel returns the lift from before the move (3f, #51). So nothing from the hub shows where a travelling shade is, or whether it has started; only the end of travel does.

**7e. Know whether a command was executed, except by the position once travel should be over.** The reply to a command does not tell us that it moved (3e), and neither does a read during travel (3f).

**7f. Stop exactly at a stop of the hub's own.** Until #54 the hub kept its own closed limit and sent a percentage go-to short of it, only as accurate as the motor's position estimate. Since the motor enforces its remote-set limits (3a), the hub keeps none.

**7g. Fix the firmware.** The device does have an OTA client cluster (output cluster 0x0019 in the signature, UPQ `:73`, `:89`). So a corrected firmware image, if SmartWings publishes one, could be delivered over Zigbee through ZHA's normal OTA path without removing any shade.

## 8. Tests that would close the open items

The 2026-10-06 discovery run (§2a) and spec check (§9) resolve 8d. They sharpen 8c without running it. No item here asked for the discovery run itself (#36).

**8a. Direction of the raw run-to-limit commands (3c).** Send one raw `up_open` and one raw `down_close` from mid-travel and watch the direction. **Not run as specified.** The owner closed #4 because the indirect evidence in 3c (the box's v18 quirk sends raw `down_close`, 0x01, with no closed limit in force, and closes work) settles what the code depends on: a close with no stop is sent as `down_close` (#34). No air capture or per-shade physical trial was recorded. Raw `up_open` raised the Office Shade (#51, 3c), and since #54 opens are sent as raw `up_open`.

**8b. Fate of the first frame (3e).** Log zigpy's response to frame 1 at debug level and read the node descriptor. **Partly done [reported]:** the node descriptor shows end devices with receiver-on-when-idle clear (3e). The frame-1 response has not been logged. **Reopened (#51):** the earlier count was judged by reads during travel, which cannot see movement; re-measure with reads after the travel time, the end-of-travel report, or by watching.

**8c. Reporting configuration (3f).** Send Read Reporting Configuration for 0x0102/0x0008. **Answered by the firmware (FA §4):** it will be refused with 0x81, and bindings do not matter. Why the radio's own pushes had not been seen is settled: the shade pushes its position at the end of travel, and earlier sessions did not look (3f, #51). The rest of this item is superseded: **still needed**, together with a read of the shade's binding table (ZDO Mgmt_Bind_req, cluster 0x0033) to look for a 0x0102 binding to the coordinator. Discovery shows that 0x0008 is advertised as reportable (§2a). The spec check (§9, 9n) makes 3f a violation only if the configuration was accepted, the binding exists and no reports arrive. These two reads separate those cases.

**8d. The `mode` reading (§2).** Re-read attribute 0x0017 explicitly. **Done [reported]:** 20 on all nine (`/config/q_*_23.csv` on the box). **Resolved by the spec check (§2, §9):** bit 2 (0x04) matches the spec's default, which conflicts with the spec's own description of that bit, and bit 4 (0x10) is reserved, so setting it is a minor violation. Only what bit 4 does on this firmware is still open, and nothing depends on it.

**8e. Repeatability of the run-to-limit stall (3b).** Ten `up_open` runs on Right master blackout and on one sibling, counted. Deferred while every open was a go-to; revived by #54, which sends opens as `up_open` (test plan `REPEAT-DOWN-CLOSE-STALL`).

**8f. Per-shade travel times (§4).** Record full-travel times per shade from the surviving CSV files in `/config` (§4), if they hold them, or from new timed runs.

## 9. Spec check against ZCL revision 8

Each **[spec]** claim in this part was checked against the ZCL8 text on 2026-10-06. The table also covers the discovery findings in §2a. "Claim" says whether Part 1's paraphrase matched the text; "Verdict" is the device's standing under the text. Line numbers are the PDF's own (L…).

| # | Part 1 claim | ZCL8 reference | Claim | Verdict on the device |
|---|---|---|---|---|
| 9a | Up/Open, Down/Close and Stop are mandatory and move to the open limit, move to the closed limit, and stop (§1a) | Table 7-45 (L11663); §7.4.2.2.1-3 (L11667-11682) | Confirmed | See 9i, 9j, 9l |
| 9b | Go to Lift Value is optional and uses the limits' units (§1a) | Table 7-45; §7.4.2.2.4 (L11687-11691) | Confirmed; the units are cm | Not used by U; not tested |
| 9c | Go to Lift Percentage is "optional (required for closed-loop lift devices)" (§1a) | Table 7-45; §7.4.2.2.5 (L11696-11705) | **Corrected.** Every device must support it or Go to Tilt Percentage (L11704-11705). A lift-only device SHOULD reject Go to Tilt Percentage (L11726-11727), so for a lift-only shade Go to Lift Percentage is the one that satisfies that rule. An open-loop device SHOULD treat 0 % as close and anything else as open. | Supported and advertised: **not a violation**. Proportional execution while declaring open loop: **inconsistent but not a violation** (a SHOULD) |
| 9d | 0 % is the open limit and 100 % the closed limit (§1a, 3g) | §7.4.2.1.2.8 (L11603-11605) | Confirmed. The open-loop sentence at L11701-11702 runs the other way, an oddity in the spec. | **Not a violation** (3g) |
| 9e | 0x0011 default is 0xFFFF; "check the spec's default column" (§1b) | Table 7-43 (L11616); §7.4.2.1.3.2 (L11628-11630) | Confirmed | 65535 is the default, and the attribute is ignored in open loop: **not a violation** (§2) |
| 9f | `config_status` = 3 declares open-loop lift (§1b, §2) | Table 7-42 (L11601) | Confirmed | The declaration is valid. It is at odds with the device's proportional positioning and its position attribute: **inconsistent but not a violation** |
| 9g | `mode` bits; 0x14 "unexplained" (§1b, §2) | Tables 7-43 (default 0000 0100) and 7-44; §1.6.2 (L2113-2117); §2.3.1 (L2229-2231) | **Updated.** Bit 2 is set in the spec's default. Bit 4 is undefined, so reserved. | Bit 2: **spec ambiguous**. Table 7-43's default sets the bit, while Table 7-44 says it blocks movement over the network, and the shade moves over the network with it set. Bit 4 set: **violation, minor** (reserved bitmap bits SHALL be sent as zero) |
| 9h | Limits are read-only and set by a means the spec leaves to the manufacturer (§1c, 7a) | Table 7-43 (Acc R); Table 7-44 bit 1 | Confirmed. **Corrected** that the guarantees in §1c hold only for closed-loop devices (Table 7-40 and 7-43 notes, L11566-11570, L11618-11622). | **Not covered by the spec**: no command or writable attribute sets a limit |
| 9i | 3a: closed limit not honoured, "protocol violation" | §7.4.2.2.2 (L11673-11676); §7.4.2.2.5 (L11697-11699); §7.4.2.1.3.2 (L11628-11630); Table 7-44 bit 1 | **Downgraded** | **Inconsistent but not a violation**: arguable, not airtight, because of the declared open loop. The behaviour checked here was reversed by #54: Zigbee commands do stop at the remote-set limits (3a) |
| 9j | 3b: run-to-limit stalls short, "violation if it reproduces" | §7.4.2.2.1 (L11667-11669) | Confirmed | **Violation if it reproduces** (8e) |
| 9k | 3c: an undeclared reversal would be a violation | Table 7-42 bit 2; Table 7-44 bit 0 | Confirmed | Down/Close lowers: **not a violation**. Up/Open: unobserved, open |
| 9l | 3d: Stop rejected, "protocol violation" | Table 7-45 (Stop M); §7.4.2.2.3 (L11680-11682); §2.5.12.2 (L3007-3009); Table 2-12, 0x81 (L3736); §2.5.18.2 (L3302-3303) | Confirmed. 0x81 is UNSUP_COMMAND in ZCL8; UNSUP_CLUSTER_COMMAND is the deprecated name. | **Violation**, the one airtight one: mandatory, advertised in discovery, rejected as unsupported. The firmware shows the 0x81 follows a SUCCESS for every Window Covering command (FA §3) |
| 9m | 3e: SUCCESS without execution would be a violation | §2.3.2 (L2234-2235); Table 2-12, SUCCESS | Confirmed | **Open**: a violation if SUCCESS was sent; delivery below the ZCL is **not covered by the spec** |
| 9n | 3f: "a violation only if reporting was accepted" | §7.4.2.5 (L11755-11760); Table 2-4 (L2689); §2.5.11.2 (L2929-2930); §2.5.7.3 (L2743-2746, L2749-2754, L2770-2772); §2.5.11.2.1 (L2931-2934); Table 7-40 note | **Revised.** 0x0008 is a mandatory reportable attribute once implemented, so rejecting it as UNREPORTABLE_ATTRIBUTE would itself breach §2.5.7.3. But reports go only to bound destinations (Table 2-4, L2689; §2.5.11.2, L2929-2930). | **Violation [firmware]**: Configure Reporting is refused with 0x81 for an attribute §7.4.2.5 says SHALL be reported (FA §4). Why the radio's own pushes have not been seen is open |
| 9o | 3g: opposite axes are not a defect | §7.4.2.1.2.8 (L11603-11605) | Confirmed | **Not a violation** |
| 9p | 3h: ignores repeated identical moves | §2.3.2 (L2234-2235) only | — | **Not covered by the spec** |
| 9q | §2: attribute 0x000E unsupported is not a defect | Tables 7-40 and 7-43 | Confirmed: there is no 0x000E | **Not a violation** |
| 9r | §2a: no manufacturer extensions advertised | §2.5.19.1.1 (L3316-3323) | — | **Not a violation**: the finding is "none advertised", not "none exist". The hiding clause covers only the 0xFFFF wildcard in Discover Commands Received; the run used 0x1002, and the spec defines no hiding for attribute or generated-command discovery. |
| 9s | §2a: tilt commands 0x07 and 0x08 advertised on a lift-only roller shade | Table 7-41 (type 0x00: Lift); §7.4.2.2.7 (L11726-11727) | — | **Inconsistent but not a violation** (a SHOULD; not sent) |
| 9t | §2a: Identify, Groups and Scenes list no received commands | Tables 3-32 (L4237), 3-37 (L4366), 3-42 (L4622); §2.5.18.3 (L3305-3308) | — | **Violation [firmware]**: the mandatory commands are missing; no handlers exist (FA §2) |
| 9u | §2a: unadvertised clusters 0xFC01 and 0xEF00 answered discovery with empty lists | §2.5.12.2 (L3011-3012) speaks of a "cluster command" to an absent cluster | — | **Not clearly covered by the spec** |
