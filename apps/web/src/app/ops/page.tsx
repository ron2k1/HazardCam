import type { Metadata } from "next";

import { OpsLive } from "@/components/ops/ops-live";
import { OpsMock, type OpsMockState } from "@/components/ops/ops-mock";
import { parseViewMode } from "@/lib/view-mode";
import { LIVE } from "@/lib/config";

export const metadata: Metadata = {
  title: "Ops · CameraVision",
};

const STATES: readonly OpsMockState[] = ["default", "abstain", "idle"];

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** apps/api/settings.py PROFILE_NAME_RE; the page still runs only a profile the API offers. */
function parseProfile(v: string | undefined): string | null {
  const name = v?.trim() ?? "";
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(name) ? name : null;
}

function parsePace(v: string | undefined): number | null {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(Math.max(n, 0), LIVE.maxPaceS) : null;
}

/**
 * /ops is the live console. /ops?mock[=default|abstain|idle] replays contracts/examples
 * offline (design checks); /ops?scenario=<id>&pace=<s> preselects a scenario and run pace, and
 * ?profile=<name> the run profile (the worker view has no profile select, so this is how it runs
 * the API's local models instead of the recorded fixture results).
 * The plain worker view is the default; ?view=technical opens the full technical console.
 */
export default async function OpsPage({ searchParams }: PageProps<"/ops">) {
  const params = await searchParams;
  const mock = one(params.mock);
  const initialView = parseViewMode(one(params.view));
  if (mock !== undefined) {
    return <OpsMock initial={STATES.find((s) => s === mock) ?? "default"} initialView={initialView} />;
  }
  return (
    <OpsLive
      initialScenarioId={one(params.scenario) ?? null}
      paceS={parsePace(one(params.pace))}
      initialProfile={parseProfile(one(params.profile))}
      initialView={initialView}
    />
  );
}
