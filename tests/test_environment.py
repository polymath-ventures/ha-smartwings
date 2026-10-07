"""The pinned environment can load the real ZHA integration (issue #2)."""

import importlib


def test_real_zha_integration_imports() -> None:
    """The real ZHA component imports, so tests need not stub it with MockModule."""
    zha = importlib.import_module("homeassistant.components.zha")

    assert zha.DOMAIN == "zha"
