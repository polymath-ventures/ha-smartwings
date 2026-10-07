# Test bench run sheets: sessions A-D

Issue #42. These are the step-by-step sheets for the owner's test sessions A-D in the [test plan](../test-plan.md) (§5). Each step names its test ID from the plan, so a result can be filed against it. Nothing here has been sent to a shade by the agent that wrote it.

**Only the Office Shade:** IEEE `60:83:da:ff:fe:a0:00:02`, entity `cover.smartwings_wm25_l_z`. The bench refuses any other IEEE.

| Session | State |
|---|---|
| A. Ask, don't move | **Run 2026-10-06** with bench version 1: [`sessions/2026-10-06-A.json`](sessions/2026-10-06-A.json), summary [`sessions/2026-10-06-A-observed.csv`](sessions/2026-10-06-A-observed.csv). Its results are folded into Part 1 and the plan separately. Steps A16b-A16j were not run (§4, end) |
| B. Every command, from mid-travel | **Partly run 2026-10-06** (owner present, driven via the Home Assistant API) with bench version 2: [`sessions/2026-10-06-B.json`](sessions/2026-10-06-B.json), observations [`sessions/2026-10-06-B-observed.csv`](sessions/2026-10-06-B-observed.csv). Seven calls: three live trials watched by the owner (Stop while moving, raw Up/Open, a go-to with reads), then B12, B13b and B14b, which were sent without the owner's confirmation that they were watching (a procedure violation, plan §2 rule 3): they have no owner observation and are to be repeated with the owner as B12-r, B13b-r and B14b-r. Bench version 2 left three second replies untagged that arrived within 8 ms of the first; the current bench tags them. The rest of B is still to run |
| C. Position and limits, with a tape measure | To run |
| D. Settings experiments | Not needed: the firmware answers all three tests (§7) |

## 1. How the bench works

1. **One file does everything.** `docs/evidence/bench_user.py` is a ZHA Toolkit handler. Each step below is one bench *action*, such as `user_bench_stop` or `user_bench_read`. You paste the step's YAML into Home Assistant and press a button. ZHA Toolkit re-reads the file on every call, so nothing needs a restart.
2. **Everything is logged.** Every frame the bench sends, every answer from the shade, and anything else the shade sends during a step go into one file per session: `/config/smartwings_bench_<session>.json` (for example `/config/smartwings_bench_B.json`). The file is updated after every frame, so even an interrupted step leaves a record. After its last frame each step keeps listening for 3 s, so a late second reply or a position report is caught too.
3. **The bench guards itself.**
   1. It sends nothing to any device but the Office Shade.
   2. A step that can move the shade must say `remote_ready: true` and `may_go_down: true`. The only exception is a go-to to lift 0 (fully open), which needs `remote_ready: true` alone. `may_go_down: true` is your statement that you are ready for the shade to go down, even when the step expects it to go up: a reversed motor or a misjudged target can send it down. Without these fields the bench refuses, and nothing is sent.
   3. A step that changes a setting must say `confirm: true`. The bench reads the setting first, writes it, reads it back, and gives you the exact undo. If it cannot read the value first, it writes nothing.
   4. **Three Window Covering commands are never sent**, whatever a step says: Go to Lift Value (0x04), Go to Tilt Value (0x07) and Go to Tilt Percentage (0x08). The shade's radio turns them into malformed motor frames that can repeat the previous command or corrupt the next ([firmware analysis](firmware-analysis.md) §3 note 3). The bench also never configures reporting and never binds: the firmware refuses the one and ignores the other (firmware analysis §4).
   5. It never re-sends a frame. If three frames in a row get no answer, it stops the step and says so.
   6. One step at a time: if a step is still running, the next is refused.
   7. A misspelt field is refused rather than ignored.
4. **Positions are ZCL "lift" numbers, not Home Assistant's.** Lift 0 is fully open and lift 100 is fully closed. Home Assistant's card counts the other way: lift 30 shows as 70 on the card. The Office Shade's remote-set stop is at lift 86 (card 14). Every go-to in these sheets is lift 70 or less.
5. **The shade answers every move twice, and the answers say nothing about the motor.** For Up/Open, Down/Close, Stop and Go to Lift Percentage the radio replies SUCCESS and then, by a firmware bug, a second Default Response UNSUP_CLUSTER_COMMAND (0x81) with the same sequence number (firmware analysis §3). The bench takes the SUCCESS as the answer and lists the 0x81 under `second_replies`. Neither says whether the motor moved or stopped: **judge every move by what the shade does**, by eye and by the position reads.

