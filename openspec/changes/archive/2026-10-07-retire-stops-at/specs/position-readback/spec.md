## ADDED Requirements

### Requirement: Tracking reads through the read retry and caches what the shade sent
Tracking SHALL obtain positions only through `command-delivery`'s `_read_lift_live()`, which uses the read retry and returns the lift without touching the cache. Tracking SHALL put each successful reading in the cache only through the cluster's `update_attribute`. The cluster SHALL cache every lift the shade sends, by a read, a report or tracking, exactly as sent, so that ZHA's own `100 - lift` is the only conversion between ZCL lift and HA position (F1). A lift outside 0-100, including the ZCL "unknown" 0xFF, SHALL NOT enter the cache, and SHALL raise no attribute event. Tracking SHALL compare only the returned lifts, SHALL NOT write the attribute cache by any other path, and SHALL NOT convert between coordinate spaces.

#### Scenario: A shade closed to its lower limit reads as closed
- **WHEN** `cover.close_cover` is tracked and the motor settles at its remote-set lower limit, reporting lift 100
- **THEN** the `cover.*` state is `closed` with `current_position` 0

#### Scenario: A position is shown as the shade reports it
- **WHEN** a read or report returns lift 41
- **THEN** the cached lift is 41 and the cover shows position 59

#### Scenario: Unknown position is not cached
- **WHEN** a read or report returns lift 255
- **THEN** the cached lift keeps its previous value and no attribute event is emitted

#### Scenario: A dropped read is retried, not counted as unreadable
- **WHEN** the first frame of a tracking read is dropped and its retry succeeds
- **THEN** the reading counts as one successful reading

## REMOVED Requirements

### Requirement: Tracking reads through the single conversion and the read retry
**Reason**: The rescaling it routed readings through (`LiftScale`) is gone with the closed limit (#54).
**Migration**: "Tracking reads through the read retry and caches what the shade sent".
