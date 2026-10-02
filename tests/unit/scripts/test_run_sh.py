"""P16: run.sh's e2e targets pin their profile, and a model profile runs eval_001 alone
unless the arguments pick tests. pnpm is a stub that prints what it was given.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.scripts._shell import BASH, SCRIPTS, run_script, script_tree

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the scripts with")

NODE = shutil.which("node")

_STUB_PNPM = '#!/usr/bin/env bash\necho "E2E_PROFILE=${E2E_PROFILE:-} args: $*"\n'


def _tool_dir() -> str:
    """The directory holding coreutils for the bash in use; PATH gets nothing else, so a stub
    that bash fails to pick up cannot fall through to the real pnpm and start Playwright."""
    assert BASH is not None
    if os.name == "nt":
        return str(Path(BASH).parents[1] / "usr" / "bin")
    dirname = shutil.which("dirname")
    assert dirname is not None
    return str(Path(dirname).parent)


@pytest.mark.parametrize(
    ("target", "args", "expected"),
    [
        # a profile left in the shell must not turn the fixture suite into a model run
        ("fixture-e2e", (), "E2E_PROFILE=fixture args: --dir apps/web e2e"),
        # bare real-model targets run eval_001 alone, so they do not rewrite fixture evidence
        ("lite-e2e", (), "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001"),
        ("full-e2e", (), "E2E_PROFILE=full-local args: --dir apps/web e2e -g eval_001"),
        # a test selection replaces eval_001; any other flag runs on top of it
        (
            "lite-e2e",
            ("-g", "eval_005"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_005",
        ),
        (
            "lite-e2e",
            ("--grep=eval_005",),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e --grep=eval_005",
        ),
        (
            "full-e2e",
            ("ops-races.spec.ts",),
            "E2E_PROFILE=full-local args: --dir apps/web e2e ops-races.spec.ts",
        ),
        (
            "lite-e2e",
            ("--headed",),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 --headed",
        ),
        (
            "full-e2e",
            ("--workers", "1", "--reporter=line"),
            "E2E_PROFILE=full-local args: --dir apps/web e2e -g eval_001 --workers 1 --reporter=line",
        ),
        (
            "lite-e2e",
            ("--output=tmp/e2e",),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 --output=tmp/e2e",
        ),
        # an option's value is not a spec path, slash or .ts or not
        (
            "lite-e2e",
            ("--output", "tmp/e2e"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 --output tmp/e2e",
        ),
        (
            "full-e2e",
            ("--shard", "1/2", "-c", "./playwright.config.ts"),
            "E2E_PROFILE=full-local args: --dir apps/web e2e -g eval_001 --shard 1/2 -c ./playwright.config.ts",
        ),
        # an inverted filter narrows eval_001 rather than replacing it
        (
            "lite-e2e",
            ("--grep-invert", "eval_001"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 --grep-invert eval_001",
        ),
        # a test list picks tests; an optional value is taken only when no option follows
        (
            "lite-e2e",
            ("--test-list", "tests.txt"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e --test-list tests.txt",
        ),
        (
            "lite-e2e",
            ("--only-changed", "origin/main"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 --only-changed origin/main",
        ),
        (
            "lite-e2e",
            ("--only-changed", "-g", "eval_005"),
            "E2E_PROFILE=lite-local args: --dir apps/web e2e --only-changed -g eval_005",
        ),
    ],
)
def test_run_e2e_targets_pin_their_profile_and_scope(tmp_path, target, args, expected):
    assert _run_e2e_target(tmp_path, target, *args) == expected


_PLAYWRIGHT_CLI = (
    SCRIPTS.parent / "apps" / "web" / "node_modules" / "@playwright" / "test" / "cli.js"
)


@pytest.mark.skipif(NODE is None, reason="no node to read Playwright's options")
@pytest.mark.skipif(not _PLAYWRIGHT_CLI.is_file(), reason="apps/web dependencies not installed")
def test_run_e2e_targets_skip_the_value_of_every_playwright_option(tmp_path):
    # Read from the installed Playwright, so an upgrade that adds an option fails here rather
    # than quietly running every spec on a model profile.
    assert NODE is not None
    usage = subprocess.run(
        [NODE, str(_PLAYWRIGHT_CLI), "test", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    specs = re.findall(r"^\s+((?:-\w, )?--[\w-]+) [<\[]", usage, re.MULTILINE)
    # the ones that pick tests replace the default by design
    flags = [
        f for spec in specs for f in spec.split(", ") if f not in {"-g", "--grep", "--test-list"}
    ]
    assert {"-c", "--output", "--shard", "--debug"} <= set(flags), usage
    args = [arg for flag in flags for arg in (flag, "a/b.spec.ts")]
    assert _run_e2e_target(tmp_path, "lite-e2e", *args) == (
        f"E2E_PROFILE=lite-local args: --dir apps/web e2e -g eval_001 {' '.join(args)}"
    )


def _run_e2e_target(tmp_path: Path, target: str, *args: str) -> str:
    """run.sh `target` with a pnpm stub that prints what it was given."""
    root = script_tree(tmp_path / "repo", "run.sh", "_python.sh")
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "pnpm").write_text(_STUB_PNPM, newline="\n")
    (stubs / "pnpm").chmod(0o755)
    done = run_script(
        root / "scripts" / "run.sh",
        tmp_path,
        target,
        *args,
        # bash's own directory too: the stub's `env bash` needs it where /bin is not /usr/bin
        env={
            "PATH": os.pathsep.join([str(stubs), str(Path(BASH or "").parent), _tool_dir()]),
            "E2E_PROFILE": "from-the-shell",
        },
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()
