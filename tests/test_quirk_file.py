"""The quirk file the integration ships, and how it recognises its own copy (issue #18).

The integration copies its bundled quirk into ZHA's ``custom_quirks_path``. A copy is its
own only when the file's first line is the marker, and an own copy is outdated when its
bytes differ from the bundled file's. These are the synchronous file operations, run in
Home Assistant's executor by the installer.
"""

from pathlib import Path
import tempfile
from typing import Any

import pytest

from custom_components.smartwings import bundle
from custom_components.smartwings.bundle import FileState
from tests.quirk.conftest import QUIRK_FILE

BUNDLED = QUIRK_FILE.read_bytes()


def test_the_bundled_file_is_the_quirk_source() -> None:
    """The integration ships the tested quirk file, byte for byte."""
    assert bundle.BUNDLED_FILE.read_bytes() == BUNDLED
    assert bundle.bundled_bytes() == BUNDLED


def test_the_bundled_file_cannot_be_imported() -> None:
    """It is data: no import machinery treats it as a module of the integration."""
    assert bundle.BUNDLED_FILE.suffix != ".py"
    assert QUIRK_FILE.name == bundle.FILE_NAME


def test_the_quirk_source_starts_with_the_marker() -> None:
    """The marker is the source's first line, so every copy carries it."""
    assert BUNDLED.decode().splitlines()[0] == bundle.MARKER
    assert bundle.MARKER.startswith("# ")


def test_an_absent_file(tmp_path: Path) -> None:
    """No file: absent."""
    assert bundle.inspect(tmp_path / "wm25lz.py", BUNDLED) is FileState.ABSENT


def test_an_identical_file_is_current(tmp_path: Path) -> None:
    """The bundled bytes: the integration's own, current."""
    target = tmp_path / "wm25lz.py"
    target.write_bytes(BUNDLED)

    assert bundle.inspect(target, BUNDLED) is FileState.CURRENT


def test_a_marked_file_that_differs_is_outdated(tmp_path: Path) -> None:
    """Marker on line 1, other content: the integration's own, outdated."""
    target = tmp_path / "wm25lz.py"
    target.write_text(f"{bundle.MARKER}\n# an older quirk\n")

    assert bundle.inspect(target, BUNDLED) is FileState.OUTDATED


@pytest.mark.parametrize(
    "content",
    [
        "# a quirk the user wrote\n",
        "",
        # The marker, but not as the first line.
        f'"""Docstring."""\n{bundle.MARKER}\n',
        # The first line differs in one character.
        f"{bundle.MARKER[:-1]}\n",
        f"{bundle.MARKER} \n",
        f" {bundle.MARKER}\n",
    ],
)
def test_an_unmarked_file_is_foreign(tmp_path: Path, content: str) -> None:
    """Anything without the exact marker as its first line is not the integration's."""
    target = tmp_path / "wm25lz.py"
    target.write_text(content)

    assert bundle.inspect(target, BUNDLED) is FileState.FOREIGN


def test_an_unmarked_copy_of_the_old_source_is_foreign(tmp_path: Path) -> None:
    """A hand copy of the quirk from before the marker existed is the user's."""
    target = tmp_path / "wm25lz.py"
    target.write_bytes(BUNDLED.split(b"\n", 1)[1])

    assert bundle.inspect(target, BUNDLED) is FileState.FOREIGN


def test_a_symlink_is_never_the_integrations(tmp_path: Path) -> None:
    """A link to an identical file is judged as a link, not by its target's bytes."""
    real = tmp_path / "elsewhere.py"
    real.write_bytes(BUNDLED)
    target = tmp_path / "wm25lz.py"
    target.symlink_to(real)

    assert bundle.inspect(target, BUNDLED) is FileState.FOREIGN


def test_a_broken_symlink_is_foreign_not_absent(tmp_path: Path) -> None:
    """A dangling link is something in the way, not an empty slot."""
    target = tmp_path / "wm25lz.py"
    target.symlink_to(tmp_path / "missing.py")

    assert bundle.inspect(target, BUNDLED) is FileState.FOREIGN


def test_a_directory_is_foreign(tmp_path: Path) -> None:
    """Anything that is not a regular file is not the integration's."""
    (tmp_path / "wm25lz.py").mkdir()

    assert bundle.inspect(tmp_path / "wm25lz.py", BUNDLED) is FileState.FOREIGN


