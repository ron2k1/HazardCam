import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { HazardsApp, type HazardsMock } from "@/components/hazards/hazards-app";

export const metadata: Metadata = {
  title: "Safety hazards · CameraVision",
};

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

function parseMock(v: string | undefined): HazardsMock | null {
  if (v === undefined) return null;
  return v === "empty" ? "empty" : "default";
}

/**
 * /hazards: the safety check screen. ?clip=<id> picks the camera; ?job=<id> attaches to an existing
 * check (no automatic check). The technical view lives in its own tab, /hazards/process, so
 * ?view=technical goes there. ?mock[=1|empty] is development data only.
 */
export default async function HazardsPage({ searchParams }: PageProps<"/hazards">) {
  const params = await searchParams;
  const clip = one(params.clip) ?? null;
  const job = one(params.job) ?? null;
  if (one(params.view) === "technical") {
    const q = new URLSearchParams();
    if (clip) q.set("clip", clip);
    if (job) q.set("job", job);
    redirect(`/hazards/process${q.size ? `?${q.toString()}` : ""}`);
  }
  return <HazardsApp mock={parseMock(one(params.mock))} initialClipId={clip} initialJobId={job} />;
}
