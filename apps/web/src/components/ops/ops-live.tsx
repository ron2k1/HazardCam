"use client";

import { useEffect, useRef, useState } from "react";

import { useRunStream } from "@/hooks/use-run-stream";
import { useStackHealth } from "@/hooks/use-stack-health";
import type { ViewMode } from "@/hooks/use-view-mode";
import { api, ApiError, describeError } from "@/lib/api";
import { API_BASE_URL, LIVE } from "@/lib/config";
import type { JudgeGroundTruth, PublicScenario } from "@/lib/contracts";

import type { OpsNotice } from "./ops-console";
import { OpsScreen } from "./ops-screen";

export interface OpsLiveProps {
  /** ?scenario= deep link; falls back to the first scenario the API lists. */
  initialScenarioId?: string | null;
  /** ?pace= RunRequest.pace_s (0..5) for a watchable demo; null = server default. */
  paceS?: number | null;
  /** ?view= as the server read it: the worker view unless "technical". */
  initialView?: ViewMode | null;
  /** ?profile= deep link; used only if the API offers it (fixture or its MODEL_PROFILE). */
  initialProfile?: string | null;
}

/**
 * /ops wired to the local API: scenarios, health, POST /api/runs, the run's SSE stream,
 * and the judge reveal. Rendering lives in OpsScreen (worker view or technical console), shared
 * with the offline mock.
 */
export function OpsLive({
  initialScenarioId = null,
  paceS = null,
  initialView = null,
  initialProfile = null,
}: OpsLiveProps) {
  const [scenarios, setScenarios] = useState<PublicScenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [scenarioAttempt, setScenarioAttempt] = useState(0);
  const [scenarioId, setScenarioId] = useState<string | null>(initialScenarioId);
  const [profile, setProfile] = useState<string>(initialProfile ?? LIVE.defaultProfile);
  const [runError, setRunError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [judge, setJudge] = useState<JudgeGroundTruth | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [judgePending, setJudgePending] = useState(false);
  const [judgeError, setJudgeError] = useState<string | null>(null);
  // Bumped by every run and scenario change; a run or judge reply from before it is dropped.
  const generation = useRef(0);

  const health = useStackHealth(profile);
  const { view, status, stream } = useRunStream();
  const online = health.service !== null;

  // Load the list once the API answers, and again if it comes back with nothing loaded; a
  // failed load is retried while the API stays up.
  const needScenarios = online && scenarios.length === 0;
  useEffect(() => {
    if (!needScenarios) return;
    const ctrl = new AbortController();
    let retry: ReturnType<typeof setTimeout> | undefined;
    api.scenarios(ctrl.signal).then(
      (r) => {
        setScenarios(r.scenarios);
        setScenarioError(null);
      },
      (err) => {
        if (ctrl.signal.aborted) return;
        setScenarioError(describeError(err));
        retry = setTimeout(() => setScenarioAttempt((n) => n + 1), LIVE.scenarioRetryMs);
      },
    );
    return () => {
      ctrl.abort();
      clearTimeout(retry);
    };
  }, [needScenarios, scenarioAttempt]);

  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios[0] ?? null;
  // A judge reply for another scenario (selection changed mid-fetch) is never shown.
  const judgeShown = judge && scenario && judge.scenario_id === scenario.id ? judge : null;

  // The select, the models health and RUN all use the profile the API offers (useStackHealth).
  const { profiles, profile: runProfile } = health;

  const changeScenario = (id: string) => {
    generation.current += 1;
    setScenarioId(id);
    stream.reset();
    setRevealed(false);
    setJudgePending(false);
    setJudgeError(null);
    setRunError(null);
    const url = new URL(window.location.href);
    url.searchParams.set("scenario", id);
    window.history.replaceState(null, "", url);
  };

  // The scenario and profile selects and REVEAL are locked while this POST is in flight
  // (runPending), so the run it starts belongs to the scenario on screen.
  const run = async () => {
    if (!scenario || posting) return;
    const gen = ++generation.current;
    setPosting(true);
    setRunError(null);
    setRevealed(false);
    // a reveal still in flight belongs to the previous run; its reply will be dropped
    setJudgePending(false);
    setJudgeError(null);
    try {
      const res = await api.createRun({
        scenario_id: scenario.id,
        profile: runProfile,
        ...(paceS != null ? { pace_s: paceS } : {}),
      });
      if (gen === generation.current) stream.start(res);
    } catch (err) {
      if (gen !== generation.current) return;
      // No reply (status 0), or a 2xx whose body never arrived: the API may have started a run.
      const unconfirmed = err instanceof ApiError && (err.status === 0 || (err.status >= 200 && err.status < 300));
      setRunError(
        unconfirmed
          ? `RUN NOT CONFIRMED · ${describeError(err)} · THE API MAY HAVE STARTED IT`
          : `RUN REJECTED · ${describeError(err)}`,
      );
    } finally {
      setPosting(false);
    }
  };

  // The only caller of the judge endpoint.
  const reveal = async () => {
    if (!scenario) return;
    if (judgeShown) {
      setRevealed(true);
      return;
    }
    const gen = generation.current;
    setJudgePending(true);
    setJudgeError(null);
    try {
      const reply = await api.judge(scenario.id);
      // a RE-RUN or scenario change since the click: this reveal no longer applies
      if (gen !== generation.current) return;
      setJudge(reply);
      setRevealed(true);
    } catch (err) {
      if (gen === generation.current) setJudgeError(describeError(err));
    } finally {
      // only this generation's reveal may clear it: an older one must not unlock a newer one
      if (gen === generation.current) setJudgePending(false);
    }
  };

  let notice: OpsNotice | null = null;
  if (health.apiStatus === "offline") {
    notice = { tone: "danger", text: `API OFFLINE · ${API_BASE_URL} · ${health.apiDetail ?? "unreachable"}` };
  } else if (runError) {
    notice = { tone: "danger", text: runError };
  } else if (scenarioError) {
    notice = { tone: "danger", text: `SCENARIOS UNAVAILABLE · ${scenarioError}` };
  } else if (status === "reconnecting") {
    notice = { tone: "muted", text: "EVENT STREAM INTERRUPTED · RESUMING FROM LAST SEQ" };
  }

  return (
    <OpsScreen
      initialView={initialView}
      scenarios={scenarios}
      scenario={scenario}
      view={view}
      onScenarioChange={changeScenario}
      onRun={run}
      runPending={posting}
      profiles={profiles}
      profile={runProfile}
      onProfileChange={setProfile}
      health={health.models}
      apiStatus={health.apiStatus}
      apiDetail={health.apiDetail}
      judge={judgeShown}
      groundTruthRevealed={revealed && !!judgeShown}
      groundTruthPending={judgePending}
      groundTruthError={judgeError}
      onRevealGroundTruth={reveal}
      onHideGroundTruth={() => setRevealed(false)}
      sourceLabel={
        !view.profile
          ? null
          : view.profile === "fixture"
            ? "FIXTURE · RECORDED MODEL OUTPUTS · NO MODEL CALLS"
            : `LOCAL MODELS · ${view.profile.toUpperCase()}`
      }
      noSignalNote="MEDIA NOT ON API HOST"
      notice={notice}
      linkStatus={status}
    />
  );
}
