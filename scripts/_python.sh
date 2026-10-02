# Sourced by scripts/*.sh: `py ARGS...` runs the project interpreter.
# Order: $PYTHON, the repo venv (Windows, then POSIX layout), then python3 on PATH.
# On Windows, python3 on PATH is often a different install (or the Store stub) without
# the project's dependencies, so the venv wins whenever it exists.
py() {
  local root
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [ -n "${PYTHON:-}" ]; then
    "$PYTHON" "$@"
  elif [ -x "$root/.venv/Scripts/python.exe" ]; then
    "$root/.venv/Scripts/python.exe" "$@"
  elif [ -x "$root/.venv/bin/python" ]; then
    "$root/.venv/bin/python" "$@"
  else
    python3 "$@"
  fi
}
