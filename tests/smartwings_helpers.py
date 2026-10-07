"""Helpers for the integration's tests over the real Home Assistant and ZHA harness."""

from homeassistant.components.zha import const as zha_const
from homeassistant.components.zha.helpers import get_zha_gateway_proxy
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
import zigpy.device
import zigpy.endpoint
from zigpy.profiles import zha as zha_profile
import zigpy.types as t
from zigpy.zcl.clusters.general import Basic, OnOff

from custom_components.smartwings.const import DOMAIN, QUIRK_ID
from custom_components.smartwings.shades import ShadeDirectory
from tests.quirk.conftest import QUIRK_FILE
from tests.zha_harness import SHADE_IEEE, HarnessApp, ZhaHarness
from tests.zha_harness.harness import ZHA_ENTRY_ID
from tests.zha_harness.radio import SHADE_NODE_DESCRIPTOR

ENTRY_ID = "01K0SMARTWINGS000000000000"
ISSUE_ID = "quirk_not_loaded"
# Installed under its own name, as the README tells the user to.
QUIRK_NAME = QUIRK_FILE.name

# A device that is not a shade, for discovery to pass over.
PLUG_IEEE = t.EUI64.convert("00:0d:6f:00:0a:bc:de:01")
PLUG_NWK = t.NWK(0x1234)


async def install(harness: ZhaHarness) -> ShadeDirectory:
    """Install the integration after ZHA, now and at every restart; return its shades."""
    await harness.install(DOMAIN, ENTRY_ID)
    return directory(harness)


async def install_with_quirk(harness: ZhaHarness) -> ShadeDirectory:
    """Supply the quirk, restart, then install the integration; return its shades.

    Frames sent so far are dropped.
    """
    await supply_quirk(harness)
    await harness.restart()
    shades = await install(harness)
    harness.frames.clear()
    return shades


def directory(harness: ZhaHarness) -> ShadeDirectory:
    """Return the loaded entry's shade directory."""
    entry = harness.hass.config_entries.async_get_entry(ENTRY_ID)
    assert entry is not None
    return entry.runtime_data


def zha_device(harness: ZhaHarness, ieee: t.EUI64) -> dr.DeviceEntry:
    """Return ZHA's device registry entry for ``ieee``."""
    device = dr.async_get(harness.hass).async_get_device_by_identifier(
        (zha_const.DOMAIN, str(ieee)), ZHA_ENTRY_ID
    )
    assert device is not None
    return device


def issue(harness: ZhaHarness) -> ir.IssueEntry | None:
    """Return the missing-quirk Repairs issue, if it is raised (active)."""
    raised = ir.async_get(harness.hass).async_get_issue(DOMAIN, ISSUE_ID)
    return raised if raised is not None and raised.active else None


def domain_issues(harness: ZhaHarness) -> list[str]:
    """Return the ids of every Repairs issue the integration has raised (active)."""
    return [
        issue_id
        for (domain, issue_id), raised in ir.async_get(harness.hass).issues.items()
        if domain == DOMAIN and raised.active
    ]


def record_issue_events(harness: ZhaHarness) -> list[str]:
    """Collect the actions of every change to the integration's Repairs issues."""
    actions: list[str] = []

    @callback
    def record(event) -> None:
        if event.data["domain"] == DOMAIN:
            actions.append(event.data["action"])

    harness.hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, record)
    return actions


def record_updates(shades: ShadeDirectory) -> list[dict[str, bool]]:
    """Collect, at each listener call, every shade's IEEE and whether U is active."""
    seen: list[dict[str, bool]] = []
    shades.add_listener(
        lambda: seen.append(
            {ieee: shade.quirk_active for ieee, shade in shades.shades.items()}
        )
    )
    return seen


def quirk_loaded(harness: ZhaHarness, ieee: t.EUI64 = SHADE_IEEE) -> bool:
    """Return whether ZHA's device for ``ieee`` was built with U (its quirk ID)."""
    proxy = get_zha_gateway_proxy(harness.hass).device_proxies[ieee]
    return QUIRK_ID in proxy.device.exposes_features


async def supply_quirk(harness: ZhaHarness) -> None:
    """Put this repository's quirk in custom_quirks_path, as the user installs it."""
    (harness.custom_quirks_path / QUIRK_NAME).write_text(QUIRK_FILE.read_text())


async def seed_plug(harness: ZhaHarness) -> None:
    """Add an interviewed non-SmartWings device to zigpy's database (HA stopped)."""
    app = await HarnessApp.new(
        HarnessApp.config_for(harness.config_dir / "zigbee.db"), start_radio=False
    )
    try:
        device = app.add_device(PLUG_IEEE, PLUG_NWK)
        device.node_desc = SHADE_NODE_DESCRIPTOR.replace(manufacturer_code=0x1234)
        endpoint = device.add_endpoint(1)
        endpoint.profile_id = zha_profile.PROFILE_ID
        endpoint.device_type = zha_profile.DeviceType.ON_OFF_PLUG_IN_UNIT
        endpoint.status = zigpy.endpoint.Status.ZDO_INIT
        endpoint.add_input_cluster(Basic.cluster_id)
        endpoint.add_input_cluster(OnOff.cluster_id)
        endpoint.basic.update_attribute(Basic.AttributeDefs.manufacturer.id, "Acme")
        endpoint.basic.update_attribute(Basic.AttributeDefs.model.id, "Plug")
        device.status = zigpy.device.Status.ENDPOINTS_INIT
        app.device_initialized(device)
    finally:
        await app.shutdown()


async def forget_in_database(harness: ZhaHarness, ieee: t.EUI64) -> None:
    """Delete a device from zigpy's database, as zigpy does (ZHA not running)."""
    app = await HarnessApp.new(
        HarnessApp.config_for(harness.config_dir / "zigbee.db"), start_radio=False
    )
    try:
        device = app.devices.pop(ieee)
        app.listener_event("device_removed", device)
    finally:
        await app.shutdown()
