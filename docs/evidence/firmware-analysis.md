# Radio firmware analysis: SmartWings WM25/L-Z Zigbee module

Written 2026-10-06, from a full flash dump of one WM25/L-Z radio module. It is offline analysis only: nothing was sent to a shade. What the shades were then measured doing is in [device-behavior.md](../device-behavior.md).

## 0. Provenance, method and ground rules

**The image.** Obtained on 2026-10-06 from a community member in a [zigpy discussion](https://github.com/zigpy/zigpy/discussions/1184). It came as two files with the same content:

| File | SHA-256 |
|---|---|
| `fw.hex` (Intel HEX) | `d90ea2d9d97e3a950e54a82254ecda62852a061988be50b46cff8fa3cdbad598` |
| `fw.s37` (Motorola S-record) | `fc60e21228826d5cfb86a9caa2c6661ad7fcbebccc325fd4d125a8c018c8dadd` |

Both decode to the same 768 KiB flat image covering 0x00000-0xBFFFF (checked byte for byte). It is a dump of the whole flash, not an OTA file, so there is no container to unwrap. The image is **not** in this repository and is not redistributed. It is someone else's unit, so the NVM areas may hold that donor's network key, link keys and EUI64. None of those were printed or recorded, and none appear here.

**Is it our firmware?** The application reports manufacturer code 0x1002, image type 0x0000 and file version 2 in its OTA client (section 7), the Basic strings "Smartwings" and "WM25/L-Z" (section 2), and the same eight clusters on endpoint 1 that discovery found on one of our shades (section 2). That shade's own OTA query carried manufacturer 0x1002, image type 0 and file version 2 (`unmatched_frames` in [discovery-office-shade.json](discovery-office-shade.json), raw `01 09 01 00 02 10 00 00 02 00 00 00`). So this is the application our shades run, as far as anything on the air can tell. A different build with the same version number cannot be ruled out.

**Tools.** Ghidra 12.1.4 headless (language `ARM:LE:32:Cortex`, raw binary at base 0, vector entries disassembled as Thumb), its decompiler for every function, Capstone 5 for exact instruction listings, and short Python scripts for the tables and for branch cross-references. No SDK symbols were available; function roles are inferred from what each does, and the inference is stated where it matters.

**Evidence tags.**

| Tag | Meaning |
|---|---|
| **[source: firmware]** | Read in the image's code or data; the flash address is cited. Addresses are flash offsets (the image is linked at 0, so they are also the Cortex-M addresses). Excerpts are a few bytes or instructions at most. |
| **[inferred]** | A reading of the code that depends on recognising an SDK function or convention by its behaviour, not by a symbol. The basis is given. |

Confidence is given per answer: **high** (read directly in code or data, one interpretation), **medium** (depends on an inference about an SDK convention), **low** (plausible, not shown).

## 1. Chip, layout and versions

**Answer.** A Silicon Labs **EFR32MG21** (Series 2, Cortex-M33, 768 KiB flash), not the EFR32MG1 reported in the zigpy discussion. A Gecko Bootloader at 0x0000, an unsigned EmberZNet 6.9.1 application (Gecko SDK suite 3.1) at 0x4000, application version 2. **Confidence: high** for Series 2 / xG21 and the layout; medium for the exact part number.

Evidence **[source: firmware]**:

1. **Series 2, xG21.** The fault handler's interrupt-name table (strings from 0x2DD14) lists `SETAMPERHOST_IRQn`, `SEMBRX_IRQn`, `SEMBTX_IRQn`, `SMU_SECURE_IRQn`, `SMU_PRIVILEGED_IRQn`, … `M33CTI0_IRQn`, `M33CTI1_IRQn`. The Secure Element mailbox, the SMU and the Cortex-M33 cross-trigger exist only on Series 2, and this set is the xG21's. The peripheral bases agree: GPIO at 0x4003C000 and the USART at 0x40058000 (literals at 0x445C, 0x45B8). The HAL path `platform/base/hal/micro/cortexm3/efm32/` in the assert strings is the SDK's directory name for every Cortex-M part; it does not mean a Cortex-M3.
2. **768 KiB flash, 8 KiB pages.** The image ends at 0xBFFFF, the bootloader's configuration holds 0x2000 and 0xC0000 (0x2770-0x2774), and NVM3 pages sit on 8 KiB boundaries. A Zigbee xG21 with 768 KiB is an EFR32MG21x…F768. The project name `oem_si32_zg_uart_connect_ty_zs3l` names Tuya's ZS3L module, which is built on that part **[inferred]**; whether it is the A010 or A020 RF-power grade cannot be read from code.
3. **Layout.**

   | Range | Contents |
   |---|---|
   | 0x00000-0x027FF | Gecko Bootloader. Application-properties block at 0x26C4: type 0x40 (bootloader), version word 0x010C0000 (1.12.0). |
   | 0x04000-0x3147B | The application. Address table at 0x4000 (initial SP 0x20001780, reset 0x2ADCD, vector table pointer 0x4200). Application-properties block at 0x2E5EC (pointer at 0x4034). |
   | 0x32000-0x3C9A0 | **Stale.** The tail of an older, larger image left behind in flash. It has its own application-properties block at 0x3AA14 with application version **1** and an ECDSA-P256 signature at 0x3C960, and it holds Tuya's generic project strings (`oem_si32_zg_uart_connect_ty_zs3l` at 0x39744, a JSON config with `wake_gpio_mcu_pin`, `firmName` at 0x39918-0x399A5). Nothing in the current application refers to it. |
   | 0x5A000-0x61FFF | The application's NVM3 (4 pages, 32 KiB). The NVM3 init block in the `.data` image (flash 0x31174, copied to RAM 0x20001AD0) gives base 0x5A000, size 0x8000, 200 cache entries, 254-byte maximum object. The address table repeats 0x5A000/0x62000 at 0x4054-0x405C. |
   | 0xB6000-0xBFFFF | A second NVM3 area that the current application does not use. It holds `_TZE200_nab7bqzv` (0xB85A3) and `_TZE200_uhizbsm0` (0xB86A7): leftovers of the earlier Tuya firmware. These are where the discussion's "_TZE200 in NVM" came from. |

4. **Versions.** The current application's properties block (0x2E5EC) has struct version 0x0101, signature type 0 (**unsigned**), application type 1 (Zigbee) and application version **2** at 0x2E60C. The EmberZNet version record at 0x30C84 reads `d6 00 06 09 01 00 aa`: build 214, version 6.9.1.0, GA. That matches the `gecko_sdk_suite/v3.1` paths in the assert strings (for example at 0x2E8AC, `…/app/framework/util/af-main-soc.c`).
5. **Container.** A raw flash dump: no OTA header (the only 0x0BEEF11E at 0x2E748 is the OTA client's own constant), no GBL container, no encryption. The bootloader can verify signed images (the stale v1 image carried a signature); the current v2 application carries none.

**What this changes.** The "EFR32MG1" reported in the zigpy discussion is wrong for this image; the memory map to load is the xG21's.

## 2. The Application Framework tables

**Answer.** One endpoint, eight clusters, 32 attributes, 23 generated-command entries. **No** manufacturer-specific attribute, command or cluster exists in the tables. Discovery on a real shade showed exactly what the tables hold. **Confidence: high.**

**Endpoint [source: firmware].** The endpoint set-up at 0xD3F0 writes one endpoint: number 1, profile 0x0104, device 0x0202 (Window Covering), device version 1, endpoint type at 0x2EC2C. That type is `{clusters 0x2EAE0, 8 clusters, 46 bytes of attribute storage}`.

**Clusters** (table at 0x2EAE0, 20 bytes per entry `{id, attributes, count, size, mask, functions}`). Mask bits follow the SDK's convention **[inferred]**: 0x40 server, 0x80 client, 0x01 init function, 0x04 default-response function.

| Entry | Cluster | Side | Attributes | Mask | Per-cluster callbacks |
|---|---|---|---|---|---|
| 0x2EAE0 | 0x0000 Basic | server | 5 | 0x40 | none |
| 0x2EAF4 | 0x0001 Power Configuration | server | 3 | 0x40 | none |
| 0x2EB08 | 0x0003 Identify | client | 1 | 0x80 | none |
| 0x2EB1C | 0x0003 Identify | server | 2 | 0x40 | none |
| 0x2EB30 | 0x0004 Groups | server | 2 | 0x40 | none |
| 0x2EB44 | 0x0005 Scenes | server | 6 | 0x40 | none |
| 0x2EB58 | 0x0019 OTA Upgrade | client | 4 | 0x85 | init, default-response (0x2E958) |
| 0x2EB6C | 0x0102 Window Covering | server | 9 | 0x40 | **none** |

The Window Covering entry is `02 01 00 00 74 ea 02 00 09 00 0e 00 40 00 00 00 00 00 00 00`: no function table, so no attribute-changed callback exists for the cluster.

**Attributes** (table at 0x2E960, 12 bytes per entry `{id, type, size, mask, default}`). Mask bits **[inferred]** from the SDK convention: 0x01 writable, 0x02 kept in NVM, 0x04 min/max, 0x08 manufacturer-specific, 0x10 external storage, 0x20 singleton, 0x40 client. No entry has 0x02, 0x08 or 0x10 set.

| Cluster | ID | Type | Size | Mask | Default |
|---|---|---|---|---|---|
| 0x0000 | 0x0000 ZCLVersion | uint8 | 1 | 0x20 | 8 |
| 0x0000 | 0x0004 ManufacturerName | string | 33 | 0x20 | "Smartwings" (0x2EBDC) |
| 0x0000 | 0x0005 ModelIdentifier | string | 33 | 0x20 | "WM25/L-Z" (0x2EBFD) |
| 0x0000 | 0x0007 PowerSource | enum8 | 1 | 0x20 | 0 (unknown) |
| 0x0000 | 0xFFFD ClusterRevision | uint16 | 2 | 0x20 | 3 |
| 0x0001 | 0x0020 BatteryVoltage | uint8 | 1 | 0x20 | 0 |
| 0x0001 | 0x0021 BatteryPercentageRemaining | uint8 | 1 | 0x20 | 0 |
| 0x0001 | 0xFFFD | uint16 | 2 | 0x20 | 2 |
| 0x0003 client | 0xFFFD | uint16 | 2 | 0x40 | 2 |
| 0x0003 | 0x0000 IdentifyTime | uint16 | 2 | 0x01 (writable) | 0 |
| 0x0003 | 0xFFFD | uint16 | 2 | 0x00 | 2 |
| 0x0004 | 0x0000 NameSupport | map8 | 1 | 0x00 | 0 |
| 0x0004 | 0xFFFD | uint16 | 2 | 0x00 | 3 |
| 0x0005 | 0x0000 SceneCount | uint8 | 1 | 0x00 | 0 |
| 0x0005 | 0x0001 CurrentScene | uint8 | 1 | 0x00 | 0 |
| 0x0005 | 0x0002 CurrentGroup | uint16 | 2 | 0x00 | 0 |
| 0x0005 | 0x0003 SceneValid | bool | 1 | 0x00 | 0 |
| 0x0005 | 0x0004 NameSupport | map8 | 1 | 0x00 | 0 |
| 0x0005 | 0xFFFD | uint16 | 2 | 0x00 | 3 |
| 0x0019 client | 0x0000 UpgradeServerID | EUI64 | 8 | 0x40 | all 0xFF |
| 0x0019 client | 0x0001 FileOffset | uint32 | 4 | 0x40 | 0xFFFFFFFF |
| 0x0019 client | 0x0006 ImageUpgradeStatus | enum8 | 1 | 0x40 | 0 |
| 0x0019 client | 0xFFFD | uint16 | 2 | 0x40 | 4 |
| 0x0102 | 0x0000 WindowCoveringType | enum8 | 1 | 0x00 | 0 (rollershade) |
| 0x0102 | 0x0007 ConfigStatus | map8 | 1 | 0x00 | **0x03** |
| 0x0102 | 0x0008 CurrentPositionLiftPercentage | uint8 | 1 | 0x00 | 0xFF |
| 0x0102 | 0x0010 InstalledOpenLimitLift | uint16 | 2 | 0x00 | 0 |
| 0x0102 | 0x0011 InstalledClosedLimitLift | uint16 | 2 | 0x00 | 0xFFFF |
| 0x0102 | 0x0012 InstalledOpenLimitTilt | uint16 | 2 | 0x00 | 0 |
| 0x0102 | 0x0013 InstalledClosedLimitTilt | uint16 | 2 | 0x00 | 0xFFFF |
| 0x0102 | 0x0017 Mode | map8 | 1 | **0x01** (writable) | **0x14** |
| 0x0102 | 0xFFFD | uint16 | 2 | 0x00 | 3 |

The Mode entry is `17 00 18 01 01 00 00 00 14 00 00 00` (0x2EAC8). So 0x14, the value every shade reads, is simply the compiled default, and bit 4 comes from the build, not from the motor.

**Generated-command table** (0x2EB80, 4 bytes per entry `{cluster, command, mask}`). The mask meanings were fixed by matching the table against the discovery replies: 0x01 sent by a client, 0x02 sent by a server, 0x08 received by a server. No entry has a manufacturer-specific bit, and no manufacturer-code table follows.

| Cluster | Commands | Mask | Meaning |
|---|---|---|---|
| 0x0003 | 0x00, 0x01 | 0x01 | Identify client sends Identify, Identify Query |
| 0x0003 | 0x00 | 0x02 | Identify server sends Identify Query Response |
| 0x0004 | 0x00-0x03 | 0x02 | Groups server sends the four responses |
| 0x0005 | 0x00-0x04, 0x06 | 0x02 | Scenes server sends the six responses |
| 0x0019 | 0x01, 0x03, 0x06 | 0x01 | OTA client sends Query Next Image, Image Block, Upgrade End |
| 0x0102 | 0x00, 0x01, 0x02, 0x04, 0x05, 0x07, 0x08 | 0x08 | Window Covering server receives these |

The bytes for the last row are `02 01 00 08 02 01 01 08 02 01 02 08 02 01 04 08 02 01 05 08 02 01 07 08 02 01 08 08`.

**Groups, Scenes and Identify have table entries but no command handlers.** The cluster-specific dispatcher (section 3) returns 0x81 for every server command on clusters 0x0003-0x0005 without calling anything (0x4C2C-0x4C38). So Get Group Membership, Add Group, View Scene, Identify and the rest are all refused with Default Response 0x81, and the shade can never join a group. The empty received-command lists that discovery returns for these clusters are accurate: the mandatory commands are missing. It confirms the zigpy discussion's "no group or scene support".

**Hidden extensions.** None. There is no attribute with the manufacturer-specific bit, no generated command with it, and no cluster in the 0xFC00-0xFFFF range. The command dispatcher refuses every manufacturer-specific Window Covering frame with 0x81 before looking at the command ID (0x4B5E: `ldrb r3,[r0,#0xf]; cbnz r3 → 0x81`). Wildcard discovery or a manufacturer-specific Stop can only confirm this.

## 3. Window Covering commands and why Stop draws 0x81

**Answer.** Every one of the seven advertised commands is handled: each builds a serial message and writes it to the motor controller. Stop (0x02) sends the serial stop `03 03 00`. Stop is **not** explicitly rejected and has its own case. The 0x81 comes from a bug shared by all seven handlers: each sends its own Default Response SUCCESS first, then returns "not handled", so the framework sends a **second** Default Response, UNSUP_COMMAND (0x81), with the same sequence number. That holds when the Disable Default Response bit is clear, as ZHA sends these commands; with the bit set the SUCCESS is suppressed and only the 0x81 goes out (note 5 below). **Confidence: high** for the code; medium for which of the two replies a hub ends up keeping.

**The path [source: firmware].**

1. The ZCL dispatcher at 0xEC48 sends each cluster-specific frame to 0x4BEA (`bl #0x4bea` at 0xE270). If that returns a non-zero status, it calls the Default Response sender with that status (0xEF7A, reached from 0xE262). The pre-command callback that could intercept a frame first is a stub that returns 0 (0x4CEC: `movs r0,#0; bx lr`).
2. 0x4BEA checks the cluster and tail-calls the Window Covering parser at 0x4B5C (`b.w #0x4b5c` at 0x4C48).
3. 0x4B5C refuses manufacturer-specific frames (0x81), then switches on the command ID with a `tbb` table (0x4B68, offsets `05 0b 0e 09 11 1c 09 26 31` for IDs 0-8). IDs 3 and 6 go straight to 0x81. Each other ID calls a handler. Afterwards:

   ```
   004b7a: cmp r0, #0
   004b7c: bne #0x4be6      ; handler returned true  -> status 0 (SUCCESS)
   004b7e: movs r0, #0x81   ; handler returned false -> UNSUP_COMMAND
   ```

4. Every handler starts by calling 0xEF74 with r0 = 0, which builds and sends a Default Response with status SUCCESS for the current command **[inferred]**: it writes frame control, sequence number, command 0x0B, the command ID and the status into the response buffer and sends it (decompiled at 0xEF74). It then writes the serial frame and returns 0, for example the Stop handler:

   ```
   004a40: push {r3,r4,r5,lr}
   004a42: movs r0, #0
   004a44: bl #0xef74          ; Default Response, SUCCESS
   004a48: movs r2, #3          ; serial frame 03 03 <xor>
   ...
   004a60: bl #0x44f0          ; write it to the UART
   004a64: movs r0, #0          ; return false
   ```

5. Because the handler returned false, 0x4B5C returns 0x81 and 0xEC48 sends a second Default Response, 0x81. Both responses carry the same TSN and the same command ID.

**What each command does.** "Frame" is the bytes written to the motor controller (section 5).

| ZCL command | Handler | Serial frame | Default Responses (Disable Default Response clear) |
|---|---|---|---|
| 0x00 Up/Open | 0x4A0C | `03 01 02` | SUCCESS, then 0x81 |
| 0x01 Down/Close | 0x4A70 | `03 02 01` | SUCCESS, then 0x81 |
| 0x02 Stop | 0x4A40 | `03 03 00` | SUCCESS, then 0x81 |
| 0x04 Go to Lift Value | 0x4B14 | 8 bytes, malformed (below) | SUCCESS, then 0x81 |
| 0x05 Go to Lift Percentage | 0x4AA4 | `0d f1 00 00 00 00 00 00 04 40 PP 00 CS`, PP = the percentage byte unchanged, CS = 0xB8 XOR PP | SUCCESS, then 0x81 |
| 0x07 Go to Tilt Value | 0x4B38 | 8 bytes, malformed | SUCCESS, then 0x81 |
| 0x08 Go to Tilt Percentage | 0x4AF4 | 8 bytes, malformed | SUCCESS, then 0x81 |
| 0x03, 0x06, any manufacturer-specific | — | none | 0x81 only |
| short payload on 0x04, 0x05, 0x07, 0x08 | — | none | 0x80 (MALFORMED_COMMAND) only |

Notes:

1. **The SUCCESS is sent before the serial frame and means only "received".** The radio never waits for, or reads, any acknowledgement from the motor controller, and never retries a serial frame (section 5). A Zigbee SUCCESS therefore says nothing about whether the motor acted.
2. **Go to Lift Percentage passes the byte through.** No range check: 101 or 255 goes to the motor as it is, so the radio never returns INVALID_VALUE. What the motor does with such a value is untested.
3. **0x04, 0x07 and 0x08 send garbage.** These handlers write only bytes 5-7 (0x04 and 0x07: a 16-bit value and the code 0x66 or 0x67) or 6-7 (0x08: the percentage and 0x65) of the shared transmit buffer at RAM 0x20001DC2, then send its first 8 bytes. They set no length byte and no checksum. Bytes 0-4 are whatever the previous frame left: after an Up/Open, `03 01 02 …`, which the motor would parse as a second Up/Open (section 5); after a Go to Lift Percentage, `0d f1 …`, which announces a 13-byte frame and leaves the motor's parser waiting for 5 more bytes that will swallow the start of the next real command. **Never send 0x04, 0x07 or 0x08.**
4. **Which reply does the hub see?** A hub that matches replies by sequence number keeps whichever Default Response arrives first and treats the other as unsolicited. Normally that is SUCCESS. The 0x81 wins when the SUCCESS frame is lost or overtaken, for example when it needs an APS retry and the second does not. This explains a [community report](https://community.home-assistant.io/t/smartwings-zigbee-zha-lessons-learned/910917) that opening or closing 6-10 blinds at once "often" returns `unsupported_cluster_command` "after the blinds begin their travel" while they complete: the error is the second reply to the open or close itself, with that command's ID. Logging every unsolicited frame shows both replies.
5. **With "disable default response" set**, the SUCCESS is suppressed (the sender checks bit 0x10 of the frame control and status 0, 0xEF74), but the 0x81 is still sent, because it is an error. So a Stop sent with that bit set draws only the 0x81.

**What this changes.** The radio does forward Stop to the motor, and on a real shade the motor halts on it. Only the reply is wrong, and not just for Stop: every Window Covering command draws an UNSUP_COMMAND reply that contradicts the SUCCESS sent a moment earlier.

## 4. Reporting

**Answer.** The radio has **no** reporting engine: Configure Reporting and Read Reporting Configuration are both refused with Default Response 0x81, there is no reporting table, and bindings play no part. Instead the radio sends its own unsolicited Report Attributes, unicast straight to the coordinator (short address 0x0000, endpoint 1), whenever the motor controller sends it a new position or battery value. **Confidence: high** for the code.

Evidence **[source: firmware]**:

1. **Configure Reporting (0x06) and Read Reporting Configuration (0x08) are refused.** In the global-command switch of 0xEC48, both call stubs that return 0 (0x4C62 and 0x4D00: `movs r0,#0; bx lr`), and a 0 result leads to Default Response 0x81 (the shared exit after the switch, decompiled at 0xE57A-0xE2D6). The reporting plugin is not linked: both post-write hooks in the attribute writer are empty (0x4CE6 and 0x4D1A: `bx lr`), and nothing else is told when an attribute changes. So ZHA's pairing-time Configure Reporting for 0x0008 was answered 0x81, and no configuration exists to read back.
2. **The push path.** The serial receive handler (0x4894) handles message 0xF5 by taking byte 4 as the position (0x493E: `ldrb r3,[r4,#4]`). If it differs from the last value it pushed, it writes it to 0x0102/0x0008 (call at 0x495C) and calls the report builder 0x4764 with cluster 0x0102 and the attribute list `[0x0008]`. Message 0xF8 does the same for 0x0001/0x0021 with byte 2. The report builder writes a ZCL frame with frame control 0x08 (server to client), the next sequence number, command 0x0A (Report Attributes) and the attribute records, and sends it with an outgoing-message type of 0 (direct) to node 0 (`movs r1,#0` … `mov r0,r1` … `bl #0xcb72` at 0x47CE-0x47DA), profile 0x0104, source and destination endpoint 1. A debug string at 0x2D126, "Report>>%s u16ClusterID: %04x, SeqNum: %d, status: %d", belongs to it.
3. **Reads return a cached value.** 0x0008 is ordinary RAM storage (no external-storage bit), and nothing on the radio asks the motor for its position: no serial "query" message exists (section 5). So a read of 0x0008 returns the last position the motor sent. The initial value before the first 0xF5 is 0xFF.

**Measured since.** On a real shade, a Report Attributes for 0x0008 arrives a few seconds after travel ends, and a read during travel returns the position from before the move. So the motor sends 0xF5 once, when it stops, and the radio pushes it then. The report builder never sets the APS options field, so these reports may go without an APS acknowledgement or retry; whether the framework adds one on the way out was not traced.

**What this changes.** Configure Reporting and Read Reporting Configuration can only return 0x81, and bindings cannot affect reporting. The device refuses Configure Reporting outright (UNSUP_COMMAND) for an attribute ZCL section 7.4.2.5 says SHALL be reported. The radio's own end-of-travel pushes are what an integration can use for position.

## 5. The serial protocol to the motor controller

**Answer.** Not the Tuya MCU protocol. The frame is `LEN CMD DATA… XOR`, at 9600 baud 8N1, with no header bytes and no version byte. The radio sends seven message types and parses five. The radio reads only a position, a battery level and three pairing/reset requests from what the motor sends. Nothing about limits, stop position or direction is read by the radio. This bounds what the radio processes, not what the motor sends: the radio ignores some bytes of the position message and drops unknown message types, and those could carry more. **Confidence: high** for framing, checksum, baud and message list; medium for the meaning of the pairing messages.

**The link [source: firmware].**

1. **USART set-up** (0x4510). The init structure at 0x2D0E0 holds `enable = 5 (RX+TX), refFreq = 0, baudrate = 9600`, 16x oversampling, 8 data bits, no parity, 1 stop bit. The USART is at 0x40058000 (USART0 on the xG21). PA05 is set push-pull, high (`bl #0x87ac` with port 0, pin 5, mode 4, out 1) and is TX; PA06 is set input with pull-up (port 0, pin 6, mode 2) and is RX. The route registers written at GPIO+0x5BC (0x60000: PA06) and GPIO+0x5C4 (0x50000: PA05) agree **[inferred]** from the register layout. The zigpy discussion's "TX pin 6, RX pin 7" are presumably module pin numbers, not port pins.
2. **Wake-up.** A falling edge on PA06 raises interrupt 6 (configured at 0x45AA, callback 0x4400), which keeps the radio awake for 5 s (`movw r1,#0x1388` at 0x4412). Before sleeping, the radio disables PA05 (TX) and arms that interrupt (0x4710); on waking it turns PA05 back on (0x472A). There is **no** separate wake line to the motor controller: when the radio has something to say it just transmits.
3. **Framing.** The receive state machine (0x4490, fed byte by byte by the USART RX interrupt handler at 0x45CC, vector at 0x426C) waits for a first byte between 1 and 9 (`subs r3,r0,#1; cmp r3,#8; bhi` at 0x44A4), takes it as the total frame length, and collects that many bytes including itself. There is no header and no timeout; a partial frame is dropped only when the radio goes to sleep (0x447C clears the state). While a complete frame waits to be processed, further bytes are discarded.
4. **Checksum.** XOR of every byte before the last (0x4424). The receiver compares it with the last byte (0x48A6-0x48B6) and silently drops a mismatch. Example: Up/Open is `03 01 02`, and 0x03 XOR 0x01 = 0x02.
5. **The Tuya hypothesis is refuted.** No code builds or checks 0x55 0xAA, a version byte or a Tuya data point. The `_TZE200` strings (section 1) are in an NVM area the current application does not use, left by an earlier Tuya firmware.

**Radio to motor [source: firmware].** Every caller of the byte writer 0x44F0 (call sites at 0x4590, 0x46C0, 0x46E4, 0x48D2, 0x4916, 0x4A2E, 0x4A60, 0x4A92, 0x4AE2, 0x4B08, 0x4B2C, 0x4B50):

| Frame | When | Meaning |
|---|---|---|
| `66 66 11 22 33 44 55 66` | once, at UART init (0x4590) | A fixed 8-byte pattern from the initial transmit buffer, no checksum. Probably a test or hello pattern **[inferred]**. |
| `03 01 02` | ZCL Up/Open | open |
| `03 02 01` | ZCL Down/Close | close |
| `03 03 00` | ZCL Stop | stop |
| `0d f1 00 00 00 00 00 00 04 40 PP 00 CS` | ZCL Go to Lift Percentage | go to PP % (ZCL lift, 0 = open), unscaled |
| 8 bytes ending `… lo hi 66` / `… lo hi 67` / `… PP 65` | ZCL 0x04 / 0x07 / 0x08 | malformed (section 3, note 3) |
| `03 fa f9` | stack status: joined a network (0x46CA-0x46E4) | network up **[inferred]** |
| `03 fb f8` | stack status: no network (0x46A6-0x46C0); also the reply to motor messages 0xFB and 0xF9 | network down / acknowledge reset **[inferred]** |

Nothing the radio sends carries a limit, a stop position, a direction or a calibration flag, and no Zigbee attribute write produces a serial frame (section 8). The radio never asks the motor for anything.

**Motor to radio [source: firmware].** The receive handler 0x4894 acts on byte 1 of a frame with a valid checksum:

| CMD | Bytes the radio reads | What the radio does |
|---|---|---|
| 0xF5 | byte 4 | Position. If changed, writes 0x0102/0x0008 and pushes a report (section 4). Bytes 2-3 are received and ignored. |
| 0xF8 | byte 2 | Battery. If changed, writes 0x0001/0x0021 unscaled and pushes a report (section 6). |
| 0xFA | — | If not on a network: starts joining (0xA96C) and arms a 60 s window (`movs r2,#0x3c` at 0x4934) **[inferred]**: a pairing request. |
| 0xFB | — | Replies `03 fb f8`; if on a network, leaves it (0x1E4D4) **[inferred]**: a reset request. |
| 0xF9 | — | If on a network, leaves it; otherwise replies `03 fb f8` **[inferred]**. |
| anything else | — | Dropped silently. |

The frame lengths of 0xF5 and 0xF8 are not fixed by the radio (any 1-9). The motor's frames may carry more than the radio reads: bytes 2-3 of 0xF5 could be a direction, a state or a limit flag, but the radio throws them away, so they cannot reach Zigbee on this firmware. Whether the motor ever sends its limit or direction cannot be read from the radio's code. If it did, it would be in a message type the radio drops or in bytes it ignores. So "the motor sends only position and battery" is **not** established; what is established is that nothing else reaches Zigbee on this firmware.

**Zigbee to serial, serial to Zigbee, in one line each.** Zigbee 0x00/0x01/0x02/0x05 become serial 0x01/0x02/0x03/0xF1; 0x04/0x07/0x08 become malformed frames. Serial 0xF5 and 0xF8 become 0x0102/0x0008 and 0x0001/0x0021 plus a report; 0xF9/0xFA/0xFB drive joining and leaving and are not visible on Zigbee.

**What this changes.** The radio is a thin bridge: it maps Stop as well as the moves, and it passes no limit and asks for none. Go to Lift Percentage goes to the motor as a bare percentage, so scaling it between the remote's limits is done entirely by the motor controller (which, measured on real shades, it does).

## 6. Battery

**Answer.** 0x0001/0x0021 is the motor controller's byte, copied unchanged (0x4984: `ldrb r3,[r4,#2]`, written at 0x49A0). The radio does not convert units. 0x0001/0x0020 (voltage) is never written and stays at its default 0. **Confidence: high** for the radio; the unit is the motor's.

One shade's cached 0x0021 is 168 (Power Configuration `cache_before` in [discovery-office-shade.json](discovery-office-shade.json)), and that cache belongs to the vendor quirk's `DoublingPowerConfigurationCluster`, which doubles the value before caching it (`zhaquirks/__init__.py:263-266`, zha-quirks 2.3.0). So the radio most likely sent 84, meaning the motor sends **whole percent** and the radio puts it into a half-percent attribute **[inferred]**. That is a violation of ZCL8 section 3.3.2.2.3.2 that the doubling corrects. A raw read would confirm it.

## 7. Basic, identity and OTA

**Answer.** The OTA client reports manufacturer 0x1002, image type 0x0000, file version 2 and no hardware version. The node descriptor's manufacturer code is 0x1002. The application's own version is 2. Basic carries no version attributes. After a "no image" answer the client asks again in 5 minutes. **Confidence: high** for the constants; medium for the query cadence, which conflicts with the roughly hourly queries seen from a real shade.

Evidence **[source: firmware]**:

1. **Image identity.** The OTA version callback at 0xB8CC: `movw r2,#0x1002; movs r3,#2; strd r2,r3,[r0]` (manufacturer 0x1002 and image type 0 in the first word, file version 2 in the second), and hardware version 0xFFFF ("none") at 0xB8DE.
2. **Node manufacturer code.** The application's main routine stores 0x1002 at RAM 0x20001D4E (literal at 0xCF2C) before starting the stack, beside 0x52 twice (probably the maximum incoming and outgoing transfer sizes **[inferred]**). 0x1002 is the code assigned to Ember, now Silicon Labs, and the SDK's default; SmartWings did not set its own.
3. **Basic.** Only ZCLVersion, ManufacturerName, ModelIdentifier, PowerSource and ClusterRevision exist (section 2). ApplicationVersion, StackVersion, HWVersion, DateCode and SWBuildID will be refused as UNSUPPORTED_ATTRIBUTE. The only build identity on the air is the OTA file version 2.
4. **OTA query cadence.** The query routine (0xAE28) sends Query Next Image and arms the client's timer with 300 000 ms (literal at 0xAE8C). A non-SUCCESS answer such as NO_IMAGE_AVAILABLE re-enters it the same way, so the next query is due 5 minutes later. After ten consecutive errors, or with no server address, the client restarts server discovery 10 minutes later (0xACAC, literal 600 000 at 0xACC0). This is the SDK's OTA client with 5- and 10-minute delays **[inferred]**. One shade was seen querying about an hour apart, so the real cadence needs checking against a log before either figure is trusted.

## 8. Mode (0x0017) and ConfigStatus (0x0007): can the hub see a direction reversal?

**Answer.** No. Writing Mode stores the byte in RAM and does nothing else: no serial message, no callback, nothing reads it, and it is not kept in NVM, so it returns to 0x14 at the next restart. ConfigStatus is read-only and nothing in the firmware ever writes it, so it stays 0x03. No message the radio parses from the motor carries a direction (the motor may send one in bytes or message types the radio ignores, section 5). A direction reversal made with the remote is therefore **invisible** on Zigbee, and so is anything else the motor controller decides. **Confidence: high.**

Evidence **[source: firmware]**:

1. **The attribute writer** (0xDD38). After the access and range checks it calls the global pre-write hook (0x4CE8: returns 0, accept), the cluster pre-write hook (none for 0x0102), stores the value, then the post-write hooks 0x4D1A and 0x4CE6 (both `bx lr`) and the cluster's attribute-changed function (none for 0x0102, section 2).
2. **Nothing reads Mode or ConfigStatus.** The only application call to the attribute reader is in the report builder (0x4808), which reads the attributes it is reporting. The only application calls to the attribute writer are for 0x0102/0x0008, 0x0001/0x0021 and OTA client attributes (call sites 0x495C, 0x49A0, 0xAC00, 0xAC30, 0xB0D2).
3. **Not persistent.** Mode's mask is 0x01 (writable) without 0x02 (kept in NVM) (section 2).
4. **ConfigStatus is read-only.** Mask 0x00, so a network write gets READ_ONLY (0x88) from the writer's access check (0xDD98-0xDD9C: `ldrb r2,[r3,#4]; lsls r1,r2,#0x1f; bpl` to the 0x88 exit), and no code path writes it internally.

**The calibration bit (Mode bit 1)** is therefore harmless at the radio: the radio does not act on it and does not tell the motor. Setting it is harmless, and it cannot set a limit. The same holds for the reversal (bit 0), maintenance (bit 2) and LED (bit 3) bits.

**What this changes for the integration.** It cannot learn a remote-set reversal from 0x0007 or 0x0017: re-reading them can only show 0x03 and 0x14. Only watching the shade shows what a reversal does to raw Up/Open, Down/Close and Go to Lift Percentage.

## 9. Sleep and polling

**Answer.** Long and short poll intervals both 1000 ms, with a 3 s stay-awake after certain activity. The radio polls its parent about once a second while it sleeps. **Confidence: medium**: the defaults are read directly, and no other code writes the long-poll field, but runtime overrides through paths the analysis did not follow are possible.

Evidence **[source: firmware]**: the end-device-support initialiser at 0x91A4 writes, into the per-network state at RAM 0x20002C38, a long-poll interval of 1000 ms (`mov.w r2,#0x3e8; str r2,[r3,#8]`, unless already set), a short-poll interval of 1000 ms (`strh` at `[r3,#0xe]`), a wake timeout of 3000 ms (`movw r2,#0xbb8`) and a wake mask of 0x18. The only writer of the short-poll field outside initialisation is the OTA client, which speeds it up during a download (0xB4F6, 0xB924). Nothing writes the long-poll field after initialisation.

A 1 s poll fits the measured read latency of 0.8-1.9 s. It does not explain a first command being lost after idle: the radio would fetch that frame within a second. The firmware does suggest another place for the loss: the radio writes each serial frame once, immediately after sending SUCCESS, with no wake signal, no acknowledgement and no retry (sections 3 and 5). If the motor controller sleeps and misses the first bytes, the radio cannot know. That is a hypothesis about the motor side **[inferred]**, consistent with "frame 1 fails, frame 2 works". It can be tested from the hub: SUCCESS arriving with no movement points there.

## 10. Summary and what it changes

| Question | Answer | Confidence |
|---|---|---|
| 1. Chip and layout | EFR32MG21 (Series 2, Cortex-M33, 768 KiB); Gecko Bootloader 1.12 at 0; EmberZNet 6.9.1 (GSDK 3.1) application v2, unsigned, at 0x4000; NVM3 at 0x5A000; stale v1 Tuya image tail and stale Tuya NVM | High |
| 2. AF tables | 1 endpoint, 8 clusters, 32 attributes, matching discovery; no manufacturer-specific anything; Groups, Scenes and Identify have no command handlers | High |
| 3. Stop | Forwarded to the motor as `03 03 00`. Every Window Covering command sends SUCCESS then 0x81 when Disable Default Response is clear (handler bug); 0x04, 0x07, 0x08 send malformed serial frames | High (code); medium (which reply the hub keeps) |
| 4. Reporting | No reporting engine; Configure Reporting refused with 0x81; the radio pushes reports itself to 0x0000 when the motor sends a new position or battery value | High |
| 5. UART | `LEN CMD DATA XOR`, 9600 8N1, not Tuya; position and battery are the only data from the motor; nothing about limits or direction | High |
| 6. Battery | Motor's byte copied unscaled; likely whole percent; voltage never set | High (radio); medium (units) |
| 7. Basic/OTA | 0x1002 / type 0 / version 2; no version attributes; 5-minute query delay after "no image" | High (constants); medium (cadence) |
| 8. Mode and ConfigStatus | Mode write is a RAM-only no-op; ConfigStatus fixed at 0x03; reversal invisible | High |
| Poll | 1 s long and short poll | Medium |

**For the integration:**

1. **Stop is forwarded.** Pass it through. For the commands the radio forwards (0x00, 0x01, 0x02, 0x05), a 0x81 after SUCCESS is the double reply, not a failure or a reason to re-send; 0x04, 0x07 and 0x08 also draw SUCCESS then 0x81 but after writing a malformed serial frame (item 3), so they are never sent; a 0x81 to anything else (manufacturer-specific frames, 0x03, 0x06, unknown IDs) is a genuine refusal and nothing was forwarded.
2. **SUCCESS means "received by the radio", not "executed".** Only a position read (or a pushed report) shows that the motor moved.
3. **Never send 0x04, 0x07 or 0x08.** They write malformed frames that can repeat the previous command or corrupt the next.
4. **Direction cannot be detected.** A remote reversal never reaches 0x0007 or 0x0017.
5. **Unsolicited position reports are usable.** The radio pushes one when the motor sends a new position, which on real shades is at the end of travel.

**For a firmware fix**, the changes are precise: make the Window Covering handlers report the command as handled, so each command gets exactly one correct reply; implement the reporting plugin or at least accept Configure Reporting; fix the 0x04/0x07/0x08 frame builders or remove the commands from the table; report battery in half-percent; and carry the motor's limit and direction over the serial link into 0x0011 and 0x0007.
