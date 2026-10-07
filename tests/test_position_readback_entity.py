"""The final position after travel, seen from the cover entity: real HA, real ZHA.

After every command the quirk waits for the shade's report at the end of travel, and
reads the lift if none comes, so the cover shows where the shade stopped without a
refresh. A move made with the remote shows after Home Assistant's stock refresh,
``homeassistant.update_entity``; nothing polls.
"""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import logging

from homeassistant.exceptions import HomeAssistantError
import pytest
from zigpy.zcl.clusters.closures import WindowCovering

from tests.test_cover_entity import cover, cover_state, install_quirk, motor_lift
from tests.zha_harness import ZhaHarness, open_zha_harness

COMMANDS = WindowCovering.ServerCommandDefs
# A full travel in 60 s, inside the measured 30-70 s.
FULL_TRAVEL_60_S = 100 / 60
# Longer than any tracking: arrival plus confirmation, within TRACK_MAX_DURATION.
AFTER_TRACKING_S = 120


@pytest.fixture
async def harness(tmp_path, hass_storage) -> AsyncIterator[ZhaHarness]:
    """Boot with the quirk installed and the shade fully open (HA position 100).

    The shade is read once after startup, so delivery has a baseline.
    """
    async with open_zha_harness(tmp_path, hass_storage, initial_lift=0) as booted:
        await install_quirk(booted)
        booted.motor.rate_pct_per_s = FULL_TRAVEL_60_S
        await refresh(booted)
        booted.frames.clear()
        yield booted


def record_positions(harness: ZhaHarness) -> list[tuple[str, int | None]]:
    """Collect every (state, current_position) the cover publishes from now on."""
    published: list[tuple[str, int | None]] = []

    def on_change(event) -> None:
        if event.data["entity_id"] == harness.cover_entity_id:
            new = event.data["new_state"]
            published.append((new.state, new.attributes.get("current_position")))

    harness.hass.bus.async_listen("state_changed", on_change)
    return published


def reads(harness: ZhaHarness) -> int:
    """Return the number of read attempts sent to the shade so far."""
    return sum(frame.general for frame in harness.shade_frames())


async def refresh(harness: ZhaHarness) -> None:
    """Refresh the cover with Home Assistant's stock service, as a user's refresh does."""
    await harness.call(
        "homeassistant", "update_entity", {"entity_id": harness.cover_entity_id}
    )


async def test_a_close_shows_closed_once_the_shade_stops(harness) -> None:
    """From HA 100, close_cover over a 60 s travel ends closed at 0 with no refresh.

    Delivery reads nothing; the shade's report at the end of travel is the position,
    so no read is needed at all.
    """
    published = record_positions(harness)

    await cover(harness, "close_cover")
    early = harness.cover_position()
    await harness.clock.advance(AFTER_TRACKING_S)

    assert early == 100  # nothing read during travel
    assert motor_lift(harness) == 100
    assert cover_state(harness) == ("closed", 0)
    assert published[-1] == ("closed", 0)
    assert reads(harness) == 0


async def test_without_a_report_one_read_at_the_arrival_shows_the_end(
    harness,
) -> None:
    """No report reaches the hub: one read at the estimated arrival shows closed."""
    harness.motor.reports = False

    await cover(harness, "close_cover")
    await harness.clock.advance(AFTER_TRACKING_S)

    assert cover_state(harness) == ("closed", 0)
    assert reads(harness) == 1


async def test_set_position_ends_at_the_real_position(harness) -> None:
    """set_cover_position(40) ends open at 40 after the arrival read.

    Before that read the card may show a stale mid-travel position: the accepted
    cosmetic cost of reading sparsely, so only the end is asserted.
    """
    await cover(harness, "set_cover_position", position=40)
    await harness.clock.advance(AFTER_TRACKING_S)

    assert motor_lift(harness) == 60
    assert cover_state(harness) == ("open", 40)


async def test_a_stall_short_of_the_target_shows_where_it_stopped(harness) -> None:
    """A close that stalls at lift 45 settles there: open at 55."""
    harness.motor.stall_at = 45

    await cover(harness, "close_cover")
    await harness.clock.advance(AFTER_TRACKING_S)

    assert motor_lift(harness) == 45
    assert cover_state(harness) == ("open", 55)


async def test_a_failed_close_still_shows_a_late_start(harness) -> None:
    """Both replies are lost, but the motor starts late: tracking shows it closed."""
    harness.motor.start_delay = 30
    harness.motor.fail_next_sends(2, delivered=True)

    with pytest.raises(HomeAssistantError, match="Failed to close cover"):
        await cover(harness, "close_cover")
    assert cover_state(harness) == ("open", 100)
    await harness.clock.advance(AFTER_TRACKING_S)

    assert motor_lift(harness) == 100
    assert cover_state(harness) == ("closed", 0)