## 2. Before every session

### 2a. Have ready

1. The shade's remote, on the Office Shade's channel.
2. A laptop or phone open at **Developer tools → Actions**, in YAML mode: <http://homeassistant.local:8123/developer-tools/action>. To switch to YAML mode, use the "Go to YAML mode" link at the bottom of the action form (or the ⋮ menu at the top right).
3. Painter's tape and a tape measure, for the safe line (§2d).
4. A notes file for what you see, saved as `docs/evidence/sessions/<YYYY-MM-DD>-<session>-observed.csv` (plan §2, rule 6). Start it with this line:

   ```csv
   time,test_id,step,saw,direction,start_delay_s,end_by_eye,stopped_by_remote,notes
   ```

   One line per step: the time, the test ID and step from the sheet, what you saw in words, which way it moved (up, down or none), roughly how long before it started, where it ended by eye, whether you stopped it with the remote (yes or no), and anything else. Separate several items in one field with `;`.

### 2b. Install the bench

On the Mac, from the repo root:

```sh
scp -i ~/.ssh/<your-key> docs/evidence/bench_user.py \
  root@homeassistant.local:/config/custom_components/zha_toolkit/local/user.py
```

This replaces any `local/user.py` already there. No restart is needed.

### 2c. Check the remote, and keep the box quiet

1. **Check the remote's Stop.** Press Down on the remote, then Stop after 2 s. The shade must stop. The remote's Stop is the only stop known to work (Part 1 §3d); Home Assistant's Stop shows an error.
2. **Quiet box.** Do not use the Office Shade's card, voice, scenes or automations during the session. The hourly "SmartWings: position refresh" automation reads every shade at minute :00, so do not start a step between :58 and :03. (If you prefer, turn that automation off for the session in Settings → Automations & scenes, and turn it back on at the end.)

### 2d. Mark the safe line (sessions B and C)

Plan §2, rule 4.6. Before any session in which the shade may move down:

1. Drive the shade down with the remote until the remote stops it by itself.
2. Put a strip of tape on the window frame at the bottom bar's height. Measure its height above the sill and write it in your CSV (`test_id` `SAFE-LINE`).
3. From now on, **under Zigbee or Home Assistant control the bottom bar must never pass that tape**. Press the remote's Stop before it does, whatever the step expects. Reaching the line and carrying on is a failure, recorded as such (§2g).
4. Raise the shade to mid-travel with the remote.

### 2e. Running a step

1. Paste the step's YAML over whatever is in the YAML box, and press **Perform action**.
2. Wait for the response to appear below the button. Most steps take 4-10 s; the sheet says when a step takes longer. Leave the page open until the response appears.
3. **Read the response.** Under `bench:` look at:
   1. `outcome`: `done` is normal. `stopped early` means three frames in a row got no answer: wait a few minutes and run the step again. `refused` means the bench sent nothing more and `message` says why.
   2. `frames:`, and in each frame `answer`. That line is the shade's first answer in words, such as `Default Response SUCCESS (0x00)`, `0x0008 = 50` or `no reply within 5.0 s`.
   3. `second_replies`: the shade's second answers (§1, item 5).
   4. `reports`: any position or battery report the shade sent by itself during the step (for `REPORT-NONE-OBSERVED`). Usually empty.
   5. `result:`, where a step has one (for example `positions`, the position reads of a watch).
4. **If the action fails with a red error**, the bench refused the step. The message says why, and in almost every case that nothing was sent. Fix what it says (usually a missing `remote_ready: true`) and run it again.
5. **Report**: what the sheet asks for in each step, plus your CSV line. The session file holds everything else.

### 2f. The safety step before every moving step

Every step that can move the shade starts with **Safety**. It always means:

1. The shade is **mid-travel**, set with the remote (unless the step says to start elsewhere).
2. Your **thumb is on the remote's Stop**.
3. If the shade goes **down**, press Stop on the remote **within 2-3 s**, and in any case **before the bottom bar reaches the safe line**. Never let it run to the bottom: over Zigbee the motor ignores the stop you set with the remote, and a run to the bottom has bunched a blackout shade's fabric (Part 1 §3a).
4. After the step, **stay with the remote for 2 minutes**. One shade started about 100 s late (Part 1 §4).
5. If anything unexpected happens, press Stop on the remote, note the time, and stop the session.

### 2g. One failure ends a series

