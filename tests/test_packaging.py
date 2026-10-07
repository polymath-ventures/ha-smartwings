"""The quirk ships as one file, and the README installs exactly that file (issue #14).

Until the quirk is released in zha-quirks, ``quirk/zhaquirks/smartwings/wm25lz.py`` goes
into the folder ZHA's ``custom_quirks_path`` names (Part 3 §5f): the integration installs
its byte-identical bundled copy there (#18), or the user copies it by hand. These tests
hold that file to what that needs: it imports nothing but zigpy, zhaquirks and the
standard library, it loads alone from such a folder, every test of the quirk exercises
that same file, every tracked copy is identical, and the README points at it. The
end-to-end proof that ZHA picks it up at startup, under the name the README gives, is
``test_integration_repairs.test_setup_order_with_the_quirk_in_custom_quirks_path``,
``test_quirk_install`` and every harness test that calls ``supply_quirk``.
"""

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
import yaml
import zha.quirks
import zhaquirks
import zhaquirks.legacy

from custom_components.smartwings import installer
from tests import smartwings_helpers, test_integration_quirk_active
from tests.quirk.conftest import QUIRK_FILE

ROOT = Path(__file__).parents[1]
SHIPPED = Path("quirk/zhaquirks/smartwings/wm25lz.py")
# The copy the integration ships as data and installs into custom_quirks_path (#18).
BUNDLED = Path("custom_components/smartwings/bundled_quirk/wm25lz.py.txt")
README = ROOT / "README.md"
SERVICES = ROOT / "custom_components" / "smartwings" / "services.yaml"
STRINGS = ROOT / "custom_components" / "smartwings" / "strings.json"
ALLOWED_PACKAGES = {"zigpy", "zhaquirks"}
# Top-level directories of tracked files that are not shipped.
NOT_SHIPPED = {"tests"}
QUIRK_IDENTITY = re.compile(
    r"""QuirkBuilder\(\s*["']Smartwings["']\s*,\s*["']WM25/L-Z["']\s*\)"""
)
# The name the harness tests once installed the quirk under, before the README's.
OLD_INSTALL_NAME = "smartwings_" + SHIPPED.name


def imported_roots(source: str) -> list[str]:
    """Return the top-level package of every import in ``source``, nested ones included."""
    roots = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.append("." if node.level else node.module.split(".")[0])
    return roots


def readme_yaml() -> list[object]:
    """Return every YAML code block in the README, parsed."""
    blocks = re.findall(r"```yaml\n(.*?)```", README.read_text(), flags=re.DOTALL)
    return [yaml.safe_load(_dedent(block)) for block in blocks]


def _dedent(block: str) -> str:
    """Strip the indentation a block takes inside a numbered list."""
    lines = block.splitlines()
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return "\n".join(line[indent:] for line in lines)


def _walk(node: object):
    """Yield every mapping inside a parsed YAML document."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


# --- The shipped file ------------------------------------------------------------------


def test_the_suite_tests_the_shipped_file() -> None:
    """The quirk's tests, the quirk-ID test and the harness all use the shipped file."""
    assert QUIRK_FILE.resolve() == (ROOT / SHIPPED).resolve()
    assert (
        test_integration_quirk_active.QUIRK_SOURCE.resolve()
        == (ROOT / SHIPPED).resolve()
    )
    # The harness installs it under the name the README tells the user to keep, and no
    # test installs it under the old one.
    assert SHIPPED.name == smartwings_helpers.QUIRK_NAME
    assert [
        path
        for path in (ROOT / "tests").rglob("*.py")
        if OLD_INSTALL_NAME in path.read_text()
    ] == []


def test_the_quirk_imports_only_zigpy_zhaquirks_and_the_standard_library() -> None:
    """No Home Assistant, no relative import: the file stands alone (Part 3 §3b)."""
    roots = imported_roots(QUIRK_FILE.read_text())

    assert roots, "the import scan found nothing"
    foreign = {
        root
        for root in roots
        if root not in ALLOWED_PACKAGES and root not in sys.stdlib_module_names
    }
    assert foreign == set()
    assert {"zigpy", "zhaquirks"} <= set(roots)


@pytest.mark.parametrize(
    ("source", "foreign"),
    [
        ("import homeassistant.const\n", "homeassistant"),
        ("from custom_components.smartwings import const\n", "custom_components"),
        (
            "def f():\n    from homeassistant.core import HomeAssistant\n",
            "homeassistant",
        ),
        ("from . import sibling\n", "."),
    ],
)
def test_the_import_scan_catches_a_foreign_import(source: str, foreign: str) -> None:
    """The scan sees top-level, nested and relative imports alike."""
    roots = imported_roots(source)

    assert foreign in roots
    assert foreign not in ALLOWED_PACKAGES
    assert foreign not in sys.stdlib_module_names


