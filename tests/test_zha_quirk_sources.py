"""What the integration reads from ZHA to install its quirk file.

ZHA's YAML ``custom_quirks_path``, and whether ZHA's quirk registry holds the quirk for
the WM25/L-Z, by its quirk ID, from outside that folder (the zha-quirks package).
"""

from collections.abc import Iterator
import contextlib
import importlib.util
from pathlib import Path
import sys

import pytest
import zha.quirks

from custom_components.smartwings.zha_gateway import (
    async_custom_quirks_path,
    zha_quirks_provide_quirk,
)
from tests.quirk.conftest import QUIRK_FILE
from tests.zha_harness import ZhaHarness, open_zha_harness

SOURCE = QUIRK_FILE.read_text()


@contextlib.contextmanager
def registered(source: str, folder: Path) -> Iterator[None]:
    """Register ``source``, loaded from ``folder``, in ZHA's registry inside the block."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "wm25lz.py"
    path.write_text(source)
    name = f"sources_variant_{folder.name}"
    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            yield
        finally:
            sys.modules.pop(name, None)


def replaced(source: str, old: str, new: str) -> str:
    """Return ``source`` with ``old`` replaced; fail if it is not there."""
    assert old in source, old
    return source.replace(old, new)


# --- custom_quirks_path ------------------------------------------------------------------


async def test_custom_quirks_path_comes_from_zha_yaml(zha_harness: ZhaHarness) -> None:
    """The folder ZHA was configured with, as ZHA holds it."""
    assert async_custom_quirks_path(zha_harness.hass) == zha_harness.custom_quirks_path


async def test_custom_quirks_path_unconfigured(tmp_path, hass_storage) -> None:
    """No custom_quirks_path in ZHA's YAML: none."""
    async with open_zha_harness(
        tmp_path, hass_storage, custom_quirks_path_configured=False
    ) as harness:
        assert async_custom_quirks_path(harness.hass) is None


# --- Whether zha-quirks provides the quirk ---------------------------------------------


def test_the_released_vendor_quirk_is_not_the_quirk(tmp_path: Path) -> None:
    """zha-quirks as pinned holds only the vendor quirk, which declares no quirk ID."""
    assert any(
        ("Smartwings", "WM25/L-Z") in entry.device_match.applies_to
        for entry in zha.quirks.DEVICE_REGISTRY
    )

    assert zha_quirks_provide_quirk(None) is False
    assert zha_quirks_provide_quirk(tmp_path) is False


def test_the_quirk_from_custom_quirks_path_is_not_upstream(tmp_path: Path) -> None:
    """Loaded from custom_quirks_path (the integration's own file): not zha-quirks."""
    custom = tmp_path / "custom_zha_quirks"
    with registered(SOURCE, custom):
        assert zha_quirks_provide_quirk(custom) is False


def test_the_quirk_from_elsewhere_is_upstream(tmp_path: Path) -> None:
    """Loaded from outside custom_quirks_path: zha-quirks provides it."""
    with registered(SOURCE, tmp_path / "site_packages"):
        assert zha_quirks_provide_quirk(tmp_path / "custom_zha_quirks") is True
        assert zha_quirks_provide_quirk(None) is True


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("    .exposes_feature(QUIRK_ID)\n", ""),
        (
            'QUIRK_ID: Final = "smartwings.wm25lz"',
            'QUIRK_ID: Final = "smartwings.other"',
        ),
        (
            'QuirkBuilder("Smartwings", "WM25/L-Z")',
            'QuirkBuilder("Smartwings", "WM25/L-Y")',
        ),
    ],
    ids=["no-quirk-id", "other-quirk-id", "model"],
)
def test_a_near_miss_is_not_the_quirk(tmp_path: Path, old: str, new: str) -> None:
    """The quirk ID and the model must both match."""
    with registered(replaced(SOURCE, old, new), tmp_path / "site_packages"):
        assert zha_quirks_provide_quirk(None) is False


@pytest.mark.parametrize(
    "restriction",
    [
        ".filter(lambda device: True)",
        ".firmware_version_filter(min_version=1)",
        ".firmware_version_filter(max_version=0x7FFFFFFF)",
    ],
    ids=["filter", "firmware-min", "firmware-max"],
)
def test_a_restricted_entry_is_not_taken_as_upstream(
    tmp_path: Path, restriction: str
) -> None:
    """An entry ZHA applies only to some WM25/L-Z units does not count (conservative)."""
    source = replaced(
        SOURCE,
        'QuirkBuilder("Smartwings", "WM25/L-Z")',
        f'QuirkBuilder("Smartwings", "WM25/L-Z"){restriction}',
    )

    with registered(source, tmp_path / "site_packages"):
        assert zha_quirks_provide_quirk(None) is False