Plan §2, rule 4.7. Some steps below are a **series**: the same kind of move repeated (B3 and B8, the two raw Down/Close moves of the direction-reversal test; B13; B14; B16-B18; C2). In a series, a move that **fails** ends the series:

1. A failure is a move that goes the wrong way, runs on past its target, has to be stopped at the safe line when it was expected to stop by itself, or answers `send failed` or `stopped early`.
2. These are **not** failures: the second reply 0x81 (§1, item 5), which comes with every move; and, in `RADIO-FIRST-FRAME-FATE`, a go-to the shade does not act on, which is what that test measures.
3. When a series fails: record that step in your CSV, write `blocked` for each remaining step of the series, and do not go on with it until the cause is understood and you decide. Steps outside the series may continue.

## 3. After every session

1. Do every undo the session lists, and check that it read back as expected.
2. Copy the session file into the repo. On the Mac, from the repo root (replace the date and the session letter):

   ```sh
   mkdir -p docs/evidence/sessions
   scp -i ~/.ssh/<your-key> \
     root@homeassistant.local:/config/smartwings_bench_B.json \
     docs/evidence/sessions/2026-10-07-B.json
   ```

3. Save your CSV next to it, as `docs/evidence/sessions/2026-10-07-B-observed.csv`.
4. Remove the bench and the session file, in the Terminal & SSH add-on:

   ```sh
   rm /config/custom_components/zha_toolkit/local/user.py
   rm /config/smartwings_bench_B.json
   ```

   Delete the session file only after step 2. If you turned the position-refresh automation off, turn it back on. Remove the tape.
5. Tell the agent, or attach both files to issue #42.

## 4. Session A: ask, don't move (run 2026-10-06)

