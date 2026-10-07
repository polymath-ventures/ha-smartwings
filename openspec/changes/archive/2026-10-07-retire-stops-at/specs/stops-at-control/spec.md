## REMOVED Requirements

### Requirement: Exactly one "Stops at" control per shade, and it is ZHA's
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: The control shows the raw closed limit honestly
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: Changing a set stop goes through a confirmed dialog
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: Store operations are shared and follow every write with a refresh
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: In force across restart and ZHA reload
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: Clearing restores stock behaviour
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: No stop outlives the integration or its visible control
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: Stable entity id
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: No default creates a stop
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: Writes of a stop are serialised per shade and compare-and-set
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.

### Requirement: A change refuses while the control is missing
**Reason**: With the motor enforcing its remote-set limits over Zigbee (#54), "Stops at" has nothing to hold; its control, Change-stop dialog, store, pending clears and registry watch are removed.
**Migration**: Set the shade's limits with its remote (README). Nothing is stored, so nothing outlives the integration.
