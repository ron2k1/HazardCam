# Sourced by scripts/*.sh that start servers under `set -m`, so each background job leads its
# own process group. Call stop_jobs_on_exit once, then add each server with
# started_jobs+=("$!"); however the script ends, every one of them and everything it started is
# gone before it returns.
STOP_GRACE_S="${STOP_GRACE_S:-10}"
if [[ ! $STOP_GRACE_S =~ ^(0|[1-9][0-9]*)$ ]]; then
  # bash arithmetic cannot compare anything else (08 reads as octal), and the stop would never
  # reach its KILL
  echo "STOP_GRACE_S must be whole seconds with no leading zero, not $STOP_GRACE_S" >&2
  exit 2
fi

started_jobs=()

# On exit, Ctrl+C (130) or TERM (143), stop every job in started_jobs.
stop_jobs_on_exit() {
  trap stop_started_jobs EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

stop_started_jobs() {
  # Nothing may cut the stop short: the servers lead their own process groups, so no other
  # signal reaches them, and a second Ctrl+C here would leave them running.
  trap '' INT TERM
  trap - EXIT
  # reap the jobs, unless one outlived its KILL: waiting on it would never return
  if stop_jobs "${started_jobs[@]}"; then wait 2>/dev/null || true; fi
}

stop_jobs() {
  local pid groups=()
  for pid in "$@"; do
    # Git Bash: end the Windows process tree by PID. -F, not //F: //F reaches taskkill as /F
    # only through MSYS argument conversion, which MSYS_NO_PATHCONV=1 turns off. Signals are
    # the fallback, and the path Linux and macOS take.
    if [ ! -r "/proc/$pid/winpid" ] ||
      ! taskkill -F -T -PID "$(cat "/proc/$pid/winpid")" >/dev/null 2>&1; then
      groups+=("$pid")
    fi
  done
  stop_groups "${groups[@]}"
}

# TERM every group at once, give them STOP_GRACE_S together to finish (uvicorn joins its run
# threads on shutdown), then KILL what is left. A job's leader is a bash subshell that dies on
# TERM at once, so waiting on the leader alone would return while its server still runs. A
# zombie counts as running: under a PID 1 that never reaps (`docker exec` into a container
# whose PID 1 is `sleep infinity`) a stop runs to the KILL and reports the group still running.
stop_groups() {
  local pid targets=() alive ticks=0
  for pid in "$@"; do
    # the group the job leads, or the process alone if it leads none
    if kill -0 -- "-$pid" 2>/dev/null; then targets+=("-$pid"); else targets+=("$pid"); fi
  done
  ((${#targets[@]})) || return 0
  kill -TERM -- "${targets[@]}" 2>/dev/null || true
  while :; do
    alive=()
    for pid in "${targets[@]}"; do
      if kill -0 -- "$pid" 2>/dev/null; then alive+=("$pid"); fi
    done
    ((${#alive[@]})) || return 0
    if ((ticks == STOP_GRACE_S * 5)); then
      kill -KILL -- "${alive[@]}" 2>/dev/null || true
    elif ((ticks > STOP_GRACE_S * 5 + 25)); then
      echo "still running 5s after KILL: ${alive[*]#-}" >&2
      return 1
    fi
    sleep 0.2
    ticks=$((ticks + 1))
  done
}
