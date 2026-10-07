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
import zha.quirks
import zhaquirks

from .const import QUIRK_ID

__all__ = [
    "SIGNAL_ADD_ENTITIES",
    "ZHAGatewayProxy",
    "async_gateway",
    "register_quirk",
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
        for entry in zha.quirks.DEVICE_REGISTRY
    )


def register_quirk() -> tuple[zha.quirks.QuirkRegistryEntry, ...]:
    """Import the quirk, registering it in front of zha-quirks' quirks; return its entries.

    Blocking (it imports every zha-quirks module): run it at import. Registers nothing
    when zha-quirks provides the quirk itself.
    """
    # Drain zha-quirks' v1 quirks now, so a later drain cannot put the vendor quirk in
    # front of this one. ZHA runs the same call when it sets up; it is idempotent.
    zhaquirks.setup()
    if zha_quirks_provide_quirk():
        return ()
    before = {id(entry) for entry in zha.quirks.DEVICE_REGISTRY}
    importlib.import_module(f"{__package__}.quirk")
    added = [e for e in zha.quirks.DEVICE_REGISTRY if id(e) not in before]
    # Re-registered without a source file, so ZHA's purge of custom_quirks_path never
    # removes them, even when that folder holds custom_components. ZHA reads only the
    # source's module and label.
    pinned = tuple(
        dataclasses.replace(entry, source=dataclasses.replace(entry.source, file=None))
        if entry.source is not None
        else entry
        for entry in added
    )
    remove(tuple(added))
    put_first(pinned)
    return pinned


def put_first(entries: tuple[zha.quirks.QuirkRegistryEntry, ...]) -> None:
    """Make ``entries`` the first ones ZHA's resolver tries, in the order given."""
    remove(entries)
    for entry in reversed(entries):
        zha.quirks.DEVICE_REGISTRY.register(entry)


def remove(entries: tuple[zha.quirks.QuirkRegistryEntry, ...]) -> None:
    """Take ``entries`` out of ZHA's quirk registry, those that are there."""
    for entry in entries:
        with contextlib.suppress(ValueError):
            zha.quirks.DEVICE_REGISTRY.remove(entry)


def _declares_quirk_id(entry: zha.quirks.QuirkRegistryEntry) -> bool:
    """Return whether a registry entry's quirk definition exposes the quirk ID.

    A quirks v2 entry carries its definition on its ZHA device factory
    (``QuirkV2Factory.quirk_definition``); anything else has none and answers False.
    """
    definition = getattr(entry.zha_device_factory, "quirk_definition", None)
    return any(
        getattr(feature, "feature", None) == QUIRK_ID
        for feature in getattr(definition, "exposes_features", ())
    )
