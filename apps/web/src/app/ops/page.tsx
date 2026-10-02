import type { Metadata } from "next";

import { OpsLive } from "@/components/ops/ops-live";
import { OpsMock, type OpsMockState } from "@/components/ops/ops-mock";
import { LIVE } from "@/lib/config";

export const metadata: Metadata = {
  title: "OPS · AMBIENT MIRROR",
};

const STATES: readonly OpsMockState[] = ["default", "abstain", "idle"];

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

function parsePace(v: string | undefined): number | null {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(Math.max(n, 0), LIVE.maxPaceS) : null;
}

/**
 * /ops is the live console. /ops?mock[=default|abstain|idle] replays contracts/examples
 * offline (design checks); /ops?scenario=<id>&pace=<s> preselects a scenario and run pace.
 */
export default async function OpsPage({ searchParams }: PageProps<"/ops">) {
  const params = await searchParams;
  const mock = one(params.mock);
  if (mock !== undefined) {
    return <OpsMock initial={STATES.find((s) => s === mock) ?? "default"} />;
  }
  return <OpsLive initialScenarioId={one(params.scenario) ?? null} paceS={parsePace(one(params.pace))} />;
}
