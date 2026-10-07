## MODIFIED Requirements

### Requirement: Clear removes the closed limit and restores stock behaviour
The integration SHALL provide the action `smartwings.clear_closed_limit`, which targets exactly one cover entity belonging to a WM25/L-Z under ZHA. It SHALL remove that shade's closed limit through the clear operation shared with `stops-at-control` (zigpy's `update_attribute(attr, None)`, which also deletes the database row), leaving the contract's unset state, and SHALL then refresh ZHA's "Stops at" control. Afterwards the shade SHALL behave exactly as if no closed limit had ever been set (Part 3 §2d, §3a). Clear SHALL send nothing over the air. It SHALL be idempotent: clearing a shade with no closed limit succeeds and changes nothing. Like every store write, a clear whose write landed but whose control does not show `unknown` fails with the store's error saying the stop was cleared (stored) but the control could not be refreshed. When ZHA is not running, or the quirk is not active for the shade, there is no closed-limit cluster to clear: clear SHALL fail with `HomeAssistantError` naming the shade (and, for the quirk, the `custom_quirks_path` remedy), as the shared clear operation does. Clear and capture SHALL run one at a time per shade.

#### Scenario: Clear then close
- **WHEN** a shade has closed limit 16, the user runs `smartwings.clear_closed_limit` on its cover, then calls `cover.close_cover`
- **THEN** the stored closed limit is unset, the "Stops at" control shows no value, and the close frame is `down_close` (0x01) with no payload, as with no closed limit ever set

#### Scenario: Clear with nothing set
- **WHEN** clear runs on a shade with no closed limit
- **THEN** the action succeeds, the stop stays unset, and no frame is sent

#### Scenario: Clear on a non-SmartWings cover
- **WHEN** clear targets a cover that is not a WM25/L-Z
- **THEN** the action raises `HomeAssistantError`, and nothing changes

#### Scenario: Clear during a capture
- **WHEN** clear is called while a capture of the same shade is in flight
- **THEN** clear runs after the capture finishes, and the shade ends with no closed limit

#### Scenario: Clear store fails
- **WHEN** the store path raises during clear
- **THEN** the action raises `HomeAssistantError` naming the shade

#### Scenario: Clear with the quirk inactive
- **WHEN** clear targets a WM25/L-Z whose loaded quirk is the stock vendor quirk
- **THEN** the action raises `HomeAssistantError` naming the shade and the `custom_quirks_path` remedy, and sends no frame
