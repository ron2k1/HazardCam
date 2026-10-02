SHELL := /usr/bin/env bash

# Every target delegates to scripts/run.sh, which also works where make is absent:
#   scripts/run.sh <target> [args...]
TARGETS := preflight remote-probe status demo-check test eval tool-probe \
	fixture-e2e lite-e2e full-e2e boundary-check snapshot-prebuild prebuild-ultracode \
	event-day-start event-day-ultracode verify-event-delta

.PHONY: $(TARGETS)

$(TARGETS):
	./scripts/run.sh $@
