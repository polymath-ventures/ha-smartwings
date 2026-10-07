"""Constants for the SmartWings integration."""

from typing import Final

DOMAIN: Final = "smartwings"

# The shades this integration serves, as their zigpy device identifies itself.
SHADE_MANUFACTURER: Final = "Smartwings"
SHADE_MODEL: Final = "WM25/L-Z"

# The quirk ID the SmartWings quirk (U) declares through ZHA's exposed features; ZHA lists
# it in the device's ``exposes_features``. The only thing this integration reads to tell
# U is loaded; a test keeps it equal to the quirk's.
QUIRK_ID: Final = "smartwings.wm25lz"
