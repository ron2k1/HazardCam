"""P16: the integrity scripts fail when they find a problem, and run from any cwd.

Each test copies the real scripts into a scratch tree and runs them with bash, so nothing
is written to the repo (in particular no ``artifacts/event_day/START.txt``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.scripts._shell import BASH, run_script, script_tree

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the scripts with")


def _boundary(tmp_path: Path, files: dict[str, str] | None = None):
    root = script_tree(
        tmp_path / "repo", "assert_prebuild_boundary.sh", "_boundary.sh", files=files
    )
    done = run_script(root / "scripts" / "assert_prebuild_boundary.sh", tmp_path)
    report = (root / "artifacts" / "PREBUILD_BOUNDARY_CHECK.txt").read_text("utf-8")
    return done, report


def test_boundary_passes_with_templates_only(tmp_path):
    done, report = _boundary(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "PASS: no finished agent implementation detected." in report
    assert "PASS: none." in report


def test_boundary_fails_on_an_agent_implementation(tmp_path):
    done, report = _boundary(tmp_path, {"agent/agent.py": "print('agent')\n"})
    assert done.returncode == 1
    assert "FORBIDDEN_PREBUILD_AGENT_FILE agent/agent.py" in report


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("runtime/nemoclaw/policy.py", "from eval.tool_probe import acceptable_calls\n"),
        ("runtime/nemoclaw/score.py", "import eval.scoring as scoring\n"),
        ("agent/event_day/oracle.py", "    from eval import tool_probe\n"),
        ("runtime/bridge.ts", 'import { oracle } from "../eval/tool_probe";\n'),
        ("scripts/runtime/serve.sh", "python -m eval.summary\n"),
    ],
)
def test_boundary_fails_when_event_day_code_imports_eval(tmp_path, rel, text):
    done, report = _boundary(tmp_path, {rel: text})
    assert done.returncode == 1
    assert f"FORBIDDEN_EVAL_IMPORT {rel}:1:" in report


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        ("runtime/notes.md", "Never import eval.tool_probe from the agent.\n"),
        ("runtime/nemoclaw/check.py", "import evaluation\nevaluate = True\n"),
    ],
)
def test_prose_and_lookalike_names_are_not_eval_imports(tmp_path, rel, text):
    done, report = _boundary(tmp_path, {rel: text})
    assert done.returncode == 0, report
    assert "FORBIDDEN_EVAL_IMPORT" not in report


def test_event_day_delta_fails_when_event_day_code_imports_eval(tmp_path):
    scripts = ("verify_event_delta.sh", "_boundary.sh", "_python.sh")
    clean = script_tree(tmp_path / "clean" / "repo", *scripts)
    assert (
        run_script(clean / "scripts" / "verify_event_delta.sh", tmp_path / "clean").returncode == 0
    )

    bad = script_tree(
        tmp_path / "bad" / "repo",
        *scripts,
        files={"runtime/policy.py": "from eval.tool_probe import acceptable_calls\n"},
    )
    done = run_script(bad / "scripts" / "verify_event_delta.sh", tmp_path / "bad")
    assert done.returncode == 1
    report = (bad / "artifacts" / "event_day" / "DELTA_REPORT.txt").read_text("utf-8")
    assert "FORBIDDEN_EVAL_IMPORT runtime/policy.py:1:" in report


def test_event_day_start_writes_into_the_repo_from_any_cwd(tmp_path):
    root = script_tree(tmp_path / "repo", "event_day_start.sh")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    done = run_script(root / "scripts" / "event_day_start.sh", elsewhere)
    assert done.returncode == 0, done.stderr
    assert (root / "artifacts" / "event_day" / "START.txt").is_file()
    assert not (elsewhere / "artifacts").exists()
