# Discovery of the Office Shade's attributes and commands: procedure

Issue #36. The owner runs every step. Written on 2026-10-06 for the box as it stands: Home Assistant 2026.10.0b2 with zha 2.3.0, zigpy 2.3.0 and bellows 1.1.0, and ZHA Toolkit 1.2.2 (`zha_toolkit:` in `configuration.yaml`). The repo's `.venv` holds the same zigpy and bellows, and the offline test runs against those. It does not depend on the v18 quirk or our integration: it talks to the shade through ZHA Toolkit, so it can run on the current install or after the new one.

**Status: run once, on 2026-10-06 at 12:35-12:36 UTC.** The shade answered all 61 frames, nothing moved, and the result is committed as `docs/evidence/discovery-office-shade.json` and summarised in Part 1 §2a. A rerun overwrites `/config/zha_discovery_office_shade.json` on the box, and copying it back (§5) overwrites the committed JSON. To keep the 2026-10-06 run, copy a rerun to a new file name instead. That run used the earlier handler, which matched a reply on cluster and TSN only. All 61 of its recorded replies also pass the stricter check described in §1 item 7: each is a general command in the opposite direction, with the request's manufacturer code and its response command ID. The two unmatched frames are unaffected.

**Only the Office Shade:** IEEE `60:83:da:ff:fe:a0:00:02`, entity `cover.smartwings_wm25_l_z`. The handler refuses any other IEEE.

## 1. What it does

1. It asks the shade which attributes and commands each of its clusters supports, including manufacturer-specific ones. That covers the eight clusters it advertises on endpoint 1 (server 0x0000, 0x0001, 0x0003, 0x0004, 0x0005, 0x0102; client 0x0003, 0x0019). It also covers two it does not advertise, 0xFC01 and 0xEF00, as probes. For each cluster it sends Discover Attributes Extended (0x15), Discover Commands Received (0x11) and Discover Commands Generated (0x13). Each is sent once plain and once with manufacturer code 0x1002 (the shade's own, from its node descriptor). It keeps asking for the next page until the shade says the list is complete.
2. It then sends one Read Attributes (0x00) for each discovered attribute that zigpy does not already have a value for, one attribute per frame.
3. **Nothing moves.** Those four ZCL general commands are the only frames it can send. It never sends a cluster-specific command, such as open, close, stop or go-to, and the offline test checks that. There is one exception, sent by zigpy rather than by the handler. If a reply arrives after the handler has stopped waiting for it, or after zigpy has already taken a colliding frame as the reply, zigpy may answer it with a Default Response (0x0B, SUCCESS), because the shade leaves the reply's disable-default-response bit clear. A late reply on 0xFC01 or 0xEF00 gets no answer, because zigpy drops it. A Default Response cannot move the shade. The handler's docstring cites the zigpy lines. This was not observed in the 2026-10-06 run, whose one late reply was on 0xEF00.
4. **Nothing is changed in Home Assistant or zigpy.** Every frame goes through zigpy's `Cluster.request()` with `retries=0`. Replies are decoded by the handler and never reach zigpy's attribute cache. So no attribute is marked unsupported in `zigbee.db`, as zigpy's own `read_attributes` would do on an UNSUPPORTED_ATTRIBUTE reply (the handler's docstring cites the zigpy lines).
5. **Pacing.** One frame at a time. The handler waits up to 5 s for each reply and re-sends a frame at most once if no reply comes. After 3 unanswered frames in a row it stops and says so.
6. **Size.** At least 60 discovery frames (10 clusters × 3 discoveries × 2), one more per extra page, plus one read per uncached attribute and any re-sends. Expect about 70-100 frames. Replies from these shades take 0.8-1.9 s (Part 1 §3e), so a run usually takes 2-5 minutes and at most about 10. A shade that does not answer at all stops the run after 3 frames, about 15 s.
7. **Output.** Everything is written to `/config/zha_discovery_office_shade.json` after every frame, so even an interrupted run leaves a file. The file records every frame sent (with its ZCL bytes and TSN), every reply (raw bytes and decoded), each cluster's cached values before the run, and any other frame the shade sent meanwhile (`unmatched_frames`), such as a late reply or an OTA query. A frame counts as a frame's reply only if it is a general command in the opposite direction with the same cluster, TSN and manufacturer code, and it is the matching response command or a Default Response for that command. Anything else on the same cluster and TSN goes to `unmatched_frames`. A summary is logged at INFO and returned as the action's response.

