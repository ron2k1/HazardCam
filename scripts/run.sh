#!/usr/bin/env bash
# One entry point for every Makefile target, for machines without make (the Windows dev box).
#   scripts/run.sh <target> [args...]      e.g. scripts/run.sh eval --scenario eval_001
# The Makefile delegates here, so each target's command lives in one place.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
. scripts/_python.sh

usage() {
  cat <<'USAGE'
usage: scripts/run.sh <target> [args...]
  preflight | remote-probe | status | demo-check
  start                API + web on 127.0.0.1, open /ops ($MODEL_PROFILE, else fixture; --smoke)
  test                 pytest (args pass through)
  eval                 score the harness on data/eval/manifest.json ($MODEL_PROFILE, else fixture)
  tool-probe           single-turn tool-call probe against local reasoning models
  offline-check        prove the fixture path needs no network (writes artifacts/offline)
  fixture-e2e          Playwright on /ops, fixture profile (args pass to playwright)
  lite-e2e | full-e2e  eval_001 on lite-local / full-local models (-g/--grep, --test-list or
                       a spec path replaces -g eval_001; other args add to it)
  boundary-check | snapshot-prebuild | prebuild-ultracode
  event-day-start | event-day-ultracode | verify-event-delta
USAGE
}

# Do the Playwright args pick tests? -g/--grep, --test-list, or a spec file or path. An option's
# value is skipped, so --output a/b or --shard 1/2 keeps the default, and an inverted filter
# (-G/--grep-invert) narrows it. The option lists follow `playwright test --help`;
# tests/unit/scripts/test_run_sh.py checks them against the installed Playwright.
picks_tests() {
  local a value=none
  for a in "$@"; do
    case "$value" in
      next) value=none && continue ;;
      optional) value=none && [[ $a != -* ]] && continue ;;
    esac
    case "$a" in
      -g | -g?* | --grep | --grep=* | --test-list | --test-list=*) return 0 ;;
      --add-reporter | --browser | -c | --config | -G | --grep-invert | --global-timeout | -j | \
        --workers | --last-failed-file | --max-failures | --output | --project | --repeat-each | \
        --reporter | --retries | --run-agents | --shard | --test-list-invert | --timeout | \
        --trace | --tsconfig | --ui-host | --ui-port | --update-source-method) value=next ;;
      --debug | --only-changed | -u | --update-snapshots) value=optional ;;
      -*) ;; # no value, or one attached (--output=a/b)
      *.ts | *.ts:* | */*) return 0 ;;
    esac
  done
  return 1
}

target="${1:-help}"
[ "$#" -gt 0 ] && shift
case "$target" in
  preflight) ./scripts/preflight.sh "$@" ;;
  remote-probe) ./scripts/remote_probe.sh "$@" ;;
  status) py scripts/task_status.py "$@" ;;
  demo-check) ./scripts/demo_check.sh "$@" ;;
  start) ./scripts/start_app.sh "$@" ;;
  test) py -m pytest "$@" ;;
  eval) py scripts/eval/run_eval.py "$@" ;;
  tool-probe) py scripts/eval/probe_tool_calls.py "$@" ;;
  offline-check) py scripts/offline_check.py "$@" ;;
  # E2E_PROFILE is set on every target, so one left in the shell cannot change the run.
  fixture-e2e) E2E_PROFILE=fixture pnpm --dir apps/web e2e "$@" ;;
  # A model target runs eval_001 alone unless the args pick tests: it is the only spec that
  # follows E2E_PROFILE, and the others would just redo the fixture run and rewrite its
  # screenshots.
  lite-e2e)
    picks_tests "$@" || set -- -g eval_001 "$@"
    E2E_PROFILE=lite-local E2E_RUN_TIMEOUT_S="${E2E_RUN_TIMEOUT_S:-600}" pnpm --dir apps/web e2e "$@"
    ;;
  full-e2e)
    picks_tests "$@" || set -- -g eval_001 "$@"
    E2E_PROFILE=full-local E2E_RUN_TIMEOUT_S="${E2E_RUN_TIMEOUT_S:-900}" pnpm --dir apps/web e2e "$@"
    ;;
  boundary-check) ./scripts/assert_prebuild_boundary.sh "$@" ;;
  snapshot-prebuild) ./scripts/snapshot_prebuild.sh "$@" ;;
  prebuild-ultracode) ./scripts/start_prebuild_ultracode.sh "$@" ;;
  event-day-start) ./scripts/event_day_start.sh "$@" ;;
  event-day-ultracode) ./scripts/start_event_day_ultracode.sh "$@" ;;
  verify-event-delta) ./scripts/verify_event_delta.sh "$@" ;;
  help | -h | --help) usage ;;
  *)
    echo "unknown target: $target" >&2
    usage >&2
    exit 2
    ;;
esac
