"use client";

import { useEffect, useRef, useState } from "react";

import { useRunStream } from "@/hooks/use-run-stream";
import { useStackHealth } from "@/hooks/use-stack-health";
import { api, ApiError, describeError } from "@/lib/api";
import { API_BASE_URL, LIVE } from "@/lib/config";
import type { JudgeGroundTruth, PublicScenario } from "@/lib/contracts";

import { OpsConsole, type OpsNotice } from "./ops-console";

export interface OpsLiveProps {
  /** ?scenario= deep link; falls back to the first scenario the API lists. */
  initialScenarioId?: string | null;
  /** ?pace= RunRequest.pace_s (0..5) for a watchable demo; null = server default. */
  paceS?: number | null;
}

/**
 * /ops wired to the local API: scenarios, health, POST /api/runs, the run's SSE stream,
 * and the judge reveal. Rendering lives in OpsConsole, shared with the offline mock.
 */
export function OpsLive({ initialScenarioId = null, paceS = null }: OpsLiveProps) {
  const [scenarios, setScenarios] = useState<PublicScenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [scenarioAttempt, setScenarioAttempt] = useState(0);
  const [scenarioId, setScenarioId] = useState<string | null>(initialScenarioId);
  const [profile, setProfile] = useState<string>(LIVE.defaultProfile);
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

  // Only fixture is listed unless the API's own default profile is something else. A choice the
  // API no longer offers (restarted with another MODEL_PROFILE) falls back to the default, so
  // the select shows the profile RUN will post.
  const apiProfile = health.service?.profile;
  const profiles = apiProfile && apiProfile !== LIVE.defaultProfile ? [LIVE.defaultProfile, apiProfile] : [LIVE.defaultProfile];
  const runProfile = profiles.includes(profile) ? profile : LIVE.defaultProfile;

  const changeScenario = (id: string) => {
    generation.current += 1;
    setScenarioId(id);
    stream.reset();
    setRevealed(false);
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
      // No HTTP status: the request may still have reached the API and started a run.
      setRunError(
        err instanceof ApiError && err.status === 0
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
      setJudgePending(false);
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
    <OpsConsole
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
