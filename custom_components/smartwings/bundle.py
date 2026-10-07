"""The quirk file the integration ships, and the file operations that install it.

``bundled_quirk/wm25lz.py.txt`` is byte-identical to the quirk's source. It is installed
in ZHA's ``custom_quirks_path`` as ``wm25lz.py`` with ``MARKER`` prepended as line 1;
the integration never imports it. A copy is the integration's own only when it is a
regular file (not a link) whose first line is ``MARKER``, and is outdated when its bytes
differ from ``installed_bytes()``. Every function here does blocking I/O: run it in the
executor. ``sync`` re-checks ownership just before replacing a file, so a file the user
writes meanwhile is never overwritten.
"""

import contextlib
from dataclasses import dataclass
from enum import StrEnum
import errno
import os
from pathlib import Path
import stat
import tempfile
from typing import Final

BUNDLED_FILE: Final = Path(__file__).parent / "bundled_quirk" / "wm25lz.py.txt"
FILE_NAME: Final = "wm25lz.py"
# Line 1 of the installed file; it marks a copy this integration manages.
MARKER: Final = (
    "# Installed by the SmartWings integration for Home Assistant, which keeps this"
    " file up to date. Delete this line to keep the file as your own."
)


class FileState(StrEnum):
    """What is at the install target, as far as this integration is concerned."""

    ABSENT = "absent"
    CURRENT = "current"  # the integration's own, identical to installed_bytes()
    OUTDATED = "outdated"  # the integration's own, different from installed_bytes()
    FOREIGN = "foreign"  # anything else, links included: never touched


@dataclass(frozen=True, slots=True)
class SyncResult:
    """The state of the target after ``sync``, and whether ``sync`` wrote it."""

    state: FileState
    written: bool


def installed_bytes() -> bytes:
    """Return the bytes to install: the marker line, then the bundled quirk."""
    return MARKER.encode() + b"\n" + BUNDLED_FILE.read_bytes()


def inspect(target: Path, installed: bytes) -> FileState:
    """Return the state of ``target`` compared with the ``installed`` bytes.

    The path itself is judged, never what a link points at: a link, broken or not,
    and anything but a regular file is foreign.
    """
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return FileState.ABSENT
    except OSError as err:
        if err.errno == errno.ELOOP:  # the path is a symbolic link
            return FileState.FOREIGN
        raise
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        return FileState.FOREIGN
    with os.fdopen(descriptor, "rb") as file:
        data = file.read()
    first_line = data.split(b"\n", 1)[0].removesuffix(b"\r")
    if first_line != MARKER.encode():
        return FileState.FOREIGN
    if data == installed:
        return FileState.CURRENT
    return FileState.OUTDATED


def sync(target: Path, installed: bytes, *, install_if_absent: bool) -> SyncResult:
    """Bring the integration's own ``target`` up to date with ``installed``.

    An outdated own file is replaced; an absent one is installed only when
    ``install_if_absent``. A current or foreign file is left alone. The check and the
    write happen here together, and ownership is checked again just before the file is
    put in place, so a file the user created or changed meanwhile is kept.
    """
    state = inspect(target, installed)
    if not (
        state is FileState.OUTDATED or (state is FileState.ABSENT and install_if_absent)
    ):
        return SyncResult(state, written=False)
    if _write(target, installed, replace=state is FileState.OUTDATED):
        return SyncResult(FileState.CURRENT, written=True)
    return SyncResult(inspect(target, installed), written=False)


def _write(target: Path, installed: bytes, *, replace: bool) -> bool:
    """Put ``installed`` at ``target`` atomically; False if ``target`` is no longer ours.

    The bytes go to a temporary file in the same folder, named without a ``.py``
    suffix so ZHA's quirk loader never sees it. A new file is hard-linked into place,
    which fails if anything appeared at ``target``; an outdated own file is replaced
    only after its first line is checked again.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent, prefix=f".{FILE_NAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(installed)
        os.chmod(temporary, 0o644)
        if not replace:
            try:
                os.link(temporary, target)
            except FileExistsError:
                return False
            return True
        if inspect(target, installed) not in (FileState.OUTDATED, FileState.CURRENT):
            return False
        os.replace(temporary, target)
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
