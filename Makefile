SHELL := /usr/bin/env bash

.PHONY: preflight remote-probe status prebuild-ultracode event-day-start event-day-ultracode boundary-check snapshot-prebuild verify-event-delta fixture-e2e lite-e2e full-e2e eval demo-check

preflight:
	./scripts/preflight.sh

remote-probe:
	./scripts/remote_probe.sh

status:
	python3 scripts/task_status.py

prebuild-ultracode:
	./scripts/start_prebuild_ultracode.sh

event-day-start:
	./scripts/event_day_start.sh

event-day-ultracode:
	./scripts/start_event_day_ultracode.sh

boundary-check:
	./scripts/assert_prebuild_boundary.sh

snapshot-prebuild:
	./scripts/snapshot_prebuild.sh

verify-event-delta:
	./scripts/verify_event_delta.sh

fixture-e2e:
	@echo "Implement during P13: MODEL_PROFILE=fixture Playwright E2E"

lite-e2e:
	@echo "Implement during P14: MODEL_PROFILE=lite-local Playwright/model E2E"

full-e2e:
	@echo "Implement during P15/D03 according to available hardware"

eval:
	@echo "Implement during P12: scripts/eval/run_eval.py"

demo-check:
	./scripts/demo_check.sh
