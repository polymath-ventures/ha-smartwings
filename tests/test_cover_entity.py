"""The shade card's controls end to end: real Home Assistant, real ZHA.

The motor stops every movement at the limits set with its remote and reports the lower
one as lift 100, so the quirk sends commands exactly as ZHA does: open is up_open, close
is down_close (no vendor swap), a position p is go_to_lift_percentage(100 - p). Stop
halts the motor, and the firmware's second reply to it shows no error.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from homeassistant.components.zha import const as zha_const
from homeassistant.components.zha.helpers import get_zha_gateway_proxy
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import PowerConfiguration

from custom_components.smartwings.const import QUIRK_ID
from tests.quirk.conftest import QUIRK_FILE
from tests.zha_harness import SHADE_IEEE, ZhaHarness, open_zha_harness, report_packet
from tests.zha_harness.harness import ZHA_ENTRY_ID

# Installed under its own name.
QUIRK_NAME = QUIRK_FILE.name
BATTERY = PowerConfiguration.AttributeDefs.battery_percentage_remaining
COMMANDS = WindowCovering.ServerCommandDefs
GO_TO = COMMANDS.go_to_lift_percentage.name


async def install_quirk(harness: ZhaHarness) -> None:
    """Supply the quirk through custom_quirks_path and restart, as a user does."""
    (harness.custom_quirks_path / QUIRK_NAME).write_text(QUIRK_FILE.read_text())
    await harness.restart()
    harness.frames.clear()


@pytest.fixture
async def stock(tmp_path, hass_storage) -> AsyncIterator[ZhaHarness]:
    """Boot the harness with only the released vendor quirk."""
    async with open_zha_harness(tmp_path, hass_storage) as booted:
        yield booted


@pytest.fixture
async def harness(stock) -> ZhaHarness:
    """Boot the harness with the quirk supplied through custom_quirks_path."""
    await install_quirk(stock)
    return stock


def wire(harness: ZhaHarness) -> list[tuple[Any, ...]]:
    """Decode the WindowCovering commands sent to the shade (reads excluded)."""
    return [
        (WindowCovering.server_commands[frame.command_id].name, *frame.args.values())
        for frame in harness.shade_frames()
        if not frame.general
    ]


def cover_state(harness: ZhaHarness) -> tuple[str, int | None]:
    """Return the cover's state and current_position (HA space)."""
    state = harness.hass.states.get(harness.cover_entity_id)
    assert state is not None
    return state.state, state.attributes.get("current_position")


async def cover(harness: ZhaHarness, service: str, **data: Any) -> None:
    """Call a cover service on the real ZHA cover entity."""
    await harness.call("cover", service, {"entity_id": harness.cover_entity_id, **data})


async def settle(harness: ZhaHarness) -> None:
    """Let the motor finish travelling and the quirk's readback end.

    The shade reports its position when travel ends, and ZHA settles the cover's
    state after its movement timeout; two minutes cover any travel and both.
    """
    await harness.clock.advance(120)
    await harness.hass.async_block_till_done()


def motor_lift(harness: ZhaHarness) -> int:
    """Return the simulated motor's lift now."""
    return round(harness.motor.position_at(asyncio.get_running_loop().time()))


def battery_entity_id(harness: ZhaHarness) -> str:
    """Return the shade's battery sensor."""
    device = dr.async_get(harness.hass).async_get_device_by_identifier(
        (zha_const.DOMAIN, str(SHADE_IEEE)), ZHA_ENTRY_ID
    )
    assert device is not None
    [entity_id] = [
        entry.entity_id
        for entry in er.async_entries_for_device(er.async_get(harness.hass), device.id)
        if entry.domain == "sensor"
        and harness.hass.states.get(entry.entity_id) is not None
        and harness.hass.states.get(entry.entity_id).attributes.get("device_class")
        == "battery"
    ]
    return entity_id


async def battery_after_report(harness: ZhaHarness, value: int) -> Any:
    """Deliver a real battery_percentage_remaining report; return the sensor's state."""
    gateway_app = harness.zigpy_device().application
    gateway_app.packet_received(
        report_packet(PowerConfiguration.cluster_id, BATTERY.id, value)
    )
    await harness.clock.advance(1)
    await harness.hass.async_block_till_done()
    return harness.hass.states.get(battery_entity_id(harness)).state


# --- One v2 quirk, superseding the vendor quirk ------------------------------------


