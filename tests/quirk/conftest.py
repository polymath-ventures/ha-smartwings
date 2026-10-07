"""Fixtures for the SmartWings quirk's own tests: zigpy's real request path, no Home Assistant.

The quirk file is loaded by path (``quirk/`` is never on the import path) inside a snapshot
of ZHA's quirk registry, so its registration lasts for one test only. Shades come from a
seeded zigpy database and are resolved through ZHA's registry, so each test gets the
quirk's real WindowCovering cluster on a real zigpy device. Every frame is captured at the
radio and decoded; a simulated motor answers, and the loop runs in virtual time.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Iterator
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest
import zha.quirks
import zigpy.exceptions
import zigpy.types as t
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import WindowCovering

from tests.zha_harness import (
    SHADE_IEEE,
    SHADE_NWK,
    HarnessApp,
    MotorSim,
    VirtualClock,
    seed_database,
)

QUIRK_FILE = (
    Path(__file__).parents[2] / "quirk" / "zhaquirks" / "smartwings" / "wm25lz.py"
)
QUIRK_MODULE = "smartwings_wm25lz_under_test"

# A second shade, for tests of independence between shades.
OTHER_IEEE = t.EUI64.convert("60:83:da:ff:fe:a0:00:03")
OTHER_NWK = t.NWK(0x5A20)

INITIAL_LIFT = 40
# Real time passes while virtual time is frozen (the test's own CPU work); this is the
# most of it a bound may absorb. Waits are all virtual, so it never hides a real wait.
JITTER_S = 0.25

LIFT = WindowCovering.AttributeDefs.current_position_lift_percentage
READ = ("read", LIFT.name)


def load_quirk() -> ModuleType:
    """Execute the quirk file as a fresh module, registering its quirk."""
    spec = importlib.util.spec_from_file_location(QUIRK_MODULE, QUIRK_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[QUIRK_MODULE] = module
    loaded = False
    try:
        spec.loader.exec_module(module)
        loaded = True
    finally:
        if not loaded:
            sys.modules.pop(QUIRK_MODULE, None)
    return module


@pytest.fixture
def wm25lz() -> Iterator[ModuleType]:
    """Load the quirk module, registered with ZHA's resolver for this test only."""
    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        try:
            yield load_quirk()
        finally:
            sys.modules.pop(QUIRK_MODULE, None)


@pytest.fixture
async def clock() -> AsyncIterator[VirtualClock]:
    """Install a virtual clock on the test's event loop."""
    virtual = VirtualClock(asyncio.get_running_loop())
    virtual.install()
    yield virtual
    virtual.uninstall()


def new_motor() -> MotorSim:
    """Return a healthy motor at the seeded lift.

    Like the real units, raw down_close lowers it; the vendor quirk's swap assumes the
    reverse.
    """
    return MotorSim(position=INITIAL_LIFT, rate_pct_per_s=5.0, reply_latency=1.0)


async def open_app(tmp_path: Path) -> HarnessApp:
    """Open a zigpy app holding two seeded shades, resolved through ZHA's quirk registry."""
    db = tmp_path / "zigbee.db"
    await seed_database(db, initial_lift=INITIAL_LIFT)
    await seed_database(db, initial_lift=INITIAL_LIFT, ieee=OTHER_IEEE, nwk=OTHER_NWK)
    application = await HarnessApp.new(
        HarnessApp.config_for(db),
        start_radio=False,
        device_resolver=zha.quirks.DEVICE_REGISTRY.resolve,
    )
    application.motors[SHADE_NWK] = new_motor()
    application.motors[OTHER_NWK] = new_motor()
    return application


@pytest.fixture
async def app(
    tmp_path: Path, wm25lz: ModuleType, clock: VirtualClock
) -> AsyncIterator[HarnessApp]:
    """Open a zigpy app holding two quirked shades, each answered by its own motor."""
    application = await open_app(tmp_path)
    yield application
    await application.shutdown()


@dataclass
class Shade:
    """The main shade under test, with everything a test drives or inspects."""

    app: HarnessApp
    clock: VirtualClock
    quirk: ModuleType
    motor: MotorSim
    covering: Any

    def wire(self, nwk: int = SHADE_NWK) -> list[tuple[Any, ...]]:
        """Return the decoded WindowCovering frames sent to a shade (see ``wire``)."""
        return wire(self.app, nwk)

    def commands(self, nwk: int = SHADE_NWK) -> list[tuple[Any, ...]]:
        """Return only the command frames (not reads) sent to a shade."""
        return [frame for frame in self.wire(nwk) if frame != READ]

    async def outcome(
        self, awaitable: Awaitable[Any], *, within: float
    ) -> tuple[Any, float]:
        """Run in virtual time (see ``outcome``)."""
        return await outcome(self.clock, awaitable, within=within)


@pytest.fixture
def shade(app: HarnessApp, clock: VirtualClock, wm25lz: ModuleType) -> Shade:
    """Return the main shade at rest at INITIAL_LIFT, its lift restored to the cache."""
    assert app.motor is not None
    return Shade(app, clock, wm25lz, app.motor, covering_of(app, SHADE_IEEE))


def covering_of(app: HarnessApp, ieee: t.EUI64) -> Any:
    """Return a shade's WindowCovering cluster."""
    return app.get_device(ieee).endpoints[1].window_covering


def wire(app: HarnessApp, nwk: int = SHADE_NWK) -> list[tuple[Any, ...]]:
    """Decode the WindowCovering frames sent to a shade, in order, dropped ones included.

    A command appears as ``(name, *args)``; a read of the lift as ``READ``.
    """
    decoded: list[tuple[Any, ...]] = []
    for frame in app.frames:
        if frame.dst_nwk != nwk or frame.cluster_id != WindowCovering.cluster_id:
            continue
        if frame.general:
            assert frame.command_id == foundation.GeneralCommand.Read_Attributes
            decoded.extend(
                ("read", WindowCovering.attributes[attribute_id].name)
                for attribute_id in frame.attribute_ids
            )
        else:
            name = WindowCovering.server_commands[frame.command_id].name
            decoded.append((name, *frame.args.values()))
    return decoded


def commands_on_wire(app: HarnessApp, nwk: int = SHADE_NWK) -> list[tuple[Any, ...]]:
    """Return only the command frames (not reads) sent to a shade."""
    return [frame for frame in wire(app, nwk) if frame != READ]


async def outcome(
    clock: VirtualClock, awaitable: Awaitable[Any], *, within: float
) -> tuple[Any, float]:
    """Run in virtual time; return the result or the Zigbee/timeout error, and the time.

    Fails the test if it takes longer than ``within`` virtual seconds.
    """

    async def capture() -> Any:
        try:
            return await awaitable
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            return exc

    return await clock.run(capture(), limit=within + JITTER_S)
