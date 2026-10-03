import type { Metadata } from "next";

import { HazardsApp, type HazardsMock } from "@/components/hazards/hazards-app";
import { parseViewMode } from "@/lib/view-mode";

export const metadata: Metadata = {
  title: "Safety hazards · CameraVision",
};

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

function parseMock(v: string | undefined): HazardsMock | null {
  if (v === undefined) return null;
  return v === "empty" ? "empty" : "default";
}

/**
 * /hazards is the single-camera safety hazard review. /hazards?mock[=1|empty] renders the real
 * teammate example from src/mocks/hazards without the API; ?clip=<id> preselects a clip. The plain
 * worker view is the default; ?view=technical shows the raw report, prompts and model metadata.
 */
export default async function HazardsPage({ searchParams }: PageProps<"/hazards">) {
  const params = await searchParams;
  return (
    <HazardsApp
      mock={parseMock(one(params.mock))}
      initialView={parseViewMode(one(params.view))}
      initialClipId={one(params.clip) ?? null}
    />
  );
}
