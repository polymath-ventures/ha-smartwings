"""The shades ZHA knows about, and whether the quirk is active for each.

A shade is a ZHA device whose zigpy device identifies as the SmartWings WM25/L-Z. The
quirk is active when the ZHA device lists its quirk ID in ``exposes_features``. No ZHA or
zigpy object is kept between discoveries: a ZHA reload replaces them.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import QUIRK_ID, SHADE_MANUFACTURER, SHADE_MODEL
from .zha_gateway import async_gateway, resolved_by_zha_quirks


@dataclass(frozen=True, slots=True)
class Shade:
    """A shade as of the last discovery."""

    ieee: str
    device_id: str  # ZHA's device in the device registry
    name: str
    quirk_active: bool
    # Whether ZHA resolved the shade with a quirk from zha-quirks itself.
    from_zha_quirks: bool


class ShadeDirectory:
    """Track the shades in ZHA's gateway, and tell listeners when they change."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Create an empty directory; ``async_discover`` fills it."""
        self.hass = hass
        self.shades: dict[str, Shade] = {}
        self.gateway_available = False
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` after every discovery and every change to the shades."""
        self._listeners.append(listener)

    @callback
    def async_discover(self, *_: Any) -> None:
        """Rebuild the directory from ZHA's gateway as it is now."""
        if (found := async_find_shades(self.hass)) is None:
            self.async_gateway_lost()
            return
        self._async_replace(found, gateway_available=True, discovered=True)

    @callback
    def async_gateway_lost(self) -> None:
        """Mark every shade gateway-unavailable while ZHA is not loaded."""
        self._async_replace(self.shades, gateway_available=False)

    @callback
    def async_zha_state_changed(self, zha_entry: ConfigEntry) -> None:
        """Follow ZHA's entry: rediscover once loaded, else the gateway is lost."""
        if zha_entry.state is ConfigEntryState.LOADED:
            self.async_discover()
        else:
            self.async_gateway_lost()

    @callback
    def async_device_registry_updated(
        self, event: Event[dr.EventDeviceRegistryUpdatedData]
    ) -> None:
        """Drop a shade whose device was removed; follow a shade's device rename."""
        data = event.data
        tracked = [
            shade
            for shade in self.shades.values()
            if shade.device_id == data["device_id"]
        ]
        if not tracked:
            return
        shades = dict(self.shades)
        for shade in tracked:
            if data["action"] == "remove":
                del shades[shade.ieee]
            else:
                shades[shade.ieee] = replace(
                    shade,
                    name=_display_name(
                        dr.async_get(self.hass).async_get(shade.device_id), shade.ieee
                    ),
                )
        self._async_replace(shades, gateway_available=self.gateway_available)

    @callback
    def async_stop(self) -> None:
        """Forget every shade, without signalling (the entry is unloading)."""
        self.shades = {}
        self.gateway_available = False

    @callback
    def _async_replace(
        self,
        shades: dict[str, Shade],
        *,
        gateway_available: bool,
        discovered: bool = False,
    ) -> None:
        """Apply a new set of shades and ZHA's availability; tell the listeners.

        Listeners hear of every change and of every completed discovery, even one
        that changed nothing, so they can reconcile what they show with it.
        """
        changed = shades != self.shades or gateway_available != self.gateway_available
        self.shades = dict(shades)
        self.gateway_available = gateway_available
        if discovered or changed:
            for listener in self._listeners:
                listener()


@callback
def async_find_shades(hass: HomeAssistant) -> dict[str, Shade] | None:
    """Return the shades in ZHA's gateway as it is now, by IEEE; None while ZHA is down."""
    if (gateway := async_gateway(hass)) is None:
        return None
    device_registry = dr.async_get(hass)
    found: dict[str, Shade] = {}
    for ieee, proxy in gateway.device_proxies.items():
        zigpy_device = proxy.device.device
        if (zigpy_device.manufacturer, zigpy_device.model) != (
            SHADE_MANUFACTURER,
            SHADE_MODEL,
        ):
            continue
        found[str(ieee)] = Shade(
            ieee=str(ieee),
            device_id=proxy.device_id,
            name=_display_name(device_registry.async_get(proxy.device_id), str(ieee)),
            quirk_active=QUIRK_ID in proxy.device.exposes_features,
            from_zha_quirks=resolved_by_zha_quirks(zigpy_device),
        )
    return found


def _display_name(device: dr.DeviceEntry | None, ieee: str) -> str:
    """Return the name the user sees for a shade's device, or its IEEE if it has none."""
    if device is None:
        return ieee
    return device.name_by_user or device.name or ieee


@callback
def is_removal_or_rename(data: dr.EventDeviceRegistryUpdatedData) -> bool:
    """Return whether a device registry update removes or renames a device."""
    return data["action"] == "remove" or (
        data["action"] == "update"
        and not {"name", "name_by_user"}.isdisjoint(data["changes"])
    )