def test_the_file_alone_loads_from_a_custom_quirks_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Copied alone into an empty folder, ZHA's loader registers it for the WM25/L-Z."""
    custom_quirks_path = tmp_path / "custom_zha_quirks"
    custom_quirks_path.mkdir()
    shutil.copy(QUIRK_FILE, custom_quirks_path / SHIPPED.name)

    with zha.quirks.DEVICE_REGISTRY.preserve_state():
        try:
            zhaquirks.setup(custom_quirks_path=str(custom_quirks_path))
            loaded = [
                entry
                for entry in zha.quirks.DEVICE_REGISTRY
                if entry.source is not None
                and entry.source.file is not None
                and Path(entry.source.file).is_relative_to(custom_quirks_path)
            ]
        finally:
            zha.quirks.DEVICE_REGISTRY.purge_custom_quirks(custom_quirks_path)
            zhaquirks.legacy.DEVICE_REGISTRY.purge_custom_quirks(custom_quirks_path)
            sys.modules.pop(SHIPPED.stem, None)

    assert "Unexpected exception importing custom quirk" not in caplog.text
    assert [set(entry.device_match.applies_to) for entry in loaded] == [
        {("Smartwings", "WM25/L-Z")}
    ]


def tracked_quirk_files() -> list[Path]:
    """Return every tracked file that is, or names itself as, the WM25/L-Z quirk.

    Only files git tracks count, so installed packages (zha-quirks' own ``wm25lz.py`` in
    a virtualenv) never do. A file of any suffix named like the quirk counts, so the
    copy the integration bundles as data does too. The retired implementation and the
    tests' own variants and spikes are not shipped.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split("\0")
    found = []
    for name in filter(None, listed):
        path = ROOT / name
        if Path(name).parts[0] in NOT_SHIPPED or not path.is_file():
            continue
        if "wm25lz" in path.name or (
            path.suffix == ".py" and QUIRK_IDENTITY.search(path.read_text())
        ):
            found.append(path)
    return found


def test_every_copy_of_the_quirk_is_the_shipped_file() -> None:
    """Any other tracked copy of the quirk is byte-identical, so none can drift."""
    copies = tracked_quirk_files()

    # The identity test recognises the shipped file by its content, not only its name.
    assert QUIRK_IDENTITY.search(QUIRK_FILE.read_text())
    assert ROOT / SHIPPED in copies
    assert ROOT / BUNDLED in copies
    shipped = (ROOT / SHIPPED).read_bytes()
    assert [copy for copy in copies if copy.read_bytes() != shipped] == []


# --- The README ------------------------------------------------------------------------


def test_the_readme_installs_the_shipped_file() -> None:
    """The README's quirk path is the tested file, and its YAML sets custom_quirks_path."""
    paths = set(re.findall(r"`([^`]*wm25lz\.py)`", README.read_text()))
    configs = [
        block["zha"]["custom_quirks_path"]
        for block in readme_yaml()
        if isinstance(block, dict) and "custom_quirks_path" in block.get("zha", {})
    ]

    assert SHIPPED.as_posix() in paths
    assert (ROOT / SHIPPED).resolve() == QUIRK_FILE.resolve()
    assert len(configs) == 1
    assert configs[0]


def test_the_integration_has_no_actions() -> None:
    """No SmartWings action exists or is documented: "Stops at" is retired (#54)."""
    used = [
        mapping
        for document in readme_yaml()
        for mapping in _walk(document)
        if str(mapping.get("action", "")).startswith("smartwings.")
    ]

    assert used == []
    assert not SERVICES.exists()
    assert "services" not in json.loads(STRINGS.read_text())


def test_the_readme_names_the_folder_and_issues_the_integration_uses() -> None:
    """The README's folder is the installer's default; it names each install issue."""
    strings = json.loads(STRINGS.read_text())
    [config] = [
        block["zha"]["custom_quirks_path"]
        for block in readme_yaml()
        if isinstance(block, dict) and "custom_quirks_path" in block.get("zha", {})
    ]

    assert config == f"/config/{installer.DEFAULT_FOLDER}/"
    for issue_id in installer.ALL_ISSUES:
        assert strings["issues"][issue_id]["title"] in README.read_text(), issue_id
