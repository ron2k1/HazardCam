import type { Metadata } from "next";

import { OpsMock, type OpsMockState } from "@/components/ops/ops-mock";

export const metadata: Metadata = {
  title: "OPS · AMBIENT MIRROR",
};

const STATES: readonly OpsMockState[] = ["default", "abstain", "idle"];

export default async function OpsPage({ searchParams }: PageProps<"/ops">) {
  const { mock } = await searchParams;
  const initial = STATES.find((s) => s === mock) ?? "default";
  return <OpsMock initial={initial} />;
}
