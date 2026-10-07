"""The ZHA surfaces this integration relies on, in one place.

ZHA's helpers and quirk registry are not a stable public API; the harness tests pin their
behaviour, so an upgrade that changes them fails the tests rather than the user's shades.

ZHA's resolver takes, for a device, the first matching entry in ``zha.quirks.
DEVICE_REGISTRY``, and every registration goes in front. ``QuirkBuilder.add_to_registry``
registers at once, but zha-quirks' own v1 quirks (the vendor quirk for the WM25/L-Z among
them) reach the registry only when ``zhaquirks.setup()`` drains them. So the quirk is
registered after that drain, and put in front again whenever the integration sets up.
"""

import contextlib
import dataclasses
import importlib

from homeassistant.components.zha.helpers import (
    SIGNAL_ADD_ENTITIES,
    ZHAGatewayProxy,
    get_zha_gateway_proxy,
)
from homeassistant.core import HomeAssistant, callback
from zha.quirks import DEVICE_REGISTRY, QuirkRegistryEntry
import zhaquirks

from .const import QUIRK_ID

__all__ = [
    "SIGNAL_ADD_ENTITIES",
    "QuirkRegistryEntry",
    "ZHAGatewayProxy",
    "async_gateway",
    "is_registered",
    "load_quirk",
    "put_first",
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


def zha_quirks_provide_quirk() -> bool:
    """Return whether zha-quirks itself registers a quirk exposing the quirk ID.

    Only entries from the ``zhaquirks`` package count: a custom quirk is not part of
    Home Assistant, and this integration's quirk comes from ``custom_components``.
    """
    return any(
        entry.source is not None
        and entry.source.module.startswith("zhaquirks.")
        and _declares_quirk_id(entry)
        for entry in DEVICE_REGISTRY
    )


def load_quirk() -> QuirkRegistryEntry:
    """Import the quirk after zha-quirks' own quirks; return its registry entry.

    Blocking: it imports every zha-quirks module. The entry is left first in ZHA's
    registry, unless zha-quirks provides the quirk itself; then it is left out.
    """
    # Drain zha-quirks' v1 quirks now, so a later drain cannot put the vendor quirk in
    # front of this one. ZHA runs the same call when it sets up; it is idempotent.
    zhaquirks.setup()
    entry: QuirkRegistryEntry = importlib.import_module(
        f"{__package__}.quirk"
    ).QUIRK_ENTRY
    remove(entry)
    # Registered without a source file, so ZHA's purge of custom_quirks_path never
    # removes it, even when that folder holds custom_components. ZHA reads only the
    # source's module and label.
    pinned = dataclasses.replace(
        entry, source=dataclasses.replace(entry.source, file=None)
    )
    if not zha_quirks_provide_quirk():
        put_first(pinned)
    return pinned


def put_first(entry: QuirkRegistryEntry) -> None:
    """Make ``entry`` the first one ZHA's resolver tries for its model."""
    remove(entry)
    DEVICE_REGISTRY.register(entry)


def remove(entry: QuirkRegistryEntry) -> None:
    """Take ``entry`` out of ZHA's quirk registry, if it is there."""
    with contextlib.suppress(ValueError):
        DEVICE_REGISTRY.remove(entry)


def is_registered(entry: QuirkRegistryEntry) -> bool:
    """Return whether ``entry`` itself is in ZHA's quirk registry."""
    return any(registered is entry for registered in DEVICE_REGISTRY)


def _declares_quirk_id(entry: QuirkRegistryEntry) -> bool:
    """Return whether a registry entry's quirk definition exposes the quirk ID.

    A quirks v2 entry carries its definition on its ZHA device factory
    (``QuirkV2Factory.quirk_definition``); anything else has none and answers False.
    """
    definition = getattr(entry.zha_device_factory, "quirk_definition", None)
    return any(
        getattr(feature, "feature", None) == QUIRK_ID
        for feature in getattr(definition, "exposes_features", ())
    )