def test_sync_installs_into_a_new_folder(tmp_path: Path) -> None:
    """Absent and allowed: the bundled bytes, folder created, nothing else left."""
    target = tmp_path / "custom_zha_quirks" / "wm25lz.py"

    result = bundle.sync(target, BUNDLED, install_if_absent=True)

    assert result == bundle.SyncResult(FileState.CURRENT, written=True)
    assert target.read_bytes() == BUNDLED
    assert sorted(path.name for path in target.parent.iterdir()) == ["wm25lz.py"]


def test_sync_leaves_an_absent_file_absent_unless_asked(tmp_path: Path) -> None:
    """Absent and not allowed (the quirk is active): nothing is written."""
    target = tmp_path / "wm25lz.py"

    result = bundle.sync(target, BUNDLED, install_if_absent=False)

    assert result == bundle.SyncResult(FileState.ABSENT, written=False)
    assert not target.exists()


def test_sync_replaces_an_outdated_copy(tmp_path: Path) -> None:
    """An outdated own copy is replaced in place, leaving no temporary file."""
    target = tmp_path / "wm25lz.py"
    target.write_text(f"{bundle.MARKER}\n# older\n")

    result = bundle.sync(target, BUNDLED, install_if_absent=False)

    assert result == bundle.SyncResult(FileState.CURRENT, written=True)
    assert target.read_bytes() == BUNDLED
    assert sorted(path.name for path in tmp_path.iterdir()) == ["wm25lz.py"]


@pytest.mark.parametrize(
    "content",
    [BUNDLED, b"# A quirk of the user's own.\n"],
    ids=["current", "foreign"],
)
def test_sync_leaves_a_current_or_foreign_file_alone(
    tmp_path: Path, content: bytes
) -> None:
    """Current or not the integration's: not written."""
    target = tmp_path / "wm25lz.py"
    target.write_bytes(content)
    mtime = target.stat().st_mtime_ns

    result = bundle.sync(target, BUNDLED, install_if_absent=True)

    assert result.written is False
    assert target.read_bytes() == content
    assert target.stat().st_mtime_ns == mtime


def _user_writes_meanwhile(
    monkeypatch: pytest.MonkeyPatch, target: Path, content: bytes
) -> None:
    """Make the user write ``target`` after the check, while the copy is being made."""
    original = tempfile.mkstemp

    def mkstemp(*args: Any, **kwargs: Any) -> Any:
        made = original(*args, **kwargs)
        if target.is_symlink() or target.exists():
            target.unlink()
        target.write_bytes(content)
        return made

    monkeypatch.setattr(bundle.tempfile, "mkstemp", mkstemp)


def test_sync_does_not_overwrite_a_file_the_user_wrote_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outdated when checked, the user's own just before the replace: kept."""
    target = tmp_path / "wm25lz.py"
    target.write_text(f"{bundle.MARKER}\n# older\n")
    _user_writes_meanwhile(monkeypatch, target, b"# Mine now.\n")

    result = bundle.sync(target, BUNDLED, install_if_absent=True)

    assert result == bundle.SyncResult(FileState.FOREIGN, written=False)
    assert target.read_bytes() == b"# Mine now.\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["wm25lz.py"]


def test_sync_does_not_overwrite_a_file_created_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent when checked, created by the user before the install: kept."""
    target = tmp_path / "wm25lz.py"
    _user_writes_meanwhile(monkeypatch, target, b"# Mine now.\n")

    result = bundle.sync(target, BUNDLED, install_if_absent=True)

    assert result == bundle.SyncResult(FileState.FOREIGN, written=False)
    assert target.read_bytes() == b"# Mine now.\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["wm25lz.py"]


def test_sync_writes_through_a_temporary_file_zha_would_not_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write is atomic, through a temporary file without a ``.py`` suffix."""
    temporary: list[Path] = []
    original = tempfile.mkstemp

    def spy(*args: Any, **kwargs: Any) -> Any:
        made = original(*args, **kwargs)
        temporary.append(Path(made[1]))
        return made

    monkeypatch.setattr(bundle.tempfile, "mkstemp", spy)

    bundle.sync(tmp_path / "wm25lz.py", BUNDLED, install_if_absent=True)

    assert len(temporary) == 1
    assert temporary[0].parent == tmp_path
    assert temporary[0].suffix != ".py"
    assert not temporary[0].exists()
    assert (tmp_path / "wm25lz.py").read_bytes() == BUNDLED
