"""P16: every script with a shebang is executable in git, so ./scripts/x runs on Linux.

Git on Windows (core.filemode=false) records new files as 100644 and ignores chmod, so a
script added from the dev laptop fails with "Permission denied" on the GB10.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from apps.api.schemas import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def test_every_tracked_script_with_a_shebang_is_executable():
    staged = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    not_executable = []
    for line in staged.splitlines():  # "<mode> <sha> <stage>\t<path>"
        mode, path = line.split(" ", 1)[0], line.split("\t", 1)[1]
        with (REPO_ROOT / path).open("rb") as f:
            if f.read(2) == b"#!" and mode != "100755":
                not_executable.append(path)
    assert not_executable == [], "run: git update-index --chmod=+x <path>"
