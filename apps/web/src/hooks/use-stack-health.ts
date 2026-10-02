"use client";

import { useEffect, useState } from "react";

import type { ApiStatus } from "@/components/ops/stack-health-panel";
import { api, describeError } from "@/lib/api";
import { LIVE } from "@/lib/config";
import type { ModelsHealth, ServiceHealth } from "@/lib/contracts";

export interface StackHealth {
  apiStatus: ApiStatus;
  /** API row detail: version + scenario count, failing dependencies, or why it is offline. */
  apiDetail: string | null;
  service: ServiceHealth | null;
  /** GET /api/models/health for `profile`; null while offline or not loaded. */
  models: ModelsHealth | null;
}

function serviceDetail(h: ServiceHealth): string {
  const failing = Object.entries(h.dependencies)
    .filter(([, d]) => !d.ok)
    .map(([k]) => k);
  const scenarios = h.dependencies.manifests_dir?.scenario_count;
  return [
    `v${h.version}`,
    typeof scenarios === "number" ? `${scenarios} scenarios` : null,
    failing.length ? `failing ${failing.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/**
 * Polls GET /healthz (cheap, local). Models health is fetched when the profile changes or
 * the API comes back, never on a timer: for a non-fixture profile it probes model servers.
 */
export function useStackHealth(profile: string): StackHealth {
  const [service, setService] = useState<ServiceHealth | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [models, setModels] = useState<{ profile: string; data: ModelsHealth | null } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      let up = false;
      try {
        const h = await api.serviceHealth(ctrl.signal);
        setService(h);
        setOffline(null);
        up = true;
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setService(null);
        setOffline(`${describeError(err)} · retry ${LIVE.offlinePollMs / 1000}s`);
      }
      setChecked(true);
      timer = setTimeout(tick, up ? LIVE.healthPollMs : LIVE.offlinePollMs);
    };
    void tick();
    return () => {
      ctrl.abort();
      if (timer !== null) clearTimeout(timer);
    };
  }, []);

  const online = service !== null;
  useEffect(() => {
    if (!online) return;
    const ctrl = new AbortController();
    api.modelsHealth(profile, ctrl.signal).then(
      (data) => setModels({ profile, data }),
      () => {
        if (!ctrl.signal.aborted) setModels({ profile, data: null });
      },
    );
    return () => ctrl.abort();
  }, [profile, online]);

  const apiStatus: ApiStatus = !checked ? "checking" : !service ? "offline" : service.status === "ok" ? "online" : "degraded";
  return {
    apiStatus,
    apiDetail: service ? serviceDetail(service) : offline,
    service,
    models: online && models?.profile === profile ? models.data : null,
  };
}
