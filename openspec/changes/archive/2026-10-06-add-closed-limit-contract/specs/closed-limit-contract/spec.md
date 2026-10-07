## ADDED Requirements

### Requirement: Contract terms are defined once, by U
U SHALL define the closed-limit contract in a single module that states: endpoint 1; cluster id `0xFC01` (server side, a `LocalDataCluster`); attribute id `0x0000`; ZCL type `uint8`; `manufacturer_code` `0x1002`; the coordinate space; `CLOSED_LIMIT_MIN` = 0 and `CLOSED_LIMIT_MAX` = 95 (inclusive); that "unset" means the attribute is absent from the device's attribute cache; and that the attribute is never sent over the air (Part 3 §1c items 1–6, ADR 0001).

#### Scenario: Contract module states every term
- **WHEN** the contract module is imported
- **THEN** it exposes the endpoint, cluster id, attribute id, type, manufacturer code, coordinate-space name, `CLOSED_LIMIT_MIN`, `CLOSED_LIMIT_MAX` and the unset semantics as named constants, and a test asserts each value

#### Scenario: Range is the one shared range
- **WHEN** any code in U or I validates, clamps, displays or accepts a closed limit, including the `number` metadata's minimum and maximum
- **THEN** it uses `CLOSED_LIMIT_MIN` and `CLOSED_LIMIT_MAX` by name and no other literal bound appears in the codebase (F7)

### Requirement: U is a quirks v2 quirk that exposes the setting through ZHA
U SHALL be built with `zhaquirks.builder.QuirkBuilder` for manufacturer "Smartwings" and model "WM25/L-Z". It SHALL add the closed-limit `LocalDataCluster` and declare a `number` entity for attribute `0x0000` with minimum `CLOSED_LIMIT_MIN`, maximum `CLOSED_LIMIT_MAX`, step 1, unit `%`, translation key `closed_limit` and fallback name "Stops at", so that ZHA creates exactly one "Stops at" control on the shade's own device (Part 3 §1c, ADR 0001).