async def test_a_new_command_supersedes_tracking(harness) -> None:
    """An open during a close's tracking is sent at once and the cover ends open."""
    await cover(harness, "close_cover")
    await harness.clock.advance(10)
    harness.frames.clear()

    _, elapsed = await harness.clock.run(
        harness.hass.services.async_call(
            "cover", "open_cover", {"entity_id": harness.cover_entity_id}, True
        )
    )
    await harness.clock.advance(AFTER_TRACKING_S)

    assert harness.shade_frames()[0].command_id == COMMANDS.up_open.id
    assert elapsed < 25
    assert motor_lift(harness) == 0
    assert cover_state(harness) == ("open", 100)


async def test_a_remote_move_shows_after_a_refresh(harness) -> None:
    """The remote moves the shade; update_entity reads it and the cover follows."""
    harness.motor.set_position(70)
    await harness.clock.advance(60)
    assert harness.cover_position() == 100

    await refresh(harness)
    await harness.clock.advance(10)

    assert cover_state(harness) == ("open", 30)


async def test_an_idle_hour_sends_nothing(harness) -> None:
    """No command and no refresh: no frame reaches the shade in an hour."""
    await harness.clock.advance(3600)

    assert harness.shade_frames() == []


async def test_a_refresh_after_a_restart_reads_the_position(harness) -> None:
    """After a full restart, update_entity reads the shade's real position."""
    harness.motor.set_position(70)

    await harness.restart()
    harness.frames.clear()
    await refresh(harness)
    await harness.clock.advance(10)

    assert cover_state(harness) == ("open", 30)
    assert reads(harness) == 1


async def test_a_first_close_after_a_restart_landing_short_ends_quietly(
    harness, caplog
) -> None:
    """After a restart nothing has been read, and the close settles one point short.

    The cover shows where it stopped, with no WARNING.
    """
    await harness.restart()
    harness.motor.stall_at = 99
    caplog.set_level(logging.DEBUG)

    await cover(harness, "close_cover")
    await harness.clock.advance(AFTER_TRACKING_S)

    assert motor_lift(harness) == 99
    assert cover_state(harness) == ("open", 1)
    assert not [
        record
        for record in caplog.records
        if "wm25lz" in record.name and record.levelno >= logging.WARNING
    ]


async def test_a_restart_during_tracking_leaves_nothing_behind(harness) -> None:
    """Home Assistant stops mid-tracking: the tracker is cancelled, nothing lingers."""
    await cover(harness, "close_cover")
    await harness.clock.advance(10)

    await harness.restart()
    harness.frames.clear()
    await harness.clock.advance(AFTER_TRACKING_S)

    assert harness.shade_frames() == []
    await refresh(harness)
    await harness.clock.advance(10)
    assert cover_state(harness) == ("closed", 0)


async def test_a_zha_reload_during_tracking_ends_it(harness) -> None:
    """A ZHA reload mid-tracking ends the old tracker; the new cluster works.

    The tracker that would have read the end is gone, so the cache still holds the
    early look, lift 10 or so, while the shade closes to 100. That look is no baseline
    for the next command, which succeeds without a refresh first.
    """
    await cover(harness, "close_cover")
    await harness.clock.advance(10)

    await harness.reload_zha()
    harness.frames.clear()
    await harness.clock.advance(AFTER_TRACKING_S)
    assert harness.shade_frames() == []
    assert motor_lift(harness) == 100

    await cover(harness, "open_cover")
    await harness.clock.advance(AFTER_TRACKING_S)
    assert cover_state(harness) == ("open", 100)


async def test_a_zha_reload_during_delivery_starts_no_tracking(harness) -> None:
    """A ZHA reload while a close is being delivered leaves no tracker behind (1c)."""
    close = asyncio.ensure_future(
        harness.hass.services.async_call(
            "cover", "close_cover", {"entity_id": harness.cover_entity_id}, True
        )
    )
    await harness.clock.advance(1)

    await harness.reload_zha()
    with contextlib.suppress(HomeAssistantError):
        await harness.run(close)
    await harness.clock.advance(0)
    sent = len(harness.shade_frames())
    await harness.clock.advance(AFTER_TRACKING_S + 300)

    assert len(harness.shade_frames()) == sent
    assert not [
        task
        for task in asyncio.all_tasks()
        if "position readback" in task.get_name() and not task.done()
    ]
