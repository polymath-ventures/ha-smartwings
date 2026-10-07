"""Constants for the SmartWings integration."""

from typing import Final

DOMAIN: Final = "smartwings"

# The shades this integration serves, as their zigpy device identifies itself.
SHADE_MANUFACTURER: Final = "Smartwings"
SHADE_MODEL: Final = "WM25/L-Z"

# The quirk ID the SmartWings quirk exposes as a ZHA feature: how this integration tells
# the quirk is loaded. A test keeps it equal to the quirk's.
QUIRK_ID: Final = "smartwings.wm25lz"

# Zigbee Home Automation's domain, here so that using it imports no ZHA library.
ZHA_DOMAIN: Final = "zha"
