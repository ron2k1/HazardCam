"use client";

import { useEffect, useRef, useState } from "react";

import { applyEvent, EMPTY_RUN_VIEW, replayEvents, type RunView } from "@/lib/run-view";
import {
  buildMockEvents,
  mockHealth,
  mockJudge,
  MOCK_SOURCE_LABEL,
  mockScenario,
  mockScenarios,
  type MockVariant,
} from "@/mocks/mock";

import { OpsConsole } from "./ops-console";

export type OpsMockState = MockVariant | "idle";

// config/models/*.yaml profile ids (POST /api/runs 422s on anything else)
const PROFILES = ["fixture", "lite-local", "full-local", "remote16gb", "gb10"] as const;
const STEP_MS = 140;

/**
 * Standalone /ops: replays the contract-example event log through the same reducer the live
 * SSE path uses. No network. P11 swaps this container for the live one; OpsConsole is shared.
 */
export function OpsMock({ initial = "default" }: { initial?: OpsMockState }) {
  const variant: MockVariant = initial === "abstain" ? "abstain" : "default";
  const [view, setView] = useState<RunView>(() =>
    initial === "idle" ? EMPTY_RUN_VIEW : replayEvents(buildMockEvents(variant)),
  );
  const [profile, setProfile] = useState<string>(mockHealth.profile);
  const [revealed, setRevealed] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const run = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    const events = buildMockEvents(variant);
    setRevealed(false);
    setView(EMPTY_RUN_VIEW);
    let i = 0;
    const step = () => {
      const ev = events[i];
      setView((v) => applyEvent(v, ev));
      i += 1;
      timer.current = i < events.length ? window.setTimeout(step, STEP_MS) : null;
    };
    timer.current = window.setTimeout(step, STEP_MS);
  };

  return (
    <OpsConsole
      scenarios={mockScenarios}
      scenario={mockScenario}
      view={view}
      onScenarioChange={() => undefined}
      onRun={run}
      profiles={PROFILES}
      profile={profile}
      onProfileChange={setProfile}
      health={{ ...mockHealth, profile }}
      apiStatus="mock"
      judge={mockJudge}
      groundTruthRevealed={revealed}
      onRevealGroundTruth={() => setRevealed(true)}
      onHideGroundTruth={() => setRevealed(false)}
      sourceLabel={MOCK_SOURCE_LABEL}
      noSignalNote="MOCK · NO MEDIA"
    />
  );
}
