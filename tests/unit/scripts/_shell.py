"""Shared by the script tests: run the real scripts with bash, copied into a scratch tree, so
nothing is written to the repo."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from apps.api.schemas import REPO_ROOT

SCRIPTS = REPO_ROOT / "scripts"


def find_bash() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    # A bare `bash` on Windows can be the WSL launcher; use the one Git ships, found above
    # git.exe (cmd\ or mingw64\bin\ depending on PATH).
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return None


BASH = find_bash()


def script_tree(root: Path, *scripts: str, files: dict[str, str] | None = None) -> Path:
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


def run_script(
    script: Path, cwd: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    # Stop git from walking up out of the scratch tree into a real repository.
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(cwd.parent), **(env or {})}
    assert BASH is not None
    return subprocess.run(
        [BASH, script.as_posix(), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,  # the exit status is what the tests assert
    )
