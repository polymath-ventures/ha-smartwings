# SmartWings WM25/L-Z and Home Assistant: findings

This is the index of the design record. How to install and use the quirk and the integration is in the [README](../README.md) at the top of the repository.

Written 2026-10-05. Code facts were checked against `~/code/ha-smartwings` as it stood that day, and against the installed zigpy 2.3.0, zha 2.3.0, zha-quirks 2.3.0 and Home Assistant 2026.10.0b0.

| File | One line |
|---|---|
| [1-the-devices.md](1-the-devices.md) | What the Zigbee WindowCovering cluster requires, where these motors depart from it (measured), which departures are violations, and what the hub cannot do about them. |
| [2-the-current-home-assistant-software.md](2-the-current-home-assistant-software.md) | **Historical (2026-10-05).** What zigpy, zha-device-handlers, the SmartWings quirk, ZHA and our custom integration each were and were called, and why the arrangement of that date could not deliver the behaviour on its own. The "Stops at" software it describes was retired by #54. |
| [3-what-must-be-built.md](3-what-must-be-built.md) | Specification of the upstream quirk change and our integration: the user-visible contract, constraints, failure modes to rule out, and the definition of done. |
| [evidence/firmware-analysis.md](evidence/firmware-analysis.md) | What the Zigbee radio's firmware does (#43): chip and layout, the cluster tables, why every Window Covering command draws 0x81, the serial protocol to the motor controller, reporting, battery, OTA and polling. |
| [test-plan.md](test-plan.md) | The one test plan for the reference, the integration and the letter: every test by descriptive ID, with its question, spec clause, method, safety, status and evidence, grouped into owner sessions and an offline firmware track. |
| [deploy-runbook.md](deploy-runbook.md) | The owner's runbook for issue #15: retire the old install on the box, install the integration, check each shade's remote limits, and run acceptance on every shade, with results in [evidence/acceptance.csv](evidence/acceptance.csv). |

## Proven versus suspected

**1. Measured on the shades** (from the research record, 2026-10-03/04):
1. ~~The remote-set closed limit is ignored over Zigbee by both command forms, while the remote stops correctly.~~ Reversed by #54 (2026-10-06): Zigbee closes stop at the limits set with the remote, with lift 100 at the lower limit (Part 1 §3a).
2. `installed_closed_limit_lift` reads 65535.
3. `config_status` is 3, which means Operational and Online, with no reversal bit.
4. Stop is rejected with UNSUP_CLUSTER_COMMAND.
5. First frames usually produce no movement, and a re-send works.
6. No position reports have been seen.
7. The lift axis is plain ZCL, with one unexplained contradicting read.
8. Reads answer in 0.8-1.9 s, and full travel takes 30-70 s.
9. Samples are small, and the per-frame counts survive only as summaries.

**2. Proven from installed source:**
1. The roles of each layer and the correct terms for them.
2. The command path from `cover.close_cover` to the quirk's cluster.
3. The released vendor quirk has no state and swaps up/down unconditionally.
4. No integration can intercept another's entity.
5. The setup-order chain: ZHA resolves every device before a custom integration can register a quirk, so an integration-only install gets none of the behaviour after a restart.
6. ZHA reports "closed" only at position 0.
7. Quirks v2 can declare a number config entity, and a quirk ID (`exposes_feature`) that ZHA lists in the device's `exposes_features`.

**3. Proven by the repo's tests, against real zigpy clusters and a real Home Assistant with ZHA stubbed:**
1. The frames our quirk sends for opens, closes, positions, re-sends and Stop, and that Open, Close, Stop and the slider work through the real ZHA cover entity with no error on the firmware's double reply (#54).
2. The integration's quirk install, missing-quirk Repairs issue and quirk-ID detection, against a real Home Assistant and real ZHA.
3. ~~A quirks v2 quirk lets ZHA host "Stops at" itself ([ADR 0001](decisions/0001-quirk-v2-hosts-stops-at.md)).~~ Proven, then retired with "Stops at" (#54).

**4. Suspected, with what would settle each:**
1. Why the first frame fails. Settle with zigpy's frame-1 response, the node descriptor, or a sniffer capture.
2. Whether reporting configuration is accepted. Settle with Read Reporting Configuration.
3. What `window_covering_mode` (0x0017) = 0x14 means. Test 8d read it as 20 on all nine, as reported by the HA agent on 2026-10-05 and not independently verified. The meaning of its bits is unexplained.
4. ~~That the card shows a stale mid-travel position after each move.~~ Settled by #51: a read during travel returns the lift from before the move, and the shade reports its position when travel ends (Part 1 §3f).

**5. Open:**
1. Which way raw `up_open` moves these units. Raw `down_close` lowers them [measured, indirect] (Part 1 §3c), and raw `up_open` raised the Office Shade once (#51); both are sent unswapped (#34, #54).
2. ~~A shade resting at its stop never reports "closed".~~ Moot since #54: the shade reports lift 100, closed, at its remote-set lower limit.
3. **No result of the current code on the real shades is recorded.** Version 18 of the quirk has been on the box since 2026-10-05.
4. ~~Only the test harness (#5) and the quirks v2 spike run the real ZHA.~~ The integration's and the cover's tests run the real ZHA through the harness (#5).
