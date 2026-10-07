"""How the integration decides whether the quirk (U) is active for a shade (#11, #54).

U declares a quirk ID through ZHA's exposed features; ZHA lists it in the device's
``exposes_features``, and that is the only thing the integration reads. No class, module,
cluster or file name decides it (Part 3 §1c).
"""

import ast
import builtins
from collections.abc import Sequence
import importlib.abc
from pathlib import Path
import sys
from typing import Any

from homeassistant import config_entries
from homeassistant.components.zha.helpers import get_zha_gateway_proxy
import pytest
import zha.quirks
import zhaquirks.legacy

from custom_components.smartwings import const
from custom_components.smartwings.const import DOMAIN
from tests.smartwings_helpers import directory, install, quirk_loaded
from tests.zha_harness import SHADE_IEEE, ZhaHarness

ROOT = Path(__file__).parents[1]
QUIRK_SOURCE = ROOT / "quirk" / "zhaquirks" / "smartwings" / "wm25lz.py"
INTEGRATION_DIR = ROOT / "custom_components" / "smartwings"
SHADE = str(SHADE_IEEE)


def replaced(source: str, old: str, new: str) -> str:
    """Return ``source`` with every ``old`` replaced; fail if there is none."""
    assert old in source, old
    return source.replace(old, new)


async def active_with(harness: ZhaHarness, source: str) -> bool:
    """Supply ``source`` as the quirk, restart, install; return whether U is active."""
    (harness.custom_quirks_path / QUIRK_SOURCE.name).write_text(source)
    await harness.restart()
    shades = await install(harness)
    return shades.shades[SHADE].quirk_active


# --- The decision (§1c; #54) ------------------------------------------------------------


async def test_the_released_vendor_quirk_is_not_active(zha_harness) -> None:
    """With only zha-quirks' vendor quirk, U is not active."""
    shades = await install(zha_harness)

    assert type(zha_harness.zigpy_device().endpoints[1].window_covering).__name__ == (
        "InvertedWindowCoveringCluster"
    )
    assert shades.shades[SHADE].quirk_active is False
    assert not quirk_loaded(zha_harness)


async def test_the_quirk_is_active(zha_harness) -> None:
    """U from custom_quirks_path: ZHA lists its quirk ID, and U is active."""
    assert await active_with(zha_harness, QUIRK_SOURCE.read_text()) is True
    assert quirk_loaded(zha_harness)


async def test_the_quirk_without_its_id_is_not_active(zha_harness) -> None:
    """The same cluster classes without the quirk ID are not evidence of U (REV 7c)."""
    source = replaced(QUIRK_SOURCE.read_text(), "    .exposes_feature(QUIRK_ID)\n", "")

    assert await active_with(zha_harness, source) is False
    covering = zha_harness.zigpy_device().endpoints[1].window_covering
    assert type(covering).__name__ == "WM25LZWindowCovering"


async def test_the_id_decides_whatever_the_names(zha_harness) -> None:
    """Renaming the classes and the module changes nothing: only the ID counts."""
    source = QUIRK_SOURCE.read_text()
    for old, new in [
        ("WM25LZWindowCovering", "RenamedCovering"),
        ("RadioBudget", "RenamedBudget"),
    ]:
        source = replaced(source, old, new)
    (zha_harness.custom_quirks_path / "renamed_module.py").write_text(source)
    await zha_harness.restart()

    shades = await install(zha_harness)

    assert shades.shades[SHADE].quirk_active is True


async def test_another_id_is_not_active(zha_harness) -> None:
    """A quirk declaring a different ID is not U."""
    source = replaced(
        QUIRK_SOURCE.read_text(),
        'QUIRK_ID: Final = "smartwings.wm25lz"',
        'QUIRK_ID: Final = "smartwings.other"',
    )

    assert await active_with(zha_harness, source) is False


async def test_the_decision_follows_a_zha_reload(zha_harness) -> None:
    """Re-read from the device ZHA holds now: U supplied, ZHA reloaded, U active."""
    shades = await install(zha_harness)
    assert shades.shades[SHADE].quirk_active is False
    (zha_harness.custom_quirks_path / QUIRK_SOURCE.name).write_text(
        QUIRK_SOURCE.read_text()
    )

    await zha_harness.reload_zha()

    assert directory(zha_harness).shades[SHADE].quirk_active is True


async def test_an_unexpected_error_propagates(zha_harness, monkeypatch) -> None:
    """No catch-all: an error reading the device is neither active nor not (F13)."""
    shades = await install(zha_harness)
    device = get_zha_gateway_proxy(zha_harness.hass).device_proxies[SHADE_IEEE].device

    def broken(_self: Any) -> set[str]:
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(
        type(device), "exposes_features", property(broken), raising=False
    )

    with pytest.raises(RuntimeError, match="lookup failed"):
        shades.async_discover()


# --- The quirk ID is mirrored, never imported (§1c) -------------------------------------


def quirk_id_in_source() -> str:
    """Return the QUIRK_ID string U's source assigns."""
    for node in ast.walk(ast.parse(QUIRK_SOURCE.read_text())):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "QUIRK_ID"
        ):
            assert isinstance(node.value, ast.Constant)
            return node.value.value
    raise AssertionError("U declares no QUIRK_ID")