#### Scenario: ZHA creates the control on the shade's device
- **WHEN** Home Assistant starts with U supplied (harness #5)
- **THEN** exactly one `number` entity for the closed limit exists on the shade's ZHA device, named "Stops at", with entity id `number.<shade>_stops_at`, minimum 0 and maximum 95

#### Scenario: Unset shade shows no value
- **WHEN** no stop has ever been set
- **THEN** the control's state is `unknown`

### Requirement: The value is in raw Home Assistant cover-position space
The stored value SHALL be a Home Assistant cover position in the raw, unscaled space: 0 = the motor's mechanical fully-closed end, 100 = fully open, measured against full motor travel. It SHALL mean "the position at which the remote stops this shade". Conversion to ZCL lift and any rescaling for "closed means at the stop" SHALL NOT alter the stored value (Part 3 §2h, F1, ADR 0001 decision 3).

#### Scenario: Stored value is not rescaled
- **WHEN** a stop of 14 is stored and the cover later displays scaled positions
- **THEN** reading the contract attribute and the "Stops at" control both still show 14

#### Scenario: Space is named at every boundary
- **WHEN** the contract value crosses a function boundary in U or I
- **THEN** the parameter, return value or constant name states that it is raw HA cover position (F1)

### Requirement: Reading the value is local, cheap and fail-closed
U SHALL provide an accessor that returns the shade's closed limit, or "unset", from the device's own attribute cache, with no radio traffic, no file or disk I/O on the event loop, no environment variables and no Home Assistant imports (Part 3 §3b). It SHALL return "unset" when the attribute is absent, and SHALL return "unset" and log at ERROR (naming the device IEEE and the rejected value) when the cached value is not an integer within `CLOSED_LIMIT_MIN`..`CLOSED_LIMIT_MAX` (F7). An exception inside the accessor SHALL NOT be turned into a permissive answer (F13).

#### Scenario: Absent attribute reads as unset
- **WHEN** a shade has never had a closed limit written
- **THEN** the accessor returns unset, sends no frame and logs nothing above DEBUG

#### Scenario: In-range value is returned
- **WHEN** the cache holds 14
- **THEN** the accessor returns 14 and sends no frame

#### Scenario: Out-of-range cached value is ignored loudly
- **WHEN** the cache holds 96 or 255 (for example written through zigpy's API by mistake)
- **THEN** the accessor returns unset and logs one ERROR naming the IEEE and the value

#### Scenario: Wrong type is ignored loudly
- **WHEN** the cache holds a non-integer value under the contract key
- **THEN** the accessor returns unset and logs one ERROR

### Requirement: Writes through the cluster are validated and never change a set stop
The closed-limit cluster's `write_attributes` and `write_attributes_raw` SHALL apply the same rules. Each SHALL store an integer within range when no valid stop is set (an invalid cached value counts as unset) or when the value equals the current stop, and SHALL persist it to zigpy's database. It SHALL answer `INVALID_VALUE` and store nothing for a value out of range or of the wrong type (F7, F8). It SHALL answer `READ_ONLY` and leave the stop unchanged when a valid stop is set and the new value differs (owner's confirm-before-change rule, ADR 0001 decision 4). As with ZCL Write Attributes, each attribute in a request stands alone: a raw write of any other attribute is answered `UNSUPPORTED_ATTRIBUTE` without affecting the closed limit, and the reply lists a status record for each refused attribute. No write SHALL send a frame.

#### Scenario: First set through the control is accepted and persists
- **WHEN** "Stops at" is set to 14 on a shade with no stop, then Home Assistant with ZHA is fully restarted (harness #5)
- **THEN** no frame was sent, the control shows 14 after the restart, and the accessor returns 14 before the first cover command (Part 3 §2f)

#### Scenario: Value survives a ZHA reload
- **WHEN** 14 is set and ZHA's config entry is reloaded
- **THEN** the control shows 14 and the accessor returns 14

#### Scenario: Changing a set stop through the control is refused
- **WHEN** the stop is 14 and "Stops at" is set to 20
- **THEN** the service call fails with an error, the stop stays 14 and no frame is sent

#### Scenario: Out-of-range write is rejected
- **WHEN** 96, -1 or a non-integer is written through `write_attributes`
- **THEN** the status is `INVALID_VALUE`, the previous value (or unset) is unchanged and no frame is sent

### Requirement: Clearing removes the stop for good
Clearing SHALL be zigpy's public `update_attribute(attr, None)` on the contract attribute. It SHALL remove the value from the cache and delete its row from zigpy's database, so the shade reads as unset after a restart (Part 3 §2d, §2f). Because ZHA does not react to the clear event, whoever clears SHALL refresh the "Stops at" control afterwards (ADR 0001).

#### Scenario: Clear persists across restart
- **WHEN** a stop of 14 is cleared and Home Assistant with ZHA is fully restarted
- **THEN** the accessor returns unset, the control shows `unknown` and the database has no row for the attribute

### Requirement: No caller can send the contract attribute over the air
Every read, write, bind or reporting request for the closed-limit cluster SHALL be served locally and SHALL NOT produce a frame, whoever makes it (ZHA entities, ZHA's "Manage Zigbee device" panel, `zha_toolkit`, or direct cluster calls). A live read with `allow_cache=False` SHALL succeed whether or not a stop is set, and SHALL NOT mark the attribute unsupported (F10). The attribute SHALL be listed in the cluster's `_VALID_ATTRIBUTES` to guarantee this for the unset case.

#### Scenario: Forced read of a set stop is local
- **WHEN** the stop is 14 and the attribute is read with `allow_cache=False`
- **THEN** no frame is sent, the read succeeds with 14 and the attribute is not marked unsupported

#### Scenario: Forced read of an unset stop is local and not marked unsupported
- **WHEN** no stop is set and the attribute is read with `allow_cache=False`
- **THEN** no frame is sent, the read succeeds with no value and the attribute is not marked unsupported

### Requirement: U never creates a value nobody set
No code path in U SHALL write the contract attribute except a write through `write_attributes` or `write_attributes_raw`, under the same rules, or a clear. U SHALL have no default value, no restore logic and no fallback value for it (F15, Part 3 §2e).

#### Scenario: Fresh device stays unset through restarts
- **WHEN** a WM25/L-Z is paired with U and Home Assistant is restarted three times with no write
- **THEN** the accessor returns unset each time and the zigpy database has no row for the contract attribute

### Requirement: Presence of the contract is detectable without names
The contract SHALL be detectable from the device object alone: endpoint 1 carries an in-cluster with id `0xFC01` whose attribute definitions include id `0x0000` with type `uint8` and manufacturer code `0x1002`. I SHALL decide "U is active for this shade" with exactly this test and SHALL NOT use any Python class name, module path or cluster class name (Part 3 §1c, REV 7c). Missing or malformed device structure SHALL yield "not present"; an unexpected error SHALL propagate rather than be caught by a catch-all handler. No failure SHALL yield "present" (F13).

#### Scenario: Stock vendor quirk is detected as absent
- **WHEN** the shade was built with the released `zhaquirks.smartwings.wm25lz` quirk
- **THEN** the presence test returns false

#### Scenario: U is detected as present
- **WHEN** the shade was built with U
- **THEN** the presence test returns true

#### Scenario: A renamed class does not change the answer
- **WHEN** U's quirk or cluster class is renamed but the cluster and attribute definitions are unchanged
- **THEN** the presence test still returns true

#### Scenario: A definition without the manufacturer code is not the contract
- **WHEN** a cluster at `0xFC01` declares attribute `0x0000` without manufacturer code `0x1002`
- **THEN** the presence test returns false

#### Scenario: Malformed device data is not the contract
- **WHEN** the device object has no endpoints mapping, no endpoint 1, no cluster `0xFC01`, no attribute definitions, or a definition that is not an attribute definition
- **THEN** the presence test returns false without raising

### Requirement: I holds its own copy of the published contract terms
The contract terms SHALL be treated as a published protocol. I SHALL carry its own copy of them and SHALL NOT import or call U's code. While U and I share this repository, a test SHALL fail if any term in I's copy differs from U's contract module.

#### Scenario: I does not import U
- **WHEN** the imports of every module under `custom_components/smartwings` are scanned
- **THEN** none imports U's quirk file or `zhaquirks.smartwings`

#### Scenario: Divergent constant fails the build
- **WHEN** `CLOSED_LIMIT_MAX` in I's copy differs from U's
- **THEN** the equality test fails
