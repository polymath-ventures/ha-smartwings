"""The ZHA surfaces this integration relies on, in one place.

ZHA's helpers are not a stable public API; the harness tests pin their behaviour, so an
upgrade that changes them fails the tests rather than the user's shades.
"""

import os
from pathlib import Path

from homeassistant.components.zha.const import CONF_CUSTOM_QUIRKS_PATH
from homeassistant.components.zha.helpers import (
    SIGNAL_ADD_ENTITIES,
    ZHAGatewayProxy,
    get_zha_data,
    get_zha_gateway_proxy,
)
from homeassistant.core import HomeAssistant, callback
import zha.quirks

from .const import QUIRK_ID, SHADE_MANUFACTURER, SHADE_MODEL

__all__ = [
    "SIGNAL_ADD_ENTITIES",
    "ZHAGatewayProxy",
    "async_custom_quirks_path",
    "async_gateway",
    "zha_quirks_provide_quirk",
]


@callback
def async_gateway(hass: HomeAssistant) -> ZHAGatewayProxy | None:
    """Return ZHA's gateway, or None while ZHA is not loaded (or is reloading)."""
    try:
        return get_zha_gateway_proxy(hass)
    except ValueError:
        # ZHA's own signal for "no gateway object exists".
        return None


@callback
def async_custom_quirks_path(hass: HomeAssistant) -> Path | None:
    """Return ZHA's YAML ``custom_quirks_path`` as an absolute path, or None if unset.

    ZHA keeps its YAML in ``hass.data`` for the whole run and hands this value to the
    quirk loader at each setup of its entry; a ZHA reload does not re-read it. ZHA
    resolves a relative value against the working directory, not the config folder:
    ``cv.isdir`` checks it with ``os.path.isdir`` after ``expanduser`` (and stores the
    expanded value), ``zhaquirks.setup`` walks ``pathlib.Path(value)``, and Python's
    path finder records every module's file as ``os.path.abspath`` of it. Resolve it the
    same way, so the folder written to and the quirks' source files compare alike.
    """
    value = get_zha_data(hass).yaml_config.get(CONF_CUSTOM_QUIRKS_PATH)
    if value is None:
        return None
    return Path(os.path.abspath(os.path.expanduser(value)))


def zha_quirks_provide_quirk(custom_quirks_path: Path | None) -> bool:
    """Return whether U is in ZHA's quirk registry from outside ``custom_quirks_path``.

    Reads the quirk registry ZHA has loaded: an entry for exactly the WM25/L-Z, with no
    filter and no firmware bounds (so ZHA would apply it to every unit), that was not
    loaded from ``custom_quirks_path`` (judged as ZHA's own purge of custom quirks
    judges it), and whose quirk definition declares U's quirk ID. The integration's own
    file in ``custom_quirks_path`` always wins over such an entry, so the device cannot
    tell; the registry can. Nothing is imported or called, and no name is consulted.
    The answer only ever adds a note; it never deletes a file.
    """
    return any(
        (SHADE_MANUFACTURER, SHADE_MODEL) in entry.device_match.applies_to
        and _unrestricted(entry.device_match)
        and not _from_custom_quirks_path(entry, custom_quirks_path)
        and _declares_quirk_id(entry)
        for entry in zha.quirks.DEVICE_REGISTRY
    )


def _unrestricted(device_match: zha.quirks.DeviceMatch) -> bool:
    """Return whether ZHA applies a match to every unit of its model."""
    return (
        not device_match.filters
        and device_match.firmware_version_min is None
        and device_match.firmware_version_max is None
    )


def _from_custom_quirks_path(
    entry: zha.quirks.QuirkRegistryEntry, custom_quirks_path: Path | None
) -> bool:
    """Return whether ZHA loaded ``entry`` from ``custom_quirks_path``."""
    if custom_quirks_path is None or entry.source is None or entry.source.file is None:
        return False
    # Both sides absolute, as the path finder records source files.
    return Path(os.path.abspath(entry.source.file)).is_relative_to(
        os.path.abspath(custom_quirks_path)
    )


def _declares_quirk_id(entry: zha.quirks.QuirkRegistryEntry) -> bool:
    """Return whether a registry entry's quirk definition exposes U's quirk ID.

    A quirks v2 entry carries its definition on its ZHA device factory
    (``QuirkV2Factory.quirk_definition``); anything else has none and answers False.
    """
    definition = getattr(entry.zha_device_factory, "quirk_definition", None)
    return any(
        getattr(feature, "feature", None) == QUIRK_ID
        for feature in getattr(definition, "exposes_features", ())
    )
