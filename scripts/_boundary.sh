# Boundary checks shared by assert_prebuild_boundary.sh and verify_event_delta.sh.
# Sourced, not run: callers cd to the repo root first.
#
# eval/ is the judge side. It reads the withheld expected.json labels, and eval/tool_probe.py
# holds an oracle of the acceptable next tool call, which is exactly the decision policy the
# event-day agent must work out for itself. Event-day agent and runtime code never imports it.

EVENT_DAY_CODE_DIRS=(agent runtime scripts/runtime)
EVAL_IMPORT_RE='^[[:space:]]*(from|import)[[:space:]]+eval([.[:space:]]|$)|eval[./](tool_probe|scoring|summary)'

# Print "path:line:text" for every reference to the eval package in event-day code files.
# Prose (.md/.txt) may name the package; only code and config are checked.
eval_import_hits() {
  local dirs=() d
  for d in "${EVENT_DAY_CODE_DIRS[@]}"; do
    [ -d "$d" ] && dirs+=("$d")
  done
  ((${#dirs[@]})) || return 0
  grep -rnIE "$EVAL_IMPORT_RE" \
    --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.mjs' \
    --include='*.cjs' --include='*.sh' --include='*.json' --include='*.yaml' --include='*.yml' \
    --include='*.toml' "${dirs[@]}" || true
}
