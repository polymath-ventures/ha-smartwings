"""What the integration keeps in ZHA's quirk registry.

ZHA's purge of custom quirks leaves the integration's registration alone, even when
custom_quirks_path is a folder that holds custom_components.
"""

from pathlib import Path

import pytest
import zha.quirks

from custom_components.smartwings.zha_gateway import load_quirk

ROOT = Path(__file__).parents[1]


def registered(entry: zha.quirks.QuirkRegistryEntry) -> bool:
    """Return whether ``entry`` itself is in ZHA's quirk registry."""
    return any(candidate is entry for candidate in zha.quirks.DEVICE_REGISTRY)


@pytest.mark.parametrize(
    "folder", [ROOT, ROOT / "custom_components"], ids=["config", "custom_components"]
)
def test_purging_a_folder_above_the_integration_keeps_the_quirk(folder: Path) -> None:
    """custom_quirks_path set to a folder holding the integration: the quirk stays."""
    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        entry = load_quirk()
        assert registered(entry)

        zha.quirks.DEVICE_REGISTRY.purge_custom_quirks(folder)

        assert registered(entry)
