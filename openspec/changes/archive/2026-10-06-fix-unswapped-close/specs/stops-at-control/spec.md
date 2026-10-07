## MODIFIED Requirements

### Requirement: Clearing restores stock behaviour
After a clear, the shade SHALL behave exactly as if no stop had been set (Part 3 §2d, §5b item 6).

#### Scenario: Clear then close
- **WHEN** the stop is cleared and `cover.close_cover` is called
- **THEN** the frame is `down_close` (0x01) with no payload, as with no stop ever set