## 2. Before you start

1. **Be at the shade with the remote**, though nothing should move (project rule: no frame without the owner present). If the shade moves at all, press Stop on the remote, then note the time and what it did.
2. Start away from the top of the hour. The hourly "SmartWings: position refresh" automation reads every shade at minute :00 and would interleave its frames with these.
3. Do not use the Office Shade's card or any automation on it while the run is going.
4. ZHA Toolkit loads only one file, `local/user.py`. This procedure puts the discovery handler there, replacing any file already there. §6 removes it afterwards.

## 3. Install the handler

On the Mac, from the repo root:

```sh
scp -i ~/.ssh/<your-key> docs/evidence/discovery_user.py \
  root@homeassistant.local:/config/custom_components/zha_toolkit/local/user.py
```

No restart is needed. ZHA Toolkit re-imports `local/user.py` on every call.

## 4. Run it (once)

Developer tools → Actions → YAML mode, paste, and press Perform action:

```yaml
action: zha_toolkit.execute
data:
  command: user_discovery_run
  ieee: "60:83:da:ff:fe:a0:00:02"
```

Leave the page open until the action finishes (2-5 minutes). The response shown is the summary: `frames_sent`, `replies`, `stopped_early` and a count per cluster.

To watch progress live instead (optional), run this first, and set it back to `notset` in §6:

```yaml
action: logger.set_level
data:
  custom_components.zha_toolkit.local.user: debug
```

**If `stopped_early` is not `null`,** the shade stopped answering. Wait a few minutes, then run the action once more. The new run overwrites the file, so copy the first one off first (§5) if it holds any replies.

## 5. Copy the result into the repo

On the Mac, from the repo root:

```sh
scp -i ~/.ssh/<your-key> \
  root@homeassistant.local:/config/zha_discovery_office_shade.json \
  docs/evidence/discovery-office-shade.json
```

Then tell the agent, or attach the file to issue #36. The agent writes the summary into Part 1: what exists beyond the ZCL standard, if anything. For the 2026-10-06 run this is done (Part 1 §2a). This command overwrites that run's committed JSON, so give a rerun's copy a new name.

## 6. Undo (same session)

In the Terminal & SSH add-on:

```sh
rm /config/custom_components/zha_toolkit/local/user.py
rm /config/zha_discovery_office_shade.json
```

Delete the JSON only after §5. The handler module stays in memory until the next restart, but nothing calls it. If you turned on the debug log in §4, set it back:

```yaml
action: logger.set_level
data:
  custom_components.zha_toolkit.local.user: notset
```

## 7. Sources

1. The handler `docs/evidence/discovery_user.py` cites the zigpy 2.3.0 lines it relies on in its docstring and comments.
2. The offline test is `tests/test_discovery_user_script.py`. It drives each frame through a real bellows 1.1.0 application up to bellows' `Sending packet` log line, and a simulated shade answers through the application's real `packet_received()`. It checks the exact frames: general frame type, command IDs 0x15/0x11/0x13/0x00, the manufacturer-specific bit and code 0x1002, and the client-direction bit for 0x0003/0x0019. It also checks that paging continues while `discovery_complete` is 0, that only uncached attributes are read, and that nothing is marked unsupported or written to zigpy's cache. A control test shows that zigpy's own `read_attributes` would have marked the attribute unsupported. The remaining tests cover the single re-send, the stop after 3 unanswered frames, and the refusal of any other IEEE. One more test covers frames that collide on cluster and TSN: an OTA Query Next Image Request, a wrong response command and a wrong manufacturer code. All three go to `unmatched_frames`, and the real reply is still taken, even though zigpy itself takes the OTA query as its reply.
3. ZHA Toolkit 1.2.2 on the box (read-only, 2026-10-06): `__init__.py:900-910` imports `local/user.py`, reloads it per call and passes eight positional arguments; when a response is requested it returns `event_data` (`:840-843`); `local/` was empty.
4. Office Shade facts from a read-only copy of `zigbee.db` (2026-10-06): node descriptor logical type 2 (end device), manufacturer code 4098 (0x1002), maximum buffer 82; endpoint 1 clusters as listed in §1; 35 cached attribute rows, three of them already marked unsupported (0x0001/0x0031, 0x0001/0x0033, 0x0102/0x0009). If discovery lists any of those three, the handler reads it, because it has no value in the cache. The read leaves the mark as it is.
