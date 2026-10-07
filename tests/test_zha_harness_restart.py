"""Tests for restarting Home Assistant and reloading ZHA in the harness (issue #5, phase 4)."""

from collections.abc import Awaitable, Callable

from homeassistant.helpers import entity_registry as er
import pytest

from tests.zha_harness import ZhaHarness


def _restart(harness: ZhaHarness) -> Callable[[], Awaitable[None]]:
    return harness.restart


def _reload(harness: ZhaHarness) -> Callable[[], Awaitable[None]]:
    return harness.reload_zha


CYCLES = pytest.mark.parametrize(
    "cycle", [_restart, _reload], ids=["restart", "reload"]
)


@CYCLES
async def test_position_read_before_a_cycle_survives_it(
    zha_harness: ZhaHarness, cycle
) -> None:
    """A refreshed position is persisted by zigpy and shown after the cycle without a new read."""
    zha_harness.motor.set_position(70)  # moved with the remote; HA does not know yet
    await zha_harness.call(
        "homeassistant", "update_entity", {"entity_id": zha_harness.cover_entity_id}
    )
    assert zha_harness.cover_position() == 30

    zha_harness.motor.set_position(90)  # moved again; only a read would reveal it
    await cycle(zha_harness)()

    assert zha_harness.cover_position() == 30


@CYCLES
async def test_entity_registry_survives_a_cycle(zha_harness: ZhaHarness, cycle) -> None:
    """A user's entity-id rename is still there after the cycle."""
    registry = er.async_get(zha_harness.hass)
    registry.async_update_entity(
        zha_harness.cover_entity_id, new_entity_id="cover.office"
    )

    await cycle(zha_harness)()

    assert zha_harness.cover_entity_id == "cover.office"


async def test_restore_state_survives_a_restart(zha_harness: ZhaHarness) -> None:
    """The cover's last state is dumped at shutdown and loaded by the next instance."""
    entity_id = zha_harness.cover_entity_id

    await zha_harness.restart()

    saved = zha_harness.hass_storage["core.restore_state"]["data"]
    assert entity_id in {item["state"]["entity_id"] for item in saved}
