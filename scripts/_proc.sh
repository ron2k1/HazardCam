# Sourced by scripts/*.sh that start servers under `set -m`, so each background job leads its
# own process group. `stop_job PID` ends that job and everything it started before returning.
STOP_GRACE_S="${STOP_GRACE_S:-10}"

# TERM the group, give it STOP_GRACE_S to finish (uvicorn joins its run threads on shutdown),
# then KILL. The job's leader is a bash subshell that dies on TERM at once, so waiting on the
# leader alone would return while the server it started is still running.
stop_group() {
  local target="-$1" ticks=0
  kill -0 -- "$target" 2>/dev/null || target="$1" # not a group leader: the process alone
  kill -TERM -- "$target" 2>/dev/null || return 0
  while kill -0 -- "$target" 2>/dev/null; do
    if ((ticks == STOP_GRACE_S * 5)); then
      kill -KILL -- "$target" 2>/dev/null || true
    elif ((ticks > STOP_GRACE_S * 5 + 25)); then
      echo "process group $1 still running 5s after KILL" >&2
      return 1
    fi
    sleep 0.2
    ticks=$((ticks + 1))
  done
}

stop_job() {
  if [ -r "/proc/$1/winpid" ]; then # Git Bash: end the Windows process tree by PID
    # -F, not //F: //F reaches taskkill as /F only through MSYS argument conversion, which
    # MSYS_NO_PATHCONV=1 turns off
    taskkill -F -T -PID "$(cat "/proc/$1/winpid")" >/dev/null 2>&1 || true
  else
    stop_group "$1"
  fi
}
