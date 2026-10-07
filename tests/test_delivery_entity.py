"""Command delivery seen from the cover entity: real Home Assistant, real ZHA."""

from collections.abc import AsyncIterator
import logging
import sys

from homeassistant.exceptions import HomeAssistantError
import pytest
from zigpy.zcl.clusters.closures import WindowCovering

from tests.smartwings_helpers import supply_quirk
from tests.zha_harness import ZhaHarness, open_zha_harness

COMMANDS = WindowCovering.ServerCommandDefs


@pytest.fixture
async def harness(tmp_path, hass_storage) -> AsyncIterator[ZhaHarness]:
    """Boot the harness with the quirk supplied through custom_quirks_path."""
    async with open_zha_harness(tmp_path, hass_storage) as booted:
        await supply_quirk(booted)
        await booted.restart()
        booted.frames.clear()
        yield booted


def commands_sent(harness: ZhaHarness) -> list[int]:
    """Return the ids of the WindowCovering commands sent to the shade (reads excluded)."""
    return [f.command_id for f in harness.shade_frames() if not f.general]


async def test_one_close_with_a_lost_first_frame_is_one_action(harness) -> None:
    """One cover.close_cover call: two frames on the wire and no error."""
    harness.motor.drop_next(1)
    quirk = sys.modules[
        type(harness.zigpy_device().endpoints[1].window_covering).__module__
    ]

    _, elapsed = await harness.clock.run(
        harness.hass.services.async_call(
            "cover",
            "close_cover",
            {"entity_id": harness.cover_entity_id},
            blocking=True,
        )
    )

    # zigpy's own retry would also land a second frame, but only after its 28 s reply
    # timeout; the quirk's re-send comes well inside T_EXEC.
    assert elapsed < quirk.T_EXEC
    assert commands_sent(harness) == [COMMANDS.down_close.id] * 2
    assert harness.hass.states.get(harness.cover_entity_id).state == "closing"


async def test_a_lift_restored_after_a_restart_is_no_baseline(harness) -> None:
    """An ignored first frame after a restart is re-sent, whatever the restored lift.

    The shade is read at lift 40, then its remote moves it to 20 while
    Home Assistant is down, so zigpy restores 40. Against that, the shade standing at 20
    would look like travel toward an open's 0 and the frame would never be re-sent.
    With no baseline, the read at the estimated arrival judges it.
    """
    await harness.call(
        "homeassistant", "update_entity", {"entity_id": harness.cover_entity_id}
    )
    await harness.stop()
    harness.motor.set_position(20)
    await harness.start()
    harness.frames.clear()
    harness.motor.ignore_next(1)

    await harness.call("cover", "open_cover", {"entity_id": harness.cover_entity_id})
    await harness.clock.advance(200)

    assert commands_sent(harness) == [COMMANDS.up_open.id] * 2
    assert round(harness.motor.position_at(harness.clock.time())) == 0
    assert harness.hass.states.get(harness.cover_entity_id).state == "open"


def record_states(harness: ZhaHarness) -> list[str]:
    """Collect every state the cover entity publishes from now on."""
    states: list[str] = []

    def on_change(event) -> None:
        if event.data["entity_id"] == harness.cover_entity_id:
            states.append(event.data["new_state"].state)

    harness.hass.bus.async_listen("state_changed", on_change)
    return states


async def test_a_close_whose_frames_are_lost_fails_through_zha_and_never_animates(
    harness,
) -> None:
    """Both frames lost on the air: ZHA's own failure path, no moving state.

    Delivery gives up by returning a FAILURE Default Response, which ZHA treats as any
    failed command: it clears its transition target and raises its standard error.
    """
    harness.motor.drop_next(10**6)
    states = record_states(harness)

    with pytest.raises(
        HomeAssistantError, match=r"^Failed to close cover: <Status.FAILURE: 1>$"
    ):
        await harness.call(
            "cover", "close_cover", {"entity_id": harness.cover_entity_id}
        )
    harness.motor.drop_next(0)
    await harness.clock.advance(200)

    assert commands_sent(harness) == [COMMANDS.down_close.id] * 2
    assert harness.hass.states.get(harness.cover_entity_id).state == "open"
    assert not {"opening", "closing"} & set(states), states