async def test_the_v2_quirk_wins_and_keeps_the_vendor_battery_reading(stock) -> None:
    """The quirk replaces the vendor quirk, declares its ID, adds nothing, keeps the battery."""
    endpoint = stock.zigpy_device().endpoints[1]
    assert type(endpoint.window_covering).__name__ == "InvertedWindowCoveringCluster"
    clusters_before = set(endpoint.in_clusters)
    vendor_reading = await battery_after_report(stock, 42)

    await install_quirk(stock)
    await battery_after_report(stock, 21)  # a different value first, so the next shows
    ours = await battery_after_report(stock, 42)

    endpoint = stock.zigpy_device().endpoints[1]
    assert type(endpoint.window_covering).__name__ == "WM25LZWindowCovering"
    assert set(endpoint.in_clusters) == clusters_before
    zha_device = get_zha_gateway_proxy(stock.hass).device_proxies[SHADE_IEEE].device
    assert QUIRK_ID in zha_device.exposes_features
    assert ours == vendor_reading == "42.0"


@pytest.mark.parametrize("percent", [84, 100])
async def test_the_battery_shows_the_motors_whole_percent(harness, percent) -> None:
    """HA's battery sensor shows the motor's own percentage.

    The radio copies the motor's whole-percent byte into BatteryPercentageRemaining,
    which ZCL counts in half percent. The quirk keeps the vendor quirk's doubling, so a raw 84
    is cached as 168, and ZHA's battery sensor halves the cached value: 84 %.
    """
    await battery_after_report(harness, 1)  # a different value first, so the next shows

    shown = await battery_after_report(harness, percent)

    power = harness.zigpy_device().endpoints[1].power
    assert power.get(BATTERY.id) == 2 * percent
    assert shown == f"{percent}.0"


# --- Open, Close and the slider, as ZHA sends them --------------------------------------


async def test_open_is_up_open_and_ends_open(harness) -> None:
    """open_cover sends raw up_open (0x00), as ZHA does, and the card ends open."""
    await cover(harness, "open_cover")

    assert {
        (frame.command_id, tuple(frame.args.values()))
        for frame in harness.shade_frames()
        if not frame.general
    } == {(0x00, ())}
    await settle(harness)
    assert motor_lift(harness) == 0
    assert cover_state(harness) == ("open", 100)


async def test_close_is_an_unswapped_down_close_to_the_lower_limit(harness) -> None:
    """close_cover sends raw down_close (0x01), not the vendor swap, and ends closed.

    The motor stops at the lower limit set with its remote and reports it as lift 100;
    raw down_close lowers these units.
    """
    await cover(harness, "close_cover")

    commands = [frame for frame in harness.shade_frames() if not frame.general]
    assert commands
    assert {(frame.command_id, tuple(frame.args.values())) for frame in commands} == {
        (0x01, ())
    }
    await settle(harness)
    assert motor_lift(harness) == 100
    assert cover_state(harness) == ("closed", 0)


@pytest.mark.parametrize(("position", "lift"), [(0, 100), (50, 50), (100, 0), (73, 27)])
async def test_the_slider_reaches_every_position(harness, position, lift) -> None:
    """set_cover_position(p) is go_to_lift_percentage(100 - p), unscaled, and lands."""
    await cover(harness, "set_cover_position", position=position)

    assert set(wire(harness)) == {(GO_TO, lift)}
    await settle(harness)
    assert motor_lift(harness) == lift
    assert cover_state(harness) == ("closed" if position == 0 else "open", position)


# --- Stop ------------------------------------------------------------------------------


@pytest.mark.parametrize("reply", ["success-first", "unsup-first", "unsup-only", None])
async def test_stop_halts_the_shade_without_an_error(harness, reply) -> None:
    """stop_cover mid-travel: one Stop, no error whichever reply wins, card shows the halt.

    The motor halts on Stop and reports where it stopped. Its 0x81 is the
    firmware's second reply to a forwarded frame, so the quirk reports SUCCESS.
    """
    harness.motor.double_reply = reply
    await cover(harness, "set_cover_position", position=0)  # lift 40 -> 100
    await harness.clock.advance(4)  # 20 lift points in
    harness.frames.clear()

    await cover(harness, "stop_cover")
    await settle(harness)

    assert wire(harness) == [(COMMANDS.stop.name,)]
    halted = motor_lift(harness)
    assert 40 < halted < 100
    assert cover_state(harness) == ("open", 100 - halted)


@pytest.mark.parametrize("cycle", ["restart", "reload_zha"])
async def test_the_controls_work_after_a_cycle(harness, cycle) -> None:
    """After a restart or a ZHA reload, Close and Open still go out as ZHA sends them."""
    await getattr(harness, cycle)()
    harness.frames.clear()

    await cover(harness, "close_cover")
    await settle(harness)
    await cover(harness, "open_cover")
    await settle(harness)

    assert [name for name, *_ in wire(harness)] == [
        COMMANDS.down_close.name,
        COMMANDS.up_open.name,
    ]
    assert cover_state(harness) == ("open", 100)
