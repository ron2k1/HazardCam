"use client";

import { useViewMode, type ViewMode } from "@/hooks/use-view-mode";

import { OpsConsole, type OpsConsoleProps } from "./ops-console";
import { ViewToggle } from "./view-toggle";
import { WorkerView } from "./worker-view";

export interface OpsScreenProps extends OpsConsoleProps {
  /** ?view= as the server read it, so the first render matches; null = no param. */
  initialView: ViewMode | null;
}

/**
 * /ops picks its view here: the plain worker view by default, or the full technical console
 * behind the "Technical details" switch (?view=technical). Both render the same props, so the
 * live and mock containers stay unaware of the choice; only the view on screen is mounted.
 */
export function OpsScreen({ initialView, ...props }: OpsScreenProps) {
  const [mode, setMode] = useViewMode(initialView);
  if (mode === "technical") {
    return <OpsConsole {...props} headerAction={<ViewToggle mode={mode} onChange={setMode} size="compact" />} />;
  }
  return <WorkerView {...props} onViewChange={setMode} />;
}
