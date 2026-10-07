"""What the integration reads from, and keeps in, ZHA's quirk registry.

Whether zha-quirks (the package Home Assistant pins) holds the quirk, by its quirk ID; and
that ZHA's purge of custom quirks leaves the integration's registration alone.
"""

from collections.abc import Iterator
import contextlib
import importlib.util
from pathlib import Path
import sys

import pytest
import zha.quirks

from custom_components.smartwings.zha_gateway import (
    is_registered,
    load_quirk,
    zha_quirks_provide_quirk,
)
from tests.quirk.conftest import QUIRK_FILE

SOURCE = QUIRK_FILE.read_text()
ROOT = Path(__file__).parents[1]


@contextlib.contextmanager
def registered(source: str, folder: Path, module: str) -> Iterator[None]:
    """Register ``source`` as module ``module`` in ZHA's registry inside the block."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "wm25lz.py"
    path.write_text(source)
    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        spec = importlib.util.spec_from_file_location(module, path)
        assert spec is not None and spec.loader is not None
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[module] = loaded
        try:
            spec.loader.exec_module(loaded)
            yield
        finally:
            sys.modules.pop(module, None)


def replaced(source: str, old: str, new: str) -> str:
    """Return ``source`` with ``old`` replaced; fail if it is not there."""
    assert old in source, old
    return source.replace(old, new)


# --- Whether zha-quirks provides the quirk ---------------------------------------------


def test_the_released_vendor_quirk_is_not_the_quirk() -> None:
    """zha-quirks as pinned holds only the vendor quirk, which declares no quirk ID."""
    assert any(
        ("Smartwings", "WM25/L-Z") in entry.device_match.applies_to
        for entry in zha.quirks.DEVICE_REGISTRY
    )

    assert zha_quirks_provide_quirk() is False


def test_the_quirk_in_zha_quirks_is_upstream(tmp_path: Path) -> None:
    """A zha-quirks module registering the quirk: zha-quirks provides it."""
    with registered(SOURCE, tmp_path, "zhaquirks.smartwings_upstream_test"):
        assert zha_quirks_provide_quirk() is True


def test_a_custom_quirk_is_not_upstream(tmp_path: Path) -> None:
    """The same quirk loaded as a custom quirk is not part of Home Assistant."""
    with registered(SOURCE, tmp_path, "wm25lz"):
        assert zha_quirks_provide_quirk() is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("    .exposes_feature(QUIRK_ID)\n", ""),
        (
            'QUIRK_ID: Final = "smartwings.wm25lz"',
            'QUIRK_ID: Final = "smartwings.other"',
        ),
    ],
    ids=["no-quirk-id", "other-quirk-id"],
)
def test_a_near_miss_is_not_the_quirk(tmp_path: Path, old: str, new: str) -> None:
    """A zha-quirks quirk without the quirk ID is not the quirk."""
    source = replaced(SOURCE, old, new)
    with registered(source, tmp_path, "zhaquirks.smartwings_upstream_test"):
        assert zha_quirks_provide_quirk() is False


# --- ZHA's purge of custom quirks -------------------------------------------------------


@pytest.mark.parametrize(
    "folder", [ROOT, ROOT / "custom_components"], ids=["config", "custom_components"]
)
def test_purging_a_folder_above_the_integration_keeps_the_quirk(folder: Path) -> None:
    """custom_quirks_path set to a folder holding the integration: the quirk stays."""
    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        entry = load_quirk()
        assert is_registered(entry)

        zha.quirks.DEVICE_REGISTRY.purge_custom_quirks(folder)

        assert is_registered(entry)
