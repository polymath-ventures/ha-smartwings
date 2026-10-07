"""Check docs/evidence/bench-run-sheets.md against the bench it drives.

Every action block in the run sheets is run through the bench's own checks (fields,
ranges, the move and write guards) up to the point where it would start sending, and
stopped there. So a block the bench would refuse, a misspelt field, or a moving step
without its safety flags fails here rather than in front of the shade.
"""

from pathlib import Path
import re
from types import SimpleNamespace

import pytest
import yaml
import zigpy.types as t

from tests.test_bench_user_script import OFFICE_SHADE, app, load_script  # noqa: F401

ROOT = Path(__file__).parents[1]
SHEETS = ROOT / "docs" / "evidence" / "bench-run-sheets.md"
PLAN = ROOT / "docs" / "test-plan.md"
BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def _blocks():
    text = SHEETS.read_text()
    blocks, end = [], 0
    for match in BLOCK.finditer(text):
        body = yaml.safe_load(re.sub(r"^ {3}", "", match.group(1), flags=re.M))
        if body.get("action") == "zha_toolkit.execute":
            blocks.append((text[end : match.start()], body))
        end = match.end()
    return blocks


BLOCKS = _blocks()


class ReachedSendingError(Exception):
    """Raised where the bench would start its call: every check has passed."""


NEVER_SENT = ("goto_lift_value", "tilt_value", "tilt_percentage")


def _plan_status() -> dict[str, str]:
    """Test ID -> status, from the plan's §6 status table."""
    rows = re.findall(
        r"^\| `([A-Z0-9-]+)` \| [^|]+ \| ([^|]+) \|", PLAN.read_text(), re.M
    )
    return {test_id: status.strip() for test_id, status in rows}


def test_the_sheets_have_blocks_for_sessions_a_to_c():
    """A (the record of its run), B and C have blocks with unique steps; D has none."""
    steps = [(b["data"]["session"], b["data"]["step"]) for _, b in BLOCKS]
    assert {session for session, _ in steps} == {"A", "B", "C"}
    assert len(steps) == len(set(steps)) > 30


def test_no_sheet_sends_lift_value_or_tilt_and_the_bench_refuses_them():
    """0x04, 0x07 and 0x08 appear in no block, and the bench refuses each of them."""
    sheets = SHEETS.read_text()
    for name in NEVER_SENT:
        assert f"user_bench_{name}" not in sheets
    assert not any(
        b["data"]["command"].removeprefix("user_bench_") in NEVER_SENT
        for _, b in BLOCKS
    )
    bench = load_script()
    assert not {(0x0102, c) for c in (0x04, 0x07, 0x08)} & set(bench.CLUSTER_COMMANDS)
    assert {(0x0102, c) for c in (0x04, 0x07, 0x08)} <= bench.NEVER_SEND


@pytest.mark.parametrize("name", NEVER_SENT)
async def test_the_bench_refuses_never_sent_actions(app, name):  # noqa: F811
    """A step written for a never-sent command is refused before anything is built."""
    bench = load_script()
    data = {
        "command": f"user_bench_{name}",
        "ieee": OFFICE_SHADE,
        "session": "B",
        "test_id": "CMD-GOTO-LIFT-VALUE",
        "value": 0,
        "remote_ready": True,
        "may_go_down": True,
    }
    with pytest.raises(ValueError, match="never sent"):
        await getattr(bench, data["command"])(
            app,
            None,
            t.EUI64.convert(OFFICE_SHADE),
            data["command"],
            None,
            SimpleNamespace(data=data),
            {},
            {},
        )


def test_no_block_runs_a_test_the_plan_retired():
    """No block runs a "do not run" test; B and C run no moot test."""
    status = _plan_status()
    assert len(status) > 80
    for _, block in BLOCKS:
        data = block["data"]
        assert "do not run" not in status[data["test_id"]], data["step"]
        if data["session"] != "A":  # A is the record of the 2026-10-06 run
            assert not status[data["test_id"]].startswith("moot"), data["step"]


