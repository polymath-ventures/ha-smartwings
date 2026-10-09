"""Real Home Assistant with the real ZHA integration, over the stub radio and motor model.

The shade comes from a seeded ``zigbee.db`` in the config dir, so ZHA loads it and resolves
its quirk through its own startup path, including ``custom_quirks_path``. The harness owns
its Home Assistant instances (the plugin's ``hass`` fixture cannot be restarted with its
registries intact): ``hass_storage`` holds registries and restore state across a restart,
and the motor, the database file and the clock live on the harness.

Each start is a new process for custom integrations: their modules are imported afresh,
and the quirks they registered are gone, so importing one registers its quirk again.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

import bellows.zigbee.application
from homeassistant import loader
from homeassistant.bootstrap import DATA_REGISTRIES_LOADED
from homeassistant.components.zha import const as zha_const
from homeassistant.components.zha.helpers import get_zha_gateway
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import DOMAIN as HA_DOMAIN, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    frame,
    issue_registry as ir,
    label_registry as lr,
    restore_state as rs,
    translation,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_test_home_assistant,
)
import zha.quirks
import zhaquirks.legacy
import zigpy.config
import zigpy.device

from .clock import VirtualClock
from .motor import MotorSim
from .radio import SHADE_IEEE, Frame, HarnessApp, seed_database

ZHA_ENTRY_ID = "01K0HARNESSZHA0000000000000"
_LIFECYCLE_TIMEOUT_S = 30


class ZhaHarness:
    """Home Assistant + ZHA + one simulated WM25/L-Z, restartable within a test."""

    def __init__(
        self, tmp_path: Path, hass_storage: dict[str, Any], motor: MotorSim
    ) -> None:
        """Lay out the config dir; call start() to boot."""
        self.config_dir = tmp_path / "config"
        self.custom_quirks_path = self.config_dir / "custom_zha_quirks"
        self.custom_quirks_path.mkdir(parents=True)
        # Whether ZHA's YAML sets custom_quirks_path; read at every start, as Home
        # Assistant reads configuration.yaml.
        self.custom_quirks_path_configured = True
        # ZHA's enable_quirks, likewise.
        self.quirks_enabled = True
        self.hass_storage = hass_storage
        self.motor = motor
        self.frames: list[Frame] = []
        self.clock = VirtualClock(asyncio.get_running_loop())
        self.hass: HomeAssistant | None = None
        self._hass_context: contextlib.AbstractAsyncContextManager | None = None
        self._exceptions: list[BaseException] = []
        self._patches = contextlib.ExitStack()
        # Config entries of other integrations, set up at every start.
        self.installed: dict[str, str] = {}
        # How many times ZHA's entry was set up since Home Assistant last started: one
        # for the start, one more for each reload.
        self.zha_starts = 0

    @property
    def zha_config(self) -> dict[str, Any]:
        """YAML for ZHA: quirks on, our quirk path, background radio work off."""
        config: dict[str, Any] = {
            zha_const.CONF_ENABLE_QUIRKS: self.quirks_enabled,
            zha_const.CONF_ZIGPY: {
                zigpy.config.CONF_WATCHDOG_ENABLED: False,
                zigpy.config.CONF_NWK_BACKUP_ENABLED: False,
                zigpy.config.CONF_TOPO_SCAN_ENABLED: False,
                zigpy.config.CONF_STARTUP_ENERGY_SCAN: False,
                zigpy.config.CONF_OTA: {zigpy.config.CONF_OTA_ENABLED: False},
            },
        }
        if self.custom_quirks_path_configured:
            config[zha_const.CONF_CUSTOM_QUIRKS_PATH] = str(self.custom_quirks_path)
        return config

    async def open(self, *, initial_lift: int) -> None:
        """Seed the database, take over the clock and the radio, and boot."""
        await seed_database(self.config_dir / "zigbee.db", initial_lift=initial_lift)
        harness = self

        class _App(HarnessApp):
            def __init__(self, config: dict[str, Any]) -> None:
                super().__init__(config)
                self.frames = harness.frames
                self.motor = harness.motor

        self._patches.enter_context(zha.quirks.DEVICE_REGISTRY.preserve_state())
        _forget_custom_integrations()
        self._patches.enter_context(
            patch.object(
                bellows.zigbee.application.ControllerApplication, "new", _App.new
            )
        )
        self._patches.enter_context(
            patch("homeassistant.components.zha.radio_manager.CONNECT_DELAY_S", 0)
        )
        self._patches.enter_context(
            patch(
                "homeassistant.components.zha.usb_device_from_path", return_value=None
            )
        )
        self.clock.install()
        await self.start()

    async def close(self) -> None:
        """Stop Home Assistant and undo every patch; re-raise any loop exception."""
        try:
            if self.hass is not None:
                await self.stop()
        finally:
            self.clock.uninstall()
            # Custom quirks live in two registries; purge both while their modules still
            # exist (zhaquirks asserts that), then forget the modules.
            zha.quirks.DEVICE_REGISTRY.purge_custom_quirks(self.custom_quirks_path)
            zhaquirks.legacy.DEVICE_REGISTRY.purge_custom_quirks(
                self.custom_quirks_path
            )
            for path in self.custom_quirks_path.glob("*.py"):
                sys.modules.pop(path.stem, None)
            self._patches.close()
        if self._exceptions:
            raise self._exceptions[0]

    async def start(self, *, zha_first: bool = False) -> None:
        """Boot Home Assistant over the persisted state and set up ZHA.

        The installed integrations are set up before ZHA, as Home Assistant's bootstrap
        usually does for one that does not depend on ZHA; ``zha_first`` reverses that.
        """
        self.zha_starts = 0
        self._hass_context = async_test_home_assistant(
            config_dir=str(self.config_dir), load_registries=False
        )
        hass = self.hass = await self._hass_context.__aenter__()
        hass.loop.set_exception_handler(
            lambda _loop, context: self._exceptions.append(
                context.get("exception") or RuntimeError(context["message"])
            )
        )
        frame.async_setup(hass)
        await translation.async_load_integrations(hass, {"homeassistant"})
        # Load the registries and restore state from hass_storage, as bootstrap does.
        dr.async_setup(hass)
        await asyncio.gather(
            ar.async_load(hass),
            cr.async_load(hass),
            dr.async_load(hass),
            er.async_load(hass),
            fr.async_load(hass),
            ir.async_load(hass),
            lr.async_load(hass),
            rs.async_load(hass),
        )
        hass.data[DATA_REGISTRIES_LOADED] = None
        # Let the loader find custom_components/smartwings (enable_custom_integrations).
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)

        zha_entry = MockConfigEntry(
            domain=zha_const.DOMAIN,
            entry_id=ZHA_ENTRY_ID,
            version=5,
            minor_version=2,
            data={
                zigpy.config.CONF_DEVICE: {
                    zigpy.config.CONF_DEVICE_PATH: "/dev/ttyUSB0",
                    zigpy.config.CONF_DEVICE_BAUDRATE: 115200,
                    zigpy.config.CONF_DEVICE_FLOW_CONTROL: "hardware",
                },
                zha_const.CONF_RADIO_TYPE: "ezsp",
            },
        )
        zha_entry.add_to_hass(hass)

        @callback
        def count_zha_setups() -> None:
            if zha_entry.state is ConfigEntryState.SETUP_IN_PROGRESS:
                self.zha_starts += 1

        zha_entry.async_on_state_change(count_zha_setups)
        # Startup and shutdown wait on threads (sqlite, executor), not on timers, so
        # they run in real time; virtual jumps are for commands and explicit advances.
        async with asyncio.timeout(_LIFECYCLE_TIMEOUT_S):
            assert await async_setup_component(hass, HA_DOMAIN, {})
            if not zha_first:
                await self._set_up_installed()
            assert await async_setup_component(
                hass, zha_const.DOMAIN, {zha_const.DOMAIN: self.zha_config}
            )
            await hass.async_block_till_done()
            if zha_first:
                await self._set_up_installed()

    async def install(self, domain: str, entry_id: str) -> None:
        """Add a config entry for ``domain`` now, with ZHA running, and at every start."""
        assert self.hass is not None
        self.installed[domain] = entry_id
        async with asyncio.timeout(_LIFECYCLE_TIMEOUT_S):
            await self._set_up(domain, entry_id)

    async def _set_up_installed(self) -> None:
        for domain, entry_id in self.installed.items():
            await self._set_up(domain, entry_id)

    async def _set_up(self, domain: str, entry_id: str) -> None:
        assert self.hass is not None
        MockConfigEntry(domain=domain, entry_id=entry_id, title=domain).add_to_hass(
            self.hass
        )
        # Home Assistant hands every integration the whole configuration.
        assert await async_setup_component(
            self.hass, domain, {zha_const.DOMAIN: self.zha_config}
        )
        await self.hass.async_block_till_done()

    async def stop(self) -> None:
        """Stop Home Assistant as a real shutdown does, flushing zigpy's DB and restore state."""
        assert self.hass is not None and self._hass_context is not None
        async with asyncio.timeout(_LIFECYCLE_TIMEOUT_S):
            await self.hass.async_stop(force=True)
        await self._hass_context.__aexit__(None, None, None)
        self.hass = None
        self._hass_context = None
        _forget_custom_integrations()

    async def restart(self, *, zha_first: bool = False) -> None:
        """Stop and start Home Assistant; the database, storage and motor carry over."""
        await self.stop()
        await self.start(zha_first=zha_first)

    async def reload_zha(self) -> None:
        """Reload ZHA's config entry, as the UI's reload does; the gateway restarts."""
        assert self.hass is not None
        async with asyncio.timeout(_LIFECYCLE_TIMEOUT_S):
            assert await self.hass.config_entries.async_reload(ZHA_ENTRY_ID)
            await self.hass.async_block_till_done()

    async def run(self, awaitable: Any) -> Any:
        """Await something in virtual time and return its result."""
        result, _ = await self.clock.run(awaitable)
        return result

    async def call(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        """Call a service and wait for it to finish, in virtual time."""
        assert self.hass is not None
        return await self.run(
            self.hass.services.async_call(domain, service, data, blocking=True)
        )

    @property
    def cover_entity_id(self) -> str:
        """The shade's real ZHA cover entity, found through the registries."""
        assert self.hass is not None
        device = dr.async_get(self.hass).async_get_device_by_identifier(
            (zha_const.DOMAIN, str(SHADE_IEEE)), ZHA_ENTRY_ID
        )
        assert device is not None, "ZHA did not create the shade's device"
        [entry] = [
            e
            for e in er.async_entries_for_device(er.async_get(self.hass), device.id)
            if e.domain == Platform.COVER
        ]
        return entry.entity_id

    def zigpy_device(self) -> zigpy.device.Device:
        """Return the shade's live (quirked) zigpy device inside ZHA's gateway."""
        assert self.hass is not None
        gateway = get_zha_gateway(self.hass)
        return gateway.application_controller.get_device(SHADE_IEEE)

    def cover_position(self) -> int | None:
        """Return the cover's current_position attribute (HA space: 0 closed, 100 open)."""
        assert self.hass is not None
        state = self.hass.states.get(self.cover_entity_id)
        assert state is not None
        return state.attributes.get("current_position")

    def shade_frames(self) -> list[Frame]:
        """Frames sent to the shade on the WindowCovering cluster, in order, dropped included."""
        return [f for f in self.frames if f.cluster_id == 0x0102]


def _forget_custom_integrations() -> None:
    """Forget the custom integrations' modules and their quirks, as a new process would."""
    for entry in list(zha.quirks.DEVICE_REGISTRY):
        if entry.source is not None and entry.source.module.startswith(
            "custom_components."
        ):
            zha.quirks.DEVICE_REGISTRY.remove(entry)
    for name in [name for name in sys.modules if name.startswith("custom_components.")]:
        del sys.modules[name]


@contextlib.asynccontextmanager
async def open_zha_harness(
    tmp_path: Path,
    hass_storage: dict[str, Any],
    *,
    initial_lift: int = 40,
    custom_quirks_path_configured: bool = True,
) -> AsyncIterator[ZhaHarness]:
    """Boot a harness for one test and always shut it down."""
    harness = ZhaHarness(
        tmp_path,
        hass_storage,
        MotorSim(position=initial_lift, rate_pct_per_s=5.0),
    )
    harness.custom_quirks_path_configured = custom_quirks_path_configured
    try:
        await harness.open(initial_lift=initial_lift)
        yield harness
    finally:
        await harness.close()
