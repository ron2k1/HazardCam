"""P16: the integrity scripts fail when they find a violation, and run from any cwd.

Each test copies the real scripts into a scratch tree and runs them with bash, so nothing
is written to the repo (in particular no ``artifacts/event_day/START.txt``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from apps.api.schemas import REPO_ROOT

SCRIPTS = REPO_ROOT / "scripts"


def _bash() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    # A bare `bash` on Windows can be the WSL launcher; use the one Git ships, found above
    # git.exe (cmd\ or mingw64\bin\ depending on PATH).
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return None


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the scripts with")


def _tree(root: Path, *scripts: str, files: dict[str, str] | None = None) -> Path:
    (root / "scripts").mkdir(parents=True)
    for name in scripts:
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    for rel, text in {
        "agent/README.md": "Agent built on event day.\n",
        "agent/tools.template.json": "{}\n",
        "agent/event_day/.gitkeep": "",
        **(files or {}),
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


def _run(script: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    # Stop git from walking up out of the scratch tree into a real repository.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent)}
    assert BASH is not None
    return subprocess.run(
        [BASH, script.as_posix()],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,  # the exit status is what the tests assert
    )


def _boundary(tmp_path: Path, files: dict[str, str] | None = None):
    root = _tree(tmp_path / "repo", "assert_prebuild_boundary.sh", "_boundary.sh", files=files)
    done = _run(root / "scripts" / "assert_prebuild_boundary.sh", tmp_path)
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
    clean = _tree(tmp_path / "clean" / "repo", *scripts)
    assert _run(clean / "scripts" / "verify_event_delta.sh", tmp_path / "clean").returncode == 0

    bad = _tree(
        tmp_path / "bad" / "repo",
        *scripts,
        files={"runtime/policy.py": "from eval.tool_probe import acceptable_calls\n"},
    )
    done = _run(bad / "scripts" / "verify_event_delta.sh", tmp_path / "bad")
    assert done.returncode == 1
    report = (bad / "artifacts" / "event_day" / "DELTA_REPORT.txt").read_text("utf-8")
    assert "FORBIDDEN_EVAL_IMPORT runtime/policy.py:1:" in report

