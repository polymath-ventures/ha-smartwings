## REMOVED Requirements

### Requirement: Contract terms are defined once, by U
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: U is a quirks v2 quirk that exposes the setting through ZHA
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: The value is in raw Home Assistant cover-position space
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: Reading the value is local, cheap and fail-closed
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: Writes through the cluster are validated and never change a set stop
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: Clearing removes the stop for good
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: No caller can send the contract attribute over the air
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: U never creates a value nobody set
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: Presence of the contract is detectable without names
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").

### Requirement: I holds its own copy of the published contract terms
**Reason**: The motor enforces the limits set with its remote for Zigbee commands too (#54, Part 1 §3a reversed), so there is no second closed limit to publish; the 0xFC01 cluster and its `number` control are removed from U.
**Migration**: Set the shade's limits with its remote (README). Whether U is loaded is decided by its quirk ID (`integration-core`, "Quirk activity is decided by U's quirk ID").
