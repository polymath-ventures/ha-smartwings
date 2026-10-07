# ADR 0001: The quirk is a quirks v2 quirk, and it hosts "Stops at"

Status: **superseded**, 2026-10-06, by #54 (OpenSpec change `retire-stops-at`). Accepted
2026-10-05. Issue #6. Evidence: `tests/spikes/test_quirks_v2_spike.py` (deleted with #54; see
the repository history), run against real Home Assistant 2026.10.0b0 and real ZHA 2.3.0
through the #5 harness.

**Superseded.** The premise behind "Stops at", that the motor ignores the remote's closed limit
over Zigbee (Part 1 §3a), was reversed live on 2026-10-06: Zigbee closes stop at the limits set
with the remote. "Stops at" was retired with the 0xFC01 cluster, its `number`, the capture and
clear actions and the Change-stop dialog. Decision 1 stands: U is still one quirks v2 quirk,
built with `QuirkBuilder`, that replaces the WindowCovering cluster and keeps the doubled
battery reporting. It now adds no cluster and declares a quirk ID with `exposes_feature`,
which the integration reads to tell U is loaded. Decisions 2-4 are retired. The rest of this
record is kept as written.

## Question

Part 3 §1c: if the quirk (U) can declare the closed-limit setting as its own configuration
entity, the integration (I) must not create a second one. Can a quirks v2 WM25/L-Z do that on
this stack, and should U be v1 or v2?

## What the spike proved

A v2 prototype (`tests/spikes/v2_prototype_quirk.py`), supplied through `custom_quirks_path`.
Each row is a test in the evidence file.

| Question | Result |
|---|---|
| ZHA creates the `number` entity on the shade's own device | Yes, as `number.<shade>_stops_at`: the entity id comes from the name, not the translation key |
| Setting it sends a frame to the shade | No: the value lives on a `LocalDataCluster` |
| A replaced WindowCovering cluster can intercept `command()` and read the value | Yes: a close went out as `go_to_lift_percentage(86)` for a stop of 14 |
| The v2 quirk wins over the released v1 vendor quirk | Yes |
| The stop is shown **and in force on the first close** after an HA restart and a ZHA reload | Yes |
| ...without `manufacturer_code=0x1002` on the attribute | No: the value is lost (negative control) |
| zigpy's public `cluster.update_attribute(attr, None)` clears it for good | Yes, but ZHA keeps **showing** the old value until the entity is refreshed (`homeassistant.update_entity`) |
| A live read (ZHA's device panel) goes on the air or marks the setting unsupported | No, set or unset, **given** `_VALID_ATTRIBUTES` (without it, an unset read is recorded as unsupported) |
| The quirk can refuse to change an already-set value | Yes: the user gets `Failed to write attribute closed_limit=20: READ_ONLY` |

Without `manufacturer_code=0x1002`, zigpy saves the row under the shade's manufacturer code
but reloads it into its legacy cache, where reads never look. Nothing logs an error.

The prototype answers only these questions. It does not carry the vendor quirk's command swap
for a close with no stop set, or its doubled battery reporting; both are owed by the real
quirk (#9) and are not evidence here.

## Decision

1. **U is a quirks v2 quirk**, built with `zhaquirks.builder.QuirkBuilder` (the
   `zigpy.quirks.v2` and `zigpy.quirks.CustomCluster` import paths are deprecated). It replaces
   the WindowCovering cluster with a subclass that does delivery and limit logic, and adds the
   closed-limit cluster. It must also keep the vendor quirk's doubled battery reporting and,
   with no stop set, its close frame (Part 3 §3a; #9).
2. **U hosts "Stops at".** The setting is attribute `0x0000` (`uint8`, read/write,
   `manufacturer_code=0x1002`, listed in `_VALID_ATTRIBUTES`) on a `LocalDataCluster` with
   cluster id `0xFC01`, server side, endpoint 1, exposed with `QuirkBuilder.number` (range from
   #7's constants, step 1, unit `%`, translation key `closed_limit`, fallback name "Stops
   at"). zigpy's database is the only store. **I creates no number entity.** The entity id is
   `number.<shade>_stops_at`, derived by Home Assistant from the name; this revises Part 3
   §2b's `number.<shade>_closed_limit`, which a ZHA-hosted control labelled "Stops at" cannot
   have. Renaming it is the user's choice, and Home Assistant keeps the user's id (F11).
3. **Coordinate spaces.** The stored value, and so the number the control shows, is the raw
   Home Assistant cover position of the stop over full travel (0 = fully closed, 100 = fully
   open): the value the remote set, such as 14. The cover entity is rescaled so the stop reads
   as closed (Part 3 §2h, #9). The owner accepted that the control and the slider therefore
   use different spaces (2026-10-05), which revises Part 3 §2b.
4. **Changing a set stop needs confirmation** (owner's rule, 2026-10-05). U's cluster refuses a
   write that changes a set value. I's Configure dialog ("Change stop") and capture with
   `replace_existing` change it through zigpy's public cluster API (`update_attribute`) on the
   device object ZHA already holds, and refresh the control afterwards. I never imports or
   calls quirk code; it relies on the published ids and on zigpy.

## Consequences

- **#7 (contract):** the terms in decision 2 are the contract. The v1 route's interception of
  reads, writes and reporting requests is unnecessary: `LocalDataCluster` keeps writes local
  and answers reads from its cache. Test the restart round-trip and the unset read; both
  pitfalls fail silently.
- **#12 ("Stops at" control):** take its Branch A. I adds no entity. It provides the
  Change-stop dialog, clears every shade's stop when the integration is removed (F9), and
  watches the entity registry: if the ZHA control is removed or disabled while a stop is set,
  it clears the stop or tells the user it is still in force, so no hidden stop can stay
  active (Part 3 §2f).
- **#13 (capture and clear):** both write through `update_attribute` after their own checks,
  then refresh the control. Clear writes `None`, which also deletes the database row.
- **Part 3 §2m changes:** when U is not loaded, the shade has no "Stops at" control at all,
  rather than an unavailable one. No stop that is not in force is ever shown, which is the
  section's intent, and I's notification still names each shade and the fix. Recorded for
  the docs update (#3), with the §2b revisions in decisions 2 and 3.
- **Cost accepted:** a direct edit of a set value on the device page fails with ZHA's generic
  `READ_ONLY` message, which cannot point at the Change-stop dialog. The dialog and the
  integration's docs say how to change a stop.
- **Upstream:** the v2 quirk replaces the vendor's v1 `wm25lz.py` quirk. The `0xFC01` cluster
  exists only in the quirk; the motor never sees it.
