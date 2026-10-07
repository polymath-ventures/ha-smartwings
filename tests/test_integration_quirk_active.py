"""How the integration decides whether the quirk is active for a shade.

The quirk declares a quirk ID through ZHA's exposed features; ZHA lists it in the
device's ``exposes_features``, and that is the only thing the integration reads.
"""

from pathlib import Path

from tests.smartwings_helpers import install
from tests.zha_harness import SHADE_IEEE, ZhaHarness

ROOT = Path(__file__).parents[1]
QUIRK_SOURCE = ROOT / "quirk" / "zhaquirks" / "smartwings" / "wm25lz.py"
SHADE = str(SHADE_IEEE)


def replaced(source: str, old: str, new: str) -> str:
    """Return ``source`` with every ``old`` replaced; fail if there is none."""
    assert old in source, old
    return source.replace(old, new)


async def active_with(harness: ZhaHarness, source: str) -> bool:
    """Supply ``source`` as the quirk, restart, install; return whether the quirk is active."""
    (harness.custom_quirks_path / QUIRK_SOURCE.name).write_text(source)
    await harness.restart()
    shades = await install(harness)
    return shades.shades[SHADE].quirk_active


async def test_the_quirk_without_its_id_is_not_active(zha_harness) -> None:
    """The same cluster classes without the quirk ID are not evidence of the quirk."""
    source = replaced(QUIRK_SOURCE.read_text(), "    .exposes_feature(QUIRK_ID)\n", "")

    assert await active_with(zha_harness, source) is False
    covering = zha_harness.zigpy_device().endpoints[1].window_covering
    assert type(covering).__name__ == "WM25LZWindowCovering"


async def test_the_id_decides_whatever_the_names(zha_harness) -> None:
    """Renaming the classes and the module changes nothing: only the ID counts."""
    source = QUIRK_SOURCE.read_text()
    for old, new in [
        ("WM25LZWindowCovering", "RenamedCovering"),
    ]:
        source = replaced(source, old, new)
    (zha_harness.custom_quirks_path / "renamed_module.py").write_text(source)
    await zha_harness.restart()

    shades = await install(zha_harness)

    assert shades.shades[SHADE].quirk_active is True


async def test_another_id_is_not_active(zha_harness) -> None:
    """A quirk declaring a different ID is not this quirk."""
    source = replaced(
        QUIRK_SOURCE.read_text(),
        'QUIRK_ID: Final = "smartwings.wm25lz"',
        'QUIRK_ID: Final = "smartwings.other"',
    )

    assert await active_with(zha_harness, source) is False