def test_the_integration_copy_of_the_quirk_id_matches() -> None:
    """I's copy of the quirk ID is U's (a test, not an import, keeps them equal)."""
    assert const.QUIRK_ID == quirk_id_in_source() == "smartwings.wm25lz"


def imported_modules(source: str) -> list[str]:
    """Return every module an ``import`` statement in ``source`` names."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            modules.append(base)
            modules.extend(f"{base}.{alias.name}" for alias in node.names)
    return modules


def imports_the_quirk(module: str) -> bool:
    """Return whether an import names U's code."""
    return (
        module.split(".")[:2] == ["zhaquirks", "smartwings"]
        or "wm25lz" in module
        or module.split(".", maxsplit=1)[0] == "quirk"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from zhaquirks.smartwings.wm25lz import X\n", True),
        ("import zhaquirks.smartwings\n", True),
        ("from zhaquirks import smartwings\n", True),
        ("from quirk.zhaquirks.smartwings import wm25lz\n", True),
        ("import zigpy.types as t\nfrom zhaquirks import LocalDataCluster\n", False),
    ],
)
def test_the_import_scan_finds_the_quirk(source, expected) -> None:
    """The scan below recognises each way of importing U (F14)."""
    assert any(map(imports_the_quirk, imported_modules(source))) is expected


def test_the_integration_never_imports_the_quirk() -> None:
    """I relies on the quirk ID only, never on U's code (§1c)."""
    sources = sorted(INTEGRATION_DIR.rglob("*.py"))
    assert INTEGRATION_DIR / "const.py" in sources

    offenders = {
        str(path.relative_to(ROOT)): module
        for path in sources
        for module in imported_modules(path.read_text())
        if imports_the_quirk(module)
    }

    assert offenders == {}


def quirk_registry_state() -> tuple:
    """Return everything a quirk registration would change."""
    registry = zha.quirks.DEVICE_REGISTRY
    return (
        {key: list(entries) for key, entries in registry._registry.items()},
        list(registry._wildcard_registry),
        list(zhaquirks.legacy.PENDING_LEGACY_QUIRKS),
    )


def names_a_quirk(module: str) -> bool:
    """Return whether a module name is U's or any zhaquirks quirk module."""
    return imports_the_quirk(module) or (
        module.startswith("zhaquirks.") and module != "zhaquirks.legacy"
    )


class ImportRecorder(importlib.abc.MetaPathFinder):
    """Record every module name looked up through the import system."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.names: list[str] = []

    def find_spec(self, fullname: str, path: Sequence[str] | None, target=None):
        """Record the name; let the real finders find it."""
        self.names.append(fullname)

    def record_statement(self, real_import: Any) -> Any:
        """Wrap ``__import__`` so import statements of loaded modules are seen too."""

        def recording_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0:
                self.names.append(name)
                self.names.extend(f"{name}.{item}" for item in fromlist or ())
            return real_import(name, globals, locals, fromlist, level)

        return recording_import


async def test_setup_imports_and_registers_no_quirk(
    zha_harness: ZhaHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting up the integration loads no quirk code and registers no quirk (§1c).

    The quirk modules ZHA already loaded, and the integration's own, are hidden for the
    setup: the integration is imported afresh, and any import of a quirk module, by
    statement or by importlib, reaches the recorder.
    """
    recorder = ImportRecorder()
    registries_before = quirk_registry_state()
    hidden = [
        name
        for name in sys.modules
        if names_a_quirk(name) or name.startswith("custom_components.smartwings")
    ]
    assert "zhaquirks.smartwings.wm25lz" in hidden
    for name in hidden:
        monkeypatch.delitem(sys.modules, name)
    # Importing the config flow afresh registers its handler class globally.
    handler_before = config_entries.HANDLERS.get(DOMAIN)
    monkeypatch.setattr(builtins, "__import__", recorder.record_statement(__import__))
    monkeypatch.setattr(sys, "meta_path", [recorder, *sys.meta_path])
    try:
        await install(zha_harness)
        loaded_quirks = [name for name in sys.modules if names_a_quirk(name)]
    finally:
        monkeypatch.undo()
        # Forget the integration modules and flow handler the fresh import added beside
        # the restored ones, so a later test does not mix the two (two ShadeStatus
        # enums, say).
        for name in [n for n in sys.modules if n.startswith("custom_components.")]:
            if name.startswith("custom_components.smartwings") and name not in hidden:
                del sys.modules[name]
        if handler_before is None:
            config_entries.HANDLERS.pop(DOMAIN, None)
        else:
            config_entries.HANDLERS[DOMAIN] = handler_before

    # The recorder saw the integration's import and its import statements.
    assert "custom_components.smartwings" in recorder.names
    assert "homeassistant.components.zha.helpers" in recorder.names
    assert [name for name in recorder.names if names_a_quirk(name)] == []
    assert loaded_quirks == []
    assert quirk_registry_state() == registries_before
