import type { Metadata } from "next";

import { LeadAgent } from "@/components/hazards/lead-agent";
import { ProcessApp } from "@/components/hazards/process-app";

export const metadata: Metadata = {
  title: "Reasoning and process · CameraVision",
};

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/**
 * /hazards/process?clip=<id>[&job=<job_id>]: the reasoning and process behind a safety check, in
 * its own tab. Without job it attaches to the camera's latest check.
 */
export default async function ProcessPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const site = one(params.site);
  if (site) {
    // ?site=<site_run_id>: the lead agent's run and links to its six checkers' process pages.
    return (
      <main className="min-h-dvh bg-bg p-4 lg:p-6">
        <LeadAgent siteRunId={site} />
      </main>
    );
  }
  return <ProcessApp clipId={one(params.clip) ?? null} jobId={one(params.job) ?? null} />;
}