@pytest.mark.parametrize(
    ("before", "block"), BLOCKS, ids=[b["data"]["step"] for _, b in BLOCKS]
)
async def test_each_block_passes_the_bench_checks(app, before, block):  # noqa: F811
    """The block names a bench action and a plan test, and the bench accepts it."""
    data = block["data"]
    assert data["ieee"] == OFFICE_SHADE
    assert f"`{data['test_id']}`" in PLAN.read_text()
    bench = load_script()

    async def reached(self):
        raise ReachedSendingError

    bench.Bench.__aenter__ = reached
    handler = getattr(bench, data["command"])
    with pytest.raises(ReachedSendingError):
        await handler(
            app,
            None,
            t.EUI64.convert(data["ieee"]),
            data["command"],
            None,
            SimpleNamespace(data=data),
            {},
            {},
        )
    if data.get("remote_ready"):
        # The safety step comes right before every moving block.
        assert "**Safety**" in before


def test_every_session_test_in_the_plan_has_a_sheet():
    """Each test the plan's §5 schedules in sessions A-D is named in the sheets."""
    sheets = SHEETS.read_text()
    rows = [
        line
        for line in PLAN.read_text().splitlines()
        if re.match(r"\| \*\*[ABCD]\. ", line)
    ]
    assert len(rows) == 4
    wanted = {name for row in rows for name in re.findall(r"`([A-Z0-9-]+)`", row)}
    assert len(wanted) >= 30
    assert sorted(name for name in wanted if f"`{name}`" not in sheets) == []


# A sentence that has the owner work the shade with the remote: a remote action verb
# and "with the (same) remote" or "the remote's Up/Down" in one sentence, or a button
# press.
REMOTE = re.compile(r"with the (?:same )?remote|the remote's (?:Up|Down)", re.I)
VERB = re.compile(
    r"\b(?:move|moving|lower|raise|drive|stop|restore|set|change|reverse|undo|put|"
    r"test|check)\b",
    re.I,
)
PRESS = re.compile(
    r"press(?:es)? (?:Up|Down)\b|double-press|remote to (?:lower|raise)", re.I
)
# A new step starts at a heading, a bold step label such as **B19.**, or a numbered item.
STEP_START = re.compile(r"^(?:#{2,4} |\*\*[A-D]\d+[a-z]?[.:\s]|\s*\d+\. )")


def _remote_moves_without_safety(text: str) -> list[tuple[str, str]]:
    sessions = text[text.index("## 4. Session A") : text.index("## 8. ")]
    missing, step, safety = [], None, False
    for line in sessions.splitlines():
        if STEP_START.match(line):
            step, safety = line[:40], False
        for sentence in re.split(r"(?<=[.:;])\s+", line):
            if "**Safety**" in sentence:
                safety = True
            moves = PRESS.search(sentence) or (
                REMOTE.search(sentence) and VERB.search(sentence)
            )
            if moves and not safety:
                missing.append((step, sentence[:80]))
    return missing


def test_the_remote_move_check_catches_an_unguarded_restore():
    """The check flags a numbered undo that restores a limit with the remote."""
    text = (
        "## 4. Session A\n\n1. **Safety** (§2f): thumb on Stop. Set a limit.\n"
        "2. **Undo:** restore the original upper limit with the remote.\n## 8. End\n"
    )
    assert [line for _, line in _remote_moves_without_safety(text)] == [
        "**Undo:** restore the original upper limit with the remote."
    ]


def test_every_remote_move_in_a_session_follows_a_safety_step():
    """A step that has the owner move the shade with the remote says **Safety** first."""
    assert _remote_moves_without_safety(SHEETS.read_text()) == []


def test_repeated_down_close_is_a_series():
    """B3 and B8 repeat Down/Close, so rule 4.7 names them in the series list."""
    text = SHEETS.read_text()
    series = text[text.index("### 2g.") : text.index("## 3. ")]
    assert "B3" in series
    assert "B8" in series
