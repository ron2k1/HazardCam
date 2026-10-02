"""P16: scripts/_proc.sh, which start_app.sh uses to stop its servers: every job's whole
process group, TERM then KILL, with nothing able to cut the stop short."""

from __future__ import annotations

import time

import pytest

from tests.unit.scripts._shell import BASH, run_script, script_tree

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the scripts with")


# --- stop_groups: a server outlives the bash subshell that leads its job -------------------

# The job mirrors start_app's: `py` (a function) runs in a forked subshell that leads the
# group, and the server is that subshell's child.
_STOP_DRIVER = """\
set -m
. scripts/_python.sh
. scripts/_proc.sh
PYTHON="$BASH" py -c "$INNER" inner "$PWD/inner.pid" &
leader=$!
until [ -s inner.pid ]; do sleep 0.1; done
inner=$(cat inner.pid)
stop_groups "$leader"
if kill -0 "$inner" 2>/dev/null; then echo "inner alive"; else echo "inner gone"; fi
echo "leader $leader inner $inner"
kill -KILL "$inner" 2>/dev/null || true # a server stop_groups missed must not outlive the test
"""


@pytest.mark.parametrize(
    ("case", "inner", "grace_s"),
    [
        # TERM handled slowly, as uvicorn does while it finishes in-flight requests
        (
            "slow-exit",
            "trap 'sleep 1; exit 0' TERM; echo $$ >\"$1\"; while :; do sleep 0.1; done",
            20,
        ),
        # TERM ignored: only the KILL after the grace period ends it
        ("ignores-term", "trap '' TERM; echo $$ >\"$1\"; while :; do sleep 0.1; done", 1),
    ],
    ids=["slow-exit", "ignores-term"],
)
def test_stop_groups_returns_only_once_the_server_is_gone(tmp_path, case, inner, grace_s):
    root = script_tree(
        tmp_path / "repo", "_python.sh", "_proc.sh", files={"driver.sh": _STOP_DRIVER}
    )
    started = time.monotonic()
    done = run_script(root / "driver.sh", root, env={"INNER": inner, "STOP_GRACE_S": str(grace_s)})
    elapsed = time.monotonic() - started
    assert done.returncode == 0, done.stderr
    leader, inner_pid = done.stdout.split("leader ")[1].split(" inner ")
    assert leader.strip() != inner_pid.strip(), "the server must be the leader's child"
    assert "inner gone" in done.stdout, case
    # a slow exit is waited for, not sat out to the grace limit
    assert elapsed < 10, f"{case} took {elapsed:.1f}s"


# start_app's exit path on two jobs: A ignores TERM (uvicorn waiting out a model call), so the
# stop sits in its grace period; B exits on TERM. A second Ctrl+C lands during that grace
# period. The jobs write nothing to the driver's pipes, so one left running cannot hold the
# test open.
_INTERRUPT_DRIVER = """\
set -m
. scripts/_proc.sh
taskkill() { return 1; } # Git Bash: take the signal path, the one Linux takes
stop_jobs_on_exit
bash -c 'trap "" TERM; echo $$ >a.pid; while :; do sleep 0.1; done' </dev/null >/dev/null 2>&1 &
started_jobs+=("$!")
bash -c 'trap "date +%s%N >b.term; exit 0" TERM; echo $$ >b.pid; while :; do sleep 0.1; done' \\
  </dev/null >/dev/null 2>&1 &
started_jobs+=("$!")
until [ -s a.pid ] && [ -s b.pid ]; do sleep 0.1; done
(sleep 0.5; date +%s%N >int1; kill -INT $$; sleep 1; kill -INT $$) </dev/null >/dev/null 2>&1 &
wait
"""

# A stop that hangs fails the test in 35 s instead of holding it open: on Windows run_script's
# timeout ends Git's bash.exe launcher, not the bash it started.
_BOUNDED = """\
if command -v timeout >/dev/null; then timeout -k 5 30 bash driver.sh; else bash driver.sh; fi
echo "driver exit $?"
"""

# Run after the driver: which of its jobs still run (bash pids, so bash checks them).
_SURVIVORS = """\
for f in a.pid b.pid; do
  if kill -0 "$(cat "$f")" 2>/dev/null; then echo "${f%.pid} alive"; kill -KILL "$(cat "$f")"; fi
done
true
"""


def test_stop_jobs_on_exit_survives_a_second_interrupt_and_terms_every_job_at_once(tmp_path):
    root = script_tree(
        tmp_path / "repo",
        "_proc.sh",
        files={"driver.sh": _INTERRUPT_DRIVER, "bounded.sh": _BOUNDED, "survivors.sh": _SURVIVORS},
    )
    done = run_script(root / "bounded.sh", root, env={"STOP_GRACE_S": "3"})
    survivors = run_script(root / "survivors.sh", root)
    assert survivors.stdout == "", (
        "jobs still running after the stop (cut short, or never signalled)"
    )
    assert done.stdout.strip() == "driver exit 130", done.stderr
    # B was TERMed with A, not after A's grace period and KILL
    b_term_s = (int((root / "b.term").read_text()) - int((root / "int1").read_text())) / 1e9
    assert b_term_s < 1, f"B got TERM {b_term_s:.1f}s after Ctrl+C"


@pytest.mark.parametrize("grace", ["1.5", "ten", "-1"])
def test_proc_rejects_a_stop_grace_that_is_not_whole_seconds(tmp_path, grace):
    # bash arithmetic cannot compare it, so the stop would never reach its KILL or its limit
    root = script_tree(
        tmp_path / "repo", "_proc.sh", files={"driver.sh": ". scripts/_proc.sh\necho sourced\n"}
    )
    done = run_script(root / "driver.sh", root, env={"STOP_GRACE_S": grace})
    assert done.returncode == 2
    assert f"STOP_GRACE_S must be whole seconds, not {grace}" in done.stderr
    assert "sourced" not in done.stdout