**Run on 2026-10-06** with bench version 1: 26 calls, copied from the box to [`sessions/2026-10-06-A.json`](sessions/2026-10-06-A.json), with a step-by-step summary of the log in [`sessions/2026-10-06-A-observed.csv`](sessions/2026-10-06-A-observed.csv) (the owner's own observations are not in the log). Its results are folded in separately. Bench version 1 did not capture the shade's second replies (A4-A7). This section is kept as the record of what was run. Most of its tests are now **answered by the firmware** (plan §4: `ID-DISCOVER-WILDCARD`, `ID-BASIC-VERSIONS`, `STOP-NO-DEFAULT-RESPONSE`, `STOP-WITHOUT-APS-ACK`, `STOP-MANUFACTURER-SPECIFIC`, `LIMIT-WRITE-READ-ONLY`, `MODE-WRITE-SAME-VALUE`, `REPORT-READ-CONFIG`, `GROUP-MEMBERSHIP-READ`, `SCENE-TABLE-READ`), so the run confirms them. `REPORT-BINDING-TABLE` is moot; the step that would have configured reporting and bound (`REPORT-CONFIGURE-AND-WAIT`) was not run and is now moot. Nothing in this session should move the shade.

### A1. `ID-DISCOVER-WILDCARD`: hidden manufacturer commands

Four steps: Discover Commands Received and Generated on 0x0102 and 0x0000, with the wildcard manufacturer code.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_discover
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: ID-DISCOVER-WILDCARD
  step: A1a
  cluster: 0x0102
  kind: commands_received
  manufacturer: 0xFFFF
```

A1b was the same with `kind: commands_generated`; A1c and A1d the same pair with `cluster: 0x0000`.

### A2. `ID-BASIC-VERSIONS`: firmware build details

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: ID-BASIC-VERSIONS
  step: A2a
  cluster: 0x0000
  attributes: [0x0001, 0x0002, 0x0003, 0x0006, 0x4000]
```

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: ID-BASIC-VERSIONS
  step: A2b
  cluster: 0x0000
  attributes: [0x0008, 0x0009, 0x000A, 0x000B, 0x000C, 0x000D, 0x000E]
```

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: ID-BASIC-VERSIONS
  step: A2c
  cluster: 0x0000
  attributes: [0xFFFD]
```

The plan also asks for 0xFFFD on the other five server clusters (A2d-A2h: `cluster` 0x0001, 0x0003, 0x0004, 0x0005, 0x0102). The log has A2c only.

### A3. `ID-POWER-DESCRIPTOR`

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_zdo
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: ID-POWER-DESCRIPTOR
  step: A3
  request: power_descriptor
```

### A4-A7. Stop, shade still

`STOP-WHILE-STILL`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_stop
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: STOP-WHILE-STILL
  step: A4
```

`STOP-NO-DEFAULT-RESPONSE` (A5) added `disable_default_response: true`; `STOP-WITHOUT-APS-ACK` (A6a, A6b) added `ask_for_ack: false` and then `ask_for_ack: true`; `STOP-MANUFACTURER-SPECIFIC` (A7) added `manufacturer: 0x1002`. Bench version 1 ended each step as soon as the first reply matched, so the log holds the SUCCESS of A4 and A6 but not the 0x81 that follows it (§1, item 5); version 2 keeps listening and records both.

### A8-A9. Writes of the value already held

`LIMIT-WRITE-READ-ONLY`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_write
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: LIMIT-WRITE-READ-ONLY
  step: A8a
  cluster: 0x0102
  attribute: 0x0011
  value: 0xFFFF
  expect_before: 0xFFFF
  confirm: true
```

A8b was the same for `attribute: 0x0010`, `value: 0x0000`, `expect_before: 0x0000`. Both answered READ_ONLY and read back unchanged: no undo needed.

`MODE-WRITE-SAME-VALUE`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_write
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: MODE-WRITE-SAME-VALUE
  step: A9
  cluster: 0x0102
  attribute: 0x0017
  value: 0x14
  expect_before: 0x14
  confirm: true
```

**Undo**, run as A9-undo: the same write of 0x14 (the value held). Mode read back 20 (0x14) both times. The firmware keeps Mode in RAM only, back to 0x14 at every restart (firmware analysis §8).

### A10-A11. Reporting configuration and binding table

`REPORT-READ-CONFIG`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read_reporting
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: REPORT-READ-CONFIG
  step: A10a
  cluster: 0x0102
  attributes: [0x0008]
```

A10b was the same for `cluster: 0x0001`, `attributes: [0x0021]`.

`REPORT-BINDING-TABLE` (moot, informational):

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_zdo
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: REPORT-BINDING-TABLE
  step: A11
  request: binding_table
```

### A13-A15. Battery, groups and scenes

`POWER-BATTERY-UNITS`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: POWER-BATTERY-UNITS
  step: A13
  cluster: 0x0001
  attributes: [0x0020, 0x0021]
```

The plan wants this read again just before the next charge, with `session: A-later` and `step: A13-later`.

`GROUP-MEMBERSHIP-READ`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_group_membership
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: GROUP-MEMBERSHIP-READ
  step: A14a
```

A14b read `cluster: 0x0004`, `attributes: [0x0000]`.

`SCENE-TABLE-READ`:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_scene_membership
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: SCENE-TABLE-READ
  step: A15b
  group: 0x0000
```

A15a read `cluster: 0x0005`, `attributes: [0x0000, 0x0001, 0x0002, 0x0003, 0x0004]`.

### A16. `RADIO-POLL-INTERVAL`: how long the shade can sleep

Each step waits `idle_s` seconds with nothing sent, then reads the position, `trials` times over. Run the next step as soon as one finishes, and leave the page open.

| Step | `idle_s` | `trials` | Takes about | Run 2026-10-06 |
|---|---|---|---|---|
| A16a | 5 | 3 | 30 s | yes |
| A16b | 15 | 3 | 1 min | no |
| A16c | 30 | 3 | 2 min | no |
| A16d | 60 | 3 | 3 min | no |
| A16e, A16f, A16g | 120 | 1 | 2 min each | no |
| A16h, A16i, A16j | 300 | 1 | 5 min each | no |

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: A
  test_id: RADIO-POLL-INTERVAL
  step: A16a
  cluster: 0x0102
  attributes: [0x0008]
  idle_s: 5
  trials: 3
```

Change `step`, `idle_s` and `trials` for each row. Report: for each frame, `idle_before_s`, `latency_s` and `answer` (a `no reply` is the data this test is after).

### End of session A

**Still to do:** A16b-A16j (about 45 minutes, nothing moves). Run them in a session of their own with `session: A-poll`, with §2a-§2c and §3 as usual (no safe line is needed). The writes A8 and A9 wrote the values already held and read back unchanged; nothing else was written.

## 5. Session B: every command, from mid-travel

About 2 hours. Have ready: §2a; the bench installed (§2b); the remote checked (§2c); **the safe line marked (§2d)**; **the remote's manual, open at its direction-reversal sequence**; a stopwatch; ideally a second person or a phone filming the shade, to time start delays. Use `session: B` throughout.

Start every moving step from the place the step says, set with the remote as part of that step's **Safety** step (§2f). "Mid-travel" means stopped near half, with the fabric well clear of both ends. Every step also feeds `REPORT-NONE-OBSERVED` and `RADIO-LATE-START` (B19, B20): report each step's `reports`, and its start delay in your CSV.

### B1-B10. `REMOTE-DIRECTION-REVERSAL` (first, high priority)

This includes `CMD-UP-OPEN-DIRECTION` and `CMD-DOWN-CLOSE-DIRECTION`.

**B1.** Read ConfigStatus and Mode:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: REMOTE-DIRECTION-REVERSAL
  step: B1
  cluster: 0x0102
  attributes: [0x0007, 0x0017]
```

Report: both values (expected 3 and 20; the firmware says no remote setting can change them, firmware analysis §8).

**B2.** Raw Up/Open. **Safety** (§2f): mid-travel; thumb on Stop; this may go **down**. Whichever way it goes, press Stop on the remote as soon as the direction is clear, after 2-3 s.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_up_open
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-UP-OPEN-DIRECTION
  step: B2
  remote_ready: true
  may_go_down: true
```

Report: which way it moved and how long before it started.

**B3.** Raw Down/Close. **Safety** (§2f): back to mid-travel with the remote; thumb on Stop; this is expected to go **down**: press Stop on the remote after 2-3 s, well above the safe line.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_down_close
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-DOWN-CLOSE-DIRECTION
  step: B3
  remote_ready: true
  may_go_down: true
```

Report: as B2.

**B4.** Go to lift 30. **Safety** (§2f): mid-travel; thumb on Stop. Lift 30 is above mid-travel, so it should go **up**. If it goes down, press Stop within 2-3 s.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: REMOTE-DIRECTION-REVERSAL
  step: B4
  value: 30
  remote_ready: true
  may_go_down: true
```

Report: which way it moved, and where it stopped by eye.

**B5.** **Safety** (§2f): the sequence may move the shade; keep it mid-travel and well above the safe line, thumb on Stop. Reverse the motor's direction with the remote, following the manual's sequence exactly. Write down the sequence you used.

**B6.** Read ConfigStatus and Mode again: run B1's YAML with `step: B6`. Report: both values.

**B7, B8, B9.** Repeat B2, B3 and B4, with `step: B7`, `B8` and `B9`, each with its own **Safety** step. After the reversal, any of them may go down: be ready, and watch the safe line.

**B10. Undo the reversal** with the same remote sequence, with the same **Safety** step as B5. Then:

1. Run B1's YAML with `step: B10a` and check both values match B1.
2. **Safety** (§2f): mid-travel; thumb on Stop. Run B2's YAML with `step: B10b` and check that the shade moves the same way as in B2. Stop it with the remote after 2-3 s.

**Do not go on until B10 confirms the original direction.** Report: B10a's values and B10b's direction.

### B11. `STOP-WHILE-MOVING`

Go to lift 30, then Stop 3 s after the go-to's answer, then read the position every 2 s for 60 s. The step takes about 70 s. The radio forwards Stop to the motor (firmware analysis §3); this step decides whether the **motor** honours it. Judge only by what the shade does and by `positions`, never by the replies.

**Safety** (§2f): use the remote to lower the shade to about halfway (below lift 30, so the go-to goes up); thumb on Stop. If it overshoots or goes down, press Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto_then_stop
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: STOP-WHILE-MOVING
  step: B11
  value: 30
  stop_after_s: 3
  remote_ready: true
  may_go_down: true
  watch_for_s: 60
  watch_every_s: 2
```

Report: did it halt within about 1 s of the Stop (about 3 s after it started), halt late (how late), or carry on to lift 30? `result` → `positions`; and both frames' answers and `second_replies`, for the record.

### B12. `STOP-JUST-AFTER-START`

The same, with Stop 0.5 s after the go-to's answer. **Safety** (§2f): back to about halfway with the remote; thumb on Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto_then_stop
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: STOP-JUST-AFTER-START
  step: B12
  value: 30
  stop_after_s: 0.5
  remote_ready: true
  may_go_down: true
  watch_for_s: 60
  watch_every_s: 2
```

Report: as B11, plus the Stop's `latency_s`.

### B13. `CMD-DUPLICATE-GOTO` (a series, §2g)

**B13a.** Go to lift 50 first, to start from rest at 50. **Safety** (§2f): mid-travel; thumb on Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-DUPLICATE-GOTO
  step: B13a
  value: 50
  remote_ready: true
  may_go_down: true
```

Wait until it has stopped.

**B13b.** Go to lift 30 twice, 2.5 s apart, then read every 5 s for 90 s. **Safety** (§2f): thumb on Stop (it should go up).

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto_twice
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-DUPLICATE-GOTO
  step: B13b
  value: 30
  gap_s: 2.5
  remote_ready: true
  may_go_down: true
  watch_for_s: 90
  watch_every_s: 5
```

**B13c.** Now at rest on 30, the same again: run B13b's YAML with `step: B13c`. **Safety** (§2f) as B13b; it should not move.

Report: did it move once and stop at 30, or move twice as far, or stop and restart? The `positions`.

### B14. `CMD-NEW-GOTO-WHILE-MOVING` (a series, §2g)

**B14a.** Go to lift 70 to start. **Safety** (§2f): mid-travel; thumb on Stop; this goes **down**, to lift 70, which is well above the safe line: if the bar nears the line, press Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-NEW-GOTO-WHILE-MOVING
  step: B14a
  value: 70
  remote_ready: true
  may_go_down: true
```

Wait until it has stopped.

**B14b.** Go to lift 20; 3 s after the answer, go to lift 50 instead; read every 2 s for 90 s. **Safety** (§2f): thumb on Stop (both moves are upward from 70).

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto_then_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: CMD-NEW-GOTO-WHILE-MOVING
  step: B14b
  value: 20
  then_value: 50
  after_s: 3
  remote_ready: true
  may_go_down: true
  watch_for_s: 90
  watch_every_s: 2
```

Report: did it end at 50 (it changed target) or at 20 (it ignored the second go-to)? The `positions`.

### B15. `POS-DURING-TRAVEL`

**B15a.** Go to lift 70: B14a's YAML with `test_id: POS-DURING-TRAVEL` and `step: B15a`, with the same **Safety** step. Wait until it has stopped.

**B15b.** Go to lift 10 and read every 2 s for 90 s. **Safety** (§2f): thumb on Stop (upward).

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: POS-DURING-TRAVEL
  step: B15b
  value: 10
  remote_ready: true
  may_go_down: true
  watch_for_s: 90
  watch_every_s: 2
```

Report: when it started and stopped by your stopwatch, and the `positions` (do they change during travel, in steps, or only at the end?).

### B16-B18. `RADIO-FIRST-FRAME-FATE` (a series, §2g)

Each trial is: leave the shade alone for 10 minutes (a phone timer helps), then one go-to, then readings every 2 s for 3 minutes. Nothing may be sent to the shade during the 10 minutes, from the bench or from Home Assistant, so run no other step meanwhile. The bench records the real idle time as `idle_before_s` on the go-to's frame; it should be 600 or more. A go-to the shade does not act on is this test's result, not a failure (§2g).

**B16.** Set up at lift 60. **Safety** (§2f): mid-travel; thumb on Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: RADIO-FIRST-FRAME-FATE
  step: B16
  value: 60
  remote_ready: true
  may_go_down: true
```

**B17a-B17c.** Three trials without a read first. Start a 10-minute timer when the previous step's response appears. When it rings, **Safety** (§2f): thumb on Stop; then run:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: RADIO-FIRST-FRAME-FATE
  step: B17a
  value: 40
  remote_ready: true
  may_go_down: true
  watch_for_s: 180
  watch_every_s: 2
```

Then B17b with `value: 60`, and B17c with `value: 40`, each after its own 10-minute wait and **Safety** step.

**B18a-B18c.** Three trials with a read 3 s before the go-to. Same 10-minute wait and **Safety** step before each:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: RADIO-FIRST-FRAME-FATE
  step: B18a
  value: 60
  read_before_s: 3
  remote_ready: true
  may_go_down: true
  watch_for_s: 180
  watch_every_s: 2
```

Then B18b with `value: 40` and B18c with `value: 60`.

Report for each trial: whether and when it started moving (stopwatch from pressing Perform action), the go-to's `answer`, `idle_before_s` and `latency_s`, and the `positions`.

### B19. `REPORT-NONE-OBSERVED` (passive)

Does the radio's own position report ever arrive? The bench has logged every frame the shade sent by itself during every step of this session; this step adds a remote move and 15 minutes of listening after the last move. It sends nothing.

Start listening with the YAML below. Then, within the first minute, **Safety** (§2f): thumb on the remote; move the shade with the remote from where it is to about a quarter open (upward) and stop it there, never letting it reach the safe line. Leave the page open for the 15 minutes.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_watch
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: B
  test_id: REPORT-NONE-OBSERVED
  step: B19
  for_s: 900
```

Report: this step's `reports` and `frames_from_shade_unasked`, and whether any earlier step of the session listed `reports`.

### B20. `RADIO-LATE-START`

No extra frames. Your CSV's `start_delay_s` for every moving step in this session is the data. Check that each line has it.

### End of session B

Undo check: B10 restored the motor's direction. Nothing was written. Then §3.

## 6. Session C: position and limits, with a tape measure

About 90 minutes. Have ready: §2a; the bench installed (§2b); the remote checked (§2c); **the remote's manual, open at its limit-programming instructions**; a tape measure fixed beside the shade so you can read the bottom bar's height. Use `session: C` throughout.

### C1. The safe line and reference heights

**Safety** (§2f): thumb on the remote. Mark the safe line (§2d); its height is the **original stop height**, which C4's undo returns to. Then raise the shade to the top with the remote and record the bottom bar's height there too.

### C2. `CMD-GOTO-PCT-ACCURACY` with `POS-READ-VS-PHYSICAL` (a series, §2g)

Twelve go-tos, in this order of `value`: 20, 40, 60, 40, 20, 0, then the same six again. Each step reads the position every 15 s for 90 s, so the last reading is where it stopped. Change `value` and `step` (C2a to C2l) each time. **Safety** before each (§2f): thumb on Stop; all targets are well above the safe line.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: CMD-GOTO-PCT-ACCURACY
  step: C2a
  value: 20
  remote_ready: true
  may_go_down: true
  watch_for_s: 90
  watch_every_s: 15
```

Report for each: the target, the last `positions` reading, and the measured height once it has stopped.

### C3. `POS-READ-VS-PHYSICAL` and `POS-TRACKS-REMOTE`: remote moves

**Safety** (§2f): thumb on Stop; the bottom bar stays above the safe line. With the remote only, stop the shade by eye at about a quarter closed, then half, then three quarters. After each, read the position and measure the height:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: POS-TRACKS-REMOTE
  step: C3a
  cluster: 0x0102
  attributes: [0x0008]
```

Use `step: C3b` and `C3c` for the next two. Report: each reading and height.

### C4. `LIMIT-PERCENT-SCALE` with `LIMIT-ATTRS-AFTER-REMOTE-SET`

`LIMIT-ATTRS-AFTER-REMOTE-SET` is answered by the firmware (only 0x0008 can change, firmware analysis §5, §8); its reads C4a and C4e are optional confirmations. `LIMIT-PERCENT-SCALE` is open: it shows whether the motor scales percentages to its full travel or to the remote's limits.

**C4a (optional).** Read the Window Covering attributes, and ask the shade for its attribute list:

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_read
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: LIMIT-ATTRS-AFTER-REMOTE-SET
  step: C4a
  cluster: 0x0102
  attributes: [0x0000, 0x0007, 0x0008, 0x0010, 0x0011, 0x0012, 0x0013, 0x0017, 0xFFFD]
```

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_discover
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: LIMIT-ATTRS-AFTER-REMOTE-SET
  step: C4b
  cluster: 0x0102
  kind: attributes
```

**C4c.** Open fully, then go to lift 50, and measure. **Safety** (§2f): thumb on Stop.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: LIMIT-PERCENT-SCALE
  step: C4c-open
  value: 0
  remote_ready: true
  watch_for_s: 90
  watch_every_s: 15
```

When it has stopped, **Safety** (§2f): thumb on Stop; this goes down to lift 50, well above the safe line.

```yaml
action: zha_toolkit.execute
data:
  command: user_bench_goto
  ieee: "60:83:da:ff:fe:a0:00:02"
  session: C
  test_id: LIMIT-PERCENT-SCALE
  step: C4c
  value: 50
  remote_ready: true
  may_go_down: true
  watch_for_s: 90
  watch_every_s: 15
```

Report: the height at lift 50.

**C4d.** **Safety** (§2f): thumb on Stop; the bottom bar must not reach the safe line while you set the new limit. **Change the lower limit with the remote** to about 20 cm higher than the original stop height, following the manual (on zigbee2mqtt's page for this shade: move the shade to the spot, then double-press Down). Record the new stop height. This is a setting change; its undo is C4g. The safe line stays where it is.

**C4e (optional).** Repeat C4a's two steps with `step: C4e-read` and `C4e-discover`.

**C4f.** Repeat C4c's two go-tos with `step: C4f-open` and `C4f`, each with its **Safety** step. Report: the height at lift 50 now.

**C4g.** **Safety** (§2f): thumb on Stop; while you set the limit back, stop the shade by hand if the bottom bar would pass the safe line. **Undo: put the lower limit back** at the original stop height (the safe line), with the same remote sequence. Then check it: lower the shade with the remote and let it stop by itself; measure. It must stop at the safe line (within a centimetre or two). **Do not end the session until it does.**

Report: the two heights at lift 50, the height after the undo, and (if run) the C4a and C4e readings side by side.

### C5. `LIMIT-OPEN-END` (optional)

Only if the remote's manual describes setting an **upper** limit.

1. **Safety** (§2f): thumb on Stop. Set an upper limit below the top with the remote, per the manual. Record its height.
2. **Safety** (§2f): mid-travel; thumb on Stop. Go to lift 0:

   ```yaml
   action: zha_toolkit.execute
   data:
     command: user_bench_goto
     ieee: "60:83:da:ff:fe:a0:00:02"
     session: C
     test_id: LIMIT-OPEN-END
     step: C5
     value: 0
     remote_ready: true
     watch_for_s: 90
     watch_every_s: 15
   ```

3. Report: did it stop at the upper limit you set, or at the top?
4. **Safety** (§2f): thumb on Stop; the shade will move while you set the limit. **Undo:** restore the original upper limit with the remote, per the manual, and check the remote's Up now stops at the original top height.

### End of session C

Undo check: C4g restored the lower limit; C5's undo (if run) restored the upper limit. Then §3.

## 7. Session D: settings experiments (not needed)

The plan's three Mode tests, `MODE-LED-BIT`, `MODE-MAINTENANCE-BIT` and `MODE-REVERSAL-BIT`, are **answered by the firmware**: no code in the radio reads Mode, a network write to it is held in RAM only and back to 0x14 at restart, and no serial message to the motor follows a write (firmware analysis §8). None of the bits can do anything, so the session would only confirm that. There is no run sheet for it. If you still want to confirm, ask the agent for one; each test would be a guarded write of Mode, a go-to, and the write of 0x14 back.

## 8. What the sheets never do

1. **Never sent:** Go to Lift Value (0x04), Go to Tilt Value (0x07) and Go to Tilt Percentage (0x08). The bench refuses them in code. Their tests, `CMD-GOTO-LIFT-VALUE`, `CMD-TILT-VALUE` and `CMD-TILT-PERCENTAGE`, are **do not run** (plan §4b).
2. **Not scheduled, because the firmware answers them** (plan §5): `CMD-GOTO-PCT-OVER-100`, `CMD-IDENTIFY`, and `STOP-MANUFACTURER-SPECIFIC`'s moving trial.
3. **Moot:** `REPORT-CONFIGURE-AND-WAIT`. Nothing configures reporting or binds; `REPORT-NONE-OBSERVED` (B19) only listens.

## 9. Sources

1. The bench: `docs/evidence/bench_user.py`. Its docstring and comments cite the zigpy 2.3.0 lines it relies on: `Cluster.request()` with `retries=0`, the application listener that sees replies first, and why nothing reaches zigpy's attribute cache.
2. The offline tests: `tests/test_bench_user_script.py` drives every action through a real bellows 1.1.0 application, cut off at bellows' `Sending packet` log line, with a simulated shade that answers as the firmware does (SUCCESS, then 0x81). It checks the exact frames, that each is sent once, the move and write guards and the recorded undo, the IEEE and cluster allow-lists, that 0x04, 0x07 and 0x08 are refused before any frame, strict reply matching against colliding frames, the second reply, report logging, the stop after three unanswered frames, appending to one session file, and that zigpy's attribute cache is untouched. `tests/test_bench_run_sheets.py` runs every YAML block in these sheets through the bench's own checks, checks that every moving block follows a **Safety** step and that no block uses a never-sent command, and checks that every test the plan schedules in sessions A-D is named here.
3. The [firmware analysis](firmware-analysis.md): §3 (the double reply; Stop forwarded; 0x04, 0x07 and 0x08 malformed), §4 (reporting), §8 (Mode).
4. ZHA Toolkit 1.2.2 on the box (read-only copy, 2026-10-06): `execute` accepts extra fields (`__init__.py:56-99`, `extra=vol.ALLOW_EXTRA`); a `user_*` command is run from `local/user.py`, reloaded on every call, with the service call passed in (`:901-912`); with a response requested it returns `event_data` (`:841-843`).
5. The test plan, `docs/test-plan.md`: §2 (ground rules, including rules 4.6 and 4.7), §3 (the bench), §4 (each test), §5 (sessions).
