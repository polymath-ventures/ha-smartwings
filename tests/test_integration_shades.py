"""Shade discovery and quirk activity through ZHA: real Home Assistant, real ZHA."""

import asyncio

from homeassistant.components.zha.helpers import get_zha_gateway, get_zha_gateway_proxy
from homeassistant.helpers import device_registry as dr

from tests.quirk.conftest import OTHER_IEEE, OTHER_NWK
from tests.smartwings_helpers import (
    ENTRY_ID,
    PLUG_IEEE,
    directory,
    install,
    record_updates,
    seed_plug,
    unshadow,
    zha_device,
)
from tests.zha_harness import SHADE_IEEE, MotorSim, ZhaHarness, add_shade
from tests.zha_harness.harness import ZHA_ENTRY_ID

SHADE = str(SHADE_IEEE)
OTHER = str(OTHER_IEEE)

# --- Discovery ------------------------------------------------------------------------


async def test_only_the_shade_is_tracked_on_zhas_own_device(
    zha_harness: ZhaHarness,
) -> None:
    """One WM25/L-Z and one other device: one shade, on ZHA's device, no new device."""
    await zha_harness.stop()
    await seed_plug(zha_harness)
    await zha_harness.start()
    hass = zha_harness.hass
    assert PLUG_IEEE in get_zha_gateway_proxy(hass).device_proxies
    devices_before = {device.id for device in dr.async_get(hass).devices}

    shades = await install(zha_harness)

    assert set(shades.shades) == {SHADE}
    shade = shades.shades[SHADE]
    assert shade.device_id == zha_device(zha_harness, SHADE_IEEE).id
    assert {device.id for device in dr.async_get(hass).devices} == devices_before
    assert dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID) == []


async def test_a_shade_paired_after_setup_is_tracked(zha_harness: ZhaHarness) -> None:
    """A join makes ZHA add entities; the new shade is tracked without a reload."""
    shades = await install(zha_harness)
    tracked = asyncio.Event()
    shades.add_listener(lambda: OTHER in shades.shades and tracked.set())
    app = get_zha_gateway(zha_harness.hass).application_controller
    app.motors[OTHER_NWK] = MotorSim(position=40, rate_pct_per_s=5.0)

    # A join: zigpy announces the interviewed device, then ZHA configures it (the
    # unanswered binds time out in virtual time) and adds its entities.
    app.device_initialized(
        add_shade(app, initial_lift=40, ieee=OTHER_IEEE, nwk=OTHER_NWK)
    )
    await zha_harness.run(tracked.wait())
    await zha_harness.hass.async_block_till_done()

    assert set(shades.shades) == {SHADE, OTHER}
    assert shades.shades[OTHER].device_id == zha_device(zha_harness, OTHER_IEEE).id
    assert directory(zha_harness) is shades


async def test_a_removed_shade_is_dropped(zha_harness: ZhaHarness) -> None:
    """Removing the shade's device from ZHA stops tracking it."""
    shades = await install(zha_harness)
    updates = record_updates(shades)
    assert SHADE in shades.shades

    await zha_harness.call("zha", "remove", {"ieee": SHADE})
    # Let the removal's debounced registry work finish.
    await zha_harness.clock.advance(60)
    await zha_harness.hass.async_block_till_done()

    assert shades.shades == {}
    assert updates and updates[-1] == {}


# --- Quirk activity, by the quirk ID --------------------------------------------------


async def test_status_is_not_active_with_another_quirk(
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """With another quirk in front of it, the shade's quirk is not active."""
    shades = await install(zha_harness_shadowed)

    assert shades.shades[SHADE].quirk_active is False


async def test_status_follows_the_quirk_across_a_zha_reload(
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """The other quirk deleted, then ZHA reloaded: listeners hear of it, it is active."""
    zha_harness = zha_harness_shadowed
    shades = await install(zha_harness)
    updates = record_updates(shades)

    unshadow(zha_harness)
    await zha_harness.reload_zha()

    assert shades.shades[SHADE].quirk_active is True
    assert updates[-1] == {SHADE: True}


async def test_status_is_gateway_unavailable_while_zha_is_down(
    zha_harness_shadowed: ZhaHarness,
) -> None:
    """While ZHA is unloaded the shade is kept, and ZHA is recorded as unavailable."""
    zha_harness = zha_harness_shadowed
    shades = await install(zha_harness)
    hass = zha_harness.hass

    assert await hass.config_entries.async_unload(ZHA_ENTRY_ID)
    await hass.async_block_till_done()

    assert shades.gateway_available is False
    assert set(shades.shades) == {SHADE}

    unshadow(zha_harness)
    assert await hass.config_entries.async_setup(ZHA_ENTRY_ID)
    await hass.async_block_till_done()

    assert shades.gateway_available is True
    assert shades.shades[SHADE].quirk_active is True


async def test_status_with_the_quirk_after_a_restart(zha_harness: ZhaHarness) -> None:
    """Integration installed, restart: the shade's quirk is active from setup."""
    await install(zha_harness)

    await zha_harness.restart()

    assert directory(zha_harness).shades[SHADE].quirk_active is True