async def test_a_close_that_never_moves_shows_closing_then_where_it_is(
    harness, caplog
) -> None:
    """A stuck shade: the call succeeds, as the radio accepted the frame.

    ZHA shows closing, as for any cover. After the travel time the readback sees no
    travel and re-sends once; its reads then show the shade still open, with no error
    after the call has returned.
    """
    await refresh(harness)
    harness.motor.ignore_commands = True
    states = record_states(harness)

    await harness.call("cover", "close_cover", {"entity_id": harness.cover_entity_id})
    await harness.clock.advance(400)

    assert states[0] == "closing"
    assert commands_sent(harness) == [COMMANDS.down_close.id] * 2
    assert harness.hass.states.get(harness.cover_entity_id).state == "open"


# --- The firmware's double reply and the commands it mangles ---------------------------

ORDERS = ["success-first", "unsup-first"]


async def refresh(harness: ZhaHarness) -> None:
    """Read the shade, as a user's refresh does, so delivery has a baseline."""
    await harness.call(
        "homeassistant", "update_entity", {"entity_id": harness.cover_entity_id}
    )


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize(
    ("service", "data", "state"),
    [
        ("open_cover", {}, "opening"),
        ("close_cover", {}, "closing"),
        ("set_cover_position", {"position": 20}, "closing"),
    ],
    ids=["open", "close", "go-to"],
)
async def test_a_movement_succeeds_whichever_reply_wins(
    harness, order, service, data, state
) -> None:
    """The firmware's 0x81 after SUCCESS raises nothing in ZHA's cover.

    ZHA's cover raises on any status but SUCCESS; both replies mean the radio took
    the frame, so the quirk answers SUCCESS whichever reply zigpy matched.
    """
    await refresh(harness)
    harness.motor.double_reply = order

    await harness.call("cover", service, {"entity_id": harness.cover_entity_id, **data})
    await harness.clock.advance(1)  # the second reply lands

    assert len(commands_sent(harness)) == 1  # the 0x81 caused no re-send
    assert harness.hass.states.get(harness.cover_entity_id).state == state


@pytest.mark.parametrize("order", ORDERS)
async def test_a_close_without_a_baseline_succeeds_whichever_reply_wins(
    harness, order
) -> None:
    """With no baseline (just restarted), the close is sent once and raises nothing."""
    harness.motor.double_reply = order

    await harness.call("cover", "close_cover", {"entity_id": harness.cover_entity_id})
    await harness.clock.advance(1)  # the second reply lands

    assert commands_sent(harness) == [COMMANDS.down_close.id]
    assert harness.hass.states.get(harness.cover_entity_id).state == "closing"


@pytest.mark.parametrize(
    ("command", "params"),
    [
        (COMMANDS.go_to_lift_value, {"lift_value": 1000}),
        (COMMANDS.go_to_tilt_value, {"tilt_value": 1000}),
        (COMMANDS.go_to_tilt_percentage, {"percentage_tilt_value": 30}),
    ],
    ids=["go_to_lift_value", "go_to_tilt_value", "go_to_tilt_percentage"],
)
async def test_a_mangled_command_from_zha_never_reaches_the_air(
    harness, command, params, caplog
) -> None:
    """ZHA's cluster command service gets ZHA's unsupported-command error; no frame.

    The refusal is the quirk's guard, not some other UNSUP_CLUSTER_COMMAND: the quirk
    logs it, once, from the cluster ZHA called.
    """
    caplog.set_level(logging.DEBUG)
    covering = harness.zigpy_device().endpoints[1].window_covering
    quirk_logger = sys.modules[type(covering).__module__]._LOGGER.name
    with pytest.raises(Exception, match="UNSUP_CLUSTER_COMMAND"):
        await harness.call(
            "zha",
            "issue_zigbee_cluster_command",
            {
                "ieee": str(harness.zigpy_device().ieee),
                "endpoint_id": 1,
                "cluster_id": WindowCovering.cluster_id,
                "cluster_type": "in",
                "command": command.id,
                "command_type": "server",
                "params": params,
            },
        )
    await harness.clock.advance(10)

    assert harness.shade_frames() == []
    refusals = [
        record.getMessage()
        for record in caplog.records
        if record.name == quirk_logger and "refused, not sent" in record.getMessage()
    ]
    assert refusals == [
        f"{harness.zigpy_device().ieee}: {command.name} refused, not sent: "
        "the radio sends the motor a malformed frame"
    ]
