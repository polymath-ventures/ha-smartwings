"""Shared test setup.

Import this repository's custom_components package before any hass fixture runs. Home
Assistant's loader imports `custom_components` from its config dir only when the name is
not already imported; the test plugin's config dir carries its own package, which would
otherwise shadow ours. Tests that need the integration request `enable_custom_integrations`.
"""

import pytest
import zhaquirks

import custom_components  # noqa: F401
from tests.smartwings_helpers import shadow
from tests.zha_harness import open_zha_harness


@pytest.fixture(scope="session", autouse=True)
def load_vendor_quirks() -> None:
    """Register zhaquirks' quirks once, before any test snapshots the quirk registry.

    v1 quirks register only when their module is first imported. A harness restores the
    registry it found when it closes, so the quirks must already be in it then, or every
    later test would see an unquirked shade (Home Assistant core's ZHA tests do the same).
    """
    zhaquirks.setup()


@pytest.fixture
async def zha_harness(tmp_path, hass_storage):
    """Boot real Home Assistant and real ZHA over a simulated WM25/L-Z at lift 40."""
    async with open_zha_harness(tmp_path, hass_storage) as harness:
        yield harness


@pytest.fixture
async def zha_harness_shadowed(tmp_path, hass_storage):
    """Boot the harness with another quirk for the WM25/L-Z in custom_quirks_path.

    ZHA loads custom quirks last whenever it sets up, so that quirk always takes
    precedence: the shade never gets the SmartWings quirk.
    """
    async with open_zha_harness(tmp_path, hass_storage) as harness:
        shadow(harness)
        await harness.restart()
        yield harness
