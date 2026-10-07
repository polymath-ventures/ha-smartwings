## Context

Every route into a shade (dashboard, voice, scenes, automations, bridges, direct service calls)
reaches the motor through one object: the zigpy WindowCovering cluster instance the quirk
installs (Part 2 §2). ZHA's cover entity (zha 2.3.x, `zha/application/platforms/cover`) does
three things this design depends on, verified in the installed source:

1. It computes position as `100 - cluster.get("current_position_lift_percentage")` and reports
   CLOSED only when that is exactly 0 (`_determine_state`).
2. It recomputes state when the cluster emits an attribute event for 0x0008
   (`handle_attribute_updated`).
3. It sends `up_open()`, `down_close()`, `go_to_lift_percentage(100 - position)` and `stop()`.

zigpy 2.3.x routes every incoming value of a known attribute, from both Read Attributes
responses and Report Attributes, through `Cluster._update_attribute()` via
`_legacy_apply_quirk_attribute_update()`. It caches whatever `_update_attribute` stores and
emits `AttributeUpdatedEvent` with the cached value when it differs from the raw one. The
return value of `read_attributes()` is built from the raw response, before that hook.

The motors ignore the remote-set stop over Zigbee (Part 1 §3a), report
`installed_closed_limit_lift` as 65535, never push position (Part 1 §3f), reject Stop
(Part 1 §3d), and on one unit stall on run-to-limit open (Part 1 §3b). The closed limit comes
from `closed-limit-contract` (#7) in raw HA cover-position space; delivery (verify and re-send)
comes from `command-delivery` (#8).

## Goals / Non-Goals

**Goals:**
- No command from any caller moves a shade past its stop (Part 3 §1a-2, §2g).
- A shade at its stop is "closed" everywhere (Part 3 §2h), and the slider spans open → stop.
- Unset is stock in direction and end point (Part 3 §3a): every frame matches the released quirk
  except opens, which are go-to 0 (D4).
- F1, F16 and F18 are impossible by construction.

**Non-Goals:**
- Delivery, verification and re-send (#8); the post-travel read (#10); how the stop is stored
  and validated (#7); capture and the UI (#11–#13).
- Correcting the vendor quirk's command-ID swap. If test 8a (#4) shows it is wrong, that is a
  separate upstream change with evidence (Part 3 §3a).

## Decisions

### D1. Rescale in the cluster's attribute cache, not in ZHA or the integration

The scaled lift is what U writes into the attribute cache for 0x0008, by overriding
`_update_attribute`. ZHA then needs no change: its `100 - lift` gives the scaled HA position,
"closed" falls out of its own rule at scaled lift 100, and its go-to arguments arrive in scaled
lift, which U unscales in `command()`.

*Alternatives:* a template or wrapper cover (banned, Part 3 §3d); patching ZHA (unsupported,
Part 2 §3b); scaling in the integration (the integration cannot intercept ZHA's entity, Part 2
§3b). Overriding `read_attributes` to rewrite its return value was rejected: capture and
delivery verification need the raw value, and zigpy already separates the raw return value from
the cached one.

### D2. One pure conversion module, `LiftScale`

A frozen value object built from the closed limit (or none), exposing `scaled_from_raw(raw_lift)`,
`raw_from_scaled(scaled_lift)` and the close target. It holds the only arithmetic between
spaces; `command()`, `_update_attribute()` and the rescale-on-change path call it and nothing
else. It is tested exhaustively over all 101 raw values and every valid limit (property tests),
which is cheap and makes F1 a test, not a convention. The HA↔lift step for the stop itself
(`L = 100 - s`) lives here too. `add-closed-limit-contract` (#7) owns only the contract terms
and the range constants `CLOSED_LIMIT_MIN`/`CLOSED_LIMIT_MAX`; it provides no conversion.
`LiftScale` also exposes the stop-independent inversions `ha_position_from_lift(raw_lift)` and
`lift_from_ha_position(position)` (both `100 - x`, with range checks) for U's own use. Capture
(`add-closed-limit-capture`, #13) needs only that inversion, which is the ZCL and Home
Assistant convention rather than quirk logic, so I computes it itself and never imports or
mirrors `LiftScale` (Part 3 §1c, owner decision 2026-10-05).

### D3. Formulas and constants

`L = 100 - s`, `A = L - CLOSE_TARGET_MARGIN`, band start `S = A - min(CLOSED_BAND, A // 4)`.
Scaled lift is 100 in the closed band `r >= S`, otherwise `round_half_up(99 * r / (S - 1))`;
unscale is `A` at 100, otherwise `round_half_up(p * (S - 1) / 99)`. Integer arithmetic, round
half up, so results are deterministic across Python versions.

- **`CLOSE_TARGET_MARGIN = 2` lift points**, kept from oldcode (named so because the merged
  contract reserves the `CLOSED_LIMIT_` prefix for its published terms). The motor's own
  position estimate is the only odometer (Part 1 §7f), and overshooting the stop bunches
  fabric while stopping short costs about 2 % of travel (≈0.6–1.4 s at the measured 30–70 s
  full travel). The cost is asymmetric, so the margin points one way. Part 3 §5c-2 ("stops at
  or above the stop, fabric unbunched") is the acceptance check; if a shade overshoots, the
  constant grows.
- **`CLOSED_BAND = 2` lift points.** A go-to to `A` lands within a point or two of `A`, and the
  motor never reports on its own. Without a band, landing at `A - 1` would show position 1 and
  "open", which is the bug §2h exists to fix. The band is the same size as the margin, so the
  closed region is `[A-2, 100]`, which always contains the stop lift `L`.
- **The band shrinks with little travel**: `min(CLOSED_BAND, A // 4)`, so at the highest stop
  (95, `A = 3`) it is 0 and raw 0–2 stay open positions; `S >= 3` for every valid stop.
- **Positions 0–99 map onto the open range `0..S-1`, not `0..A`.** Mapping onto `0..A` sent
  the top slider positions into the closed band (Stops at 14: slider 1 → raw 83, which reads
  closed; at stop 95 slider 50 → raw 2, closed). With the open range, every slider position
  above 0 lands below the band, the scale stays monotonic, and only position 0 (scaled 100,
  sent as `A`) reads closed. A landed position reads back within half a raw lift step,
  `99 / (2 * (S - 1))` positions plus rounding (within 1 up to stop 62; 25 at 94–95). A
  property test covers every stop × every slider position.
- **Known limit at the highest stops.** Stops 91–95 leave under 8 points to the target, so the
  band is narrower than `CLOSED_BAND`, and at 95 it is empty: target and band start are both
  raw 3, and a landing at raw 2 reads HA position 1. Integer lift cannot avoid this without a
  position above 0 reading closed; accepted (review 2a).

### D4. Command translation table

| Incoming (from ZHA or any caller) | Limit unset (stock) | Limit set |
|---|---|---|
| `up_open` 0x00 | `go_to_lift_percentage(0)` | `go_to_lift_percentage(0)` |
| `down_close` 0x01 | `up_open` (vendor swap) | `go_to_lift_percentage(A)` |
| `go_to_lift_percentage(p)` 0x05 | unchanged | `go_to_lift_percentage(raw_from_scaled(p))` |
| `go_to_lift_value` 0x04 | unchanged | refused, error naming the shade |
| `stop` 0x02 | sent once, unverified | sent once, unverified |
| anything else | unchanged, sent once | unchanged, sent once |

- **Every open is go-to 0, stop or no stop (owner decision, 2026-10-05).** Part 3 §3a forbids
  changing a command's direction or end point versus the released quirk, not its form. Go-to 0
  has the same direction and end point (fully open) on the measured, unambiguous lift axis
  (Part 1 §3g). It completed first time where run-to-limit open stalled three times on one unit
  (Part 1 §3b, DH:210-222), and it does not depend on the unresolved direction of the raw command
  IDs (Part 1 §3c). Overshooting the top is harmless: the fabric is on the tube. The upstream PR
  states this form change and its evidence; for unset users the shade still ends fully open.
- **Close with no stop stays the vendor frame.** Strict §3a: byte-identical (`up_open`, the
  vendor swap) to what every ZHA user gets today, until hardware test 8a (#4) reports which way
  that frame moves these units. The owner tests these settings on the Office Shade.
- **`go_to_lift_value` is refused with a stop set**, because its units are relative to installed
  limits the device reports as unset, so it cannot be bounded. ZHA never sends it, but the
  cluster-management panel can.
- **Keyword forms.** zigpy names the field `percentage_lift_value`; both positional and keyword
  calls are normalised before translation, and the normalised value is the only one forwarded,
  so an argument can never be passed twice or dropped (an oldcode defect class).

### D5. Raw position is kept in memory; the cache holds scaled

`_update_attribute(0x0008, raw)` validates 0–100, records `self._raw_lift = raw`, and stores
`LiftScale.scaled_from_raw(raw)`. Values outside 0–100 (0xFF = unknown) are swallowed: the
cache and raw field keep their previous values. The raw value is not persisted. zigpy persists
the scaled cache, and ZHA reads 0x0008 at startup (`read_on_startup=True`), which repopulates
the raw value when the sleepy shade answers.

*Why scaling in `_update_attribute` is sufficient (verified in zha 2.3 source).* ZHA's cover
reads its position only from the cluster's attribute cache: `current_cover_position` returns
`100 - self._cluster.get(current_position_lift_percentage)`
(`zha/application/platforms/cover/__init__.py:333-347`), and `async_update` only re-reads the
attribute through `safe_read`, which repopulates the cache and discards the return value
(`:620-631`). So the scaled value written by `_update_attribute` is exactly what ZHA displays
and what drives its "closed" rule, while `read_attributes` and `read_attributes_raw` still return
the undecorated device value to their callers. Delivery verification (#8), end-of-travel
tracking (#10) and capture (#13) all compare raw lift taken from those return values.

*Alternative rejected:* persisting raw lift in a second local attribute. That adds a second
stored copy needing the same unsupported-mark and panel protections as the contract attribute
(F10), for the sole benefit of exact rescale after a restart with no successful read. D6 covers
that case without a second store (Part 3 §3e).

### D6. Rescale on limit change

The enforcement cluster subscribes to the sibling closed-limit cluster's (`0xFC01`, #7)
`AttributeUpdatedEvent` and `AttributeClearedEvent`; either triggers `_rescale()`. The clear
event matters: I clears a stop with zigpy's `update_attribute(attr, None)`, which emits only
`AttributeClearedEvent` (ADR 0001). `_rescale()` builds the new
`LiftScale`, takes `_raw_lift`, or if that is unknown derives a display-only raw value by
unscaling the cached value with the previous `LiftScale`, and writes the new scaled value
through `_update_attribute` so ZHA gets the event. A derived raw value is flagged so
`_cached_lift_raw()` returns `None` to #8, whose F6 rule then sends at least two frames.
In-flight commands keep the target computed when they started. Every command that can move
the shade (open, close, both go-tos) waits for #8's per-shade lock first and is translated
exactly once while holding it, so a command never mixes two limits and a stop set while a
command waits is honoured; Stop and tilt are translated and sent without the lock.

### D7. Seam with `command-delivery` (#8)

#8 owns the seam; this change uses #8's names unchanged:

```
WireCommand(command_id, args, target_lift)   # target_lift: raw ZCL lift; None = send once
await self._deliver(WireCommand(...))        # zigpy reply, or a DeliveryError subclass naming the IEEE
self._read_lift_live() -> int | None         # raw; #8's default, not overridden here
self._cached_lift_raw() -> int | None        # raw baseline; OVERRIDDEN by this change
```

`command()` is the translator: it turns each incoming command into a `WireCommand` and calls
`self._deliver(...)`. Movement commands carry a raw `target_lift`; Stop, tilt and every other
command carry `target_lift=None`, which #8 sends once, unverified, without the lock or the
tracking hooks.

`_cached_lift_raw()` is the single baseline accessor; there is no separate
`raw_lift_baseline()`. Once this change rescales, the attribute cache holds scaled values, so it
overrides #8's default (which reads the cache) to return: the in-memory `_raw_lift` when it came
from the device; otherwise the cached value when no closed limit is set (the scale is the
identity, so the cache is raw); otherwise `None`, including when `_raw_lift` was only derived
for display (D6). #8 compares live raw reads (`_read_lift_live()`, the `read_attributes` return
value) against `target_lift` and this baseline, so no scaled value ever meets a raw one.

### D8. Fail closed on a broken contract read

The contract's reader returns "unset" only when the attribute is absent. Any other exception
while reading it aborts the movement command with an error naming the shade (F13). Out-of-range
stored values are #7's to classify; per #7 they read as unset and are logged at ERROR.

### D9. One v2 quirk, with vendor parity (ADR 0001)

U is built with `zhaquirks.builder.QuirkBuilder("Smartwings", "WM25/L-Z")`: `.replaces()` the
WindowCovering cluster with this change's subclass, `.replaces()` PowerConfiguration with the
vendor quirk's `DoublingPowerConfigurationCluster`, and `.adds()` #7's closed-limit cluster
(registered once, in the same chain). Supplied through `custom_quirks_path` it wins over the
released v1 vendor quirk (proven in the #6 spike), so everything that quirk did for this device
must carry over: the doubled battery percentage, and with no stop set the swapped close frame
(D4). The enforcement subclass reads the stop through #7's accessor on the sibling cluster
(`endpoint.in_clusters[0xFC01]`), never through a class reference, and treats a missing sibling
cluster as a contract read failure (D8).

## Risks / Trade-offs

- [The motor's position estimate drifts and a go-to to `A` overshoots the stop] → the margin
  points the safe way; §5c-2 is the per-shade acceptance check; the margin is one constant.
- [The slider is relative to the stop, not mechanical travel] → accepted by the owner (Part 3
  §2h). Capture reads raw (#13), so changing the stop never compounds scaling.
- [Restart with no successful read, then a limit change: the display is derived and may be off
  by a point] → display-only. Delivery treats the baseline as unknown, and the next read
  corrects it.
- [Shade pushed past its stop by the remote reads "closed"] → true for "is it closed?". The
  raw lift is still visible to capture. Detecting overrun is out of scope.
- [Opens in the unset state differ in form from the released quirk's frame] → same direction
  and end point, so §3a holds; the upstream PR must state the change and cite Part 1 §3b. If
  upstream reviewers object, the unset open can revert to the vendor frame without touching the
  set path.
- [The unset close keeps the vendor's swapped run-to-limit frame, whose direction is unverified]
  → required by §3a until #4 reports; #4's evidence feeds a separate change if warranted.
- [A limit change during travel does not retarget] → bounded by one command. Retargeting would
  need a mid-travel go-to built from a stale read, which F16 forbids in spirit.
- [ZHA's `assert current_cover_position is not None` in `async_set_cover_position`] →
  unchanged by this design. The cache is only ever a scaled valid value or unchanged.

## Migration Plan

Pure quirk behaviour; no stored data changes shape. When a box moves from oldcode v18 to the
new U, the cached 0x0008 is raw, and it becomes scaled on the first read after a limit is set.
Rollback means removing U from `custom_quirks_path` and restarting; the cached lift may show
scaled until the next read.

## Open Questions

- Should `CLOSE_TARGET_MARGIN` and `CLOSED_BAND` be retuned after §5c acceptance on the Office
  Shade? Revisit with the acceptance data (#15).
