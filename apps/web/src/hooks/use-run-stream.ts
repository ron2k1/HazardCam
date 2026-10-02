"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { apiUrl, LIVE } from "@/lib/config";
import { parseEnvelope, TERMINAL_EVENT_TYPES, type RunResponse } from "@/lib/contracts";
import { applyEvent, EMPTY_RUN_VIEW, type RunView } from "@/lib/run-view";

/**
 * idle: no run · connecting/open: first connect / receiving · reconnecting: the browser
 * (Last-Event-ID) or we (?after_seq) are resuming · closed: terminal event seen · lost: gave up.
 */
export type StreamStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "lost";

function withAfterSeq(url: string, seq: number): string {
  return `${url}${url.includes("?") ? "&" : "?"}after_seq=${seq}`;
}

/**
 * One EventSource per run, outside React state so handlers never see stale closures.
 * Envelopes go through the pure reducer, which drops seq <= lastSeq, so a resumed stream
 * that replays events it already delivered is harmless.
 */
function createStreamController(
  setView: Dispatch<SetStateAction<RunView>>,
  setStatus: Dispatch<SetStateAction<StreamStatus>>,
) {
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let eventsUrl: string | null = null;
  let lastSeq = 0;
  let retries = 0;

  const stop = () => {
    source?.close();
    source = null;
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };

  const connect = () => {
    if (!eventsUrl) return;
    const es = new EventSource(apiUrl(lastSeq > 0 ? withAfterSeq(eventsUrl, lastSeq) : eventsUrl));
    source = es;
    es.onopen = () => {
      if (source !== es) return;
      retries = 0;
      setStatus("open");
    };
    // The API sends unnamed events only, so onmessage sees all of them.
    es.onmessage = (e: MessageEvent<string>) => {
      if (source !== es) return;
      const env = parseEnvelope(e.data);
      if (!env) return;
      lastSeq = Math.max(lastSeq, env.seq);
      setView((v) => applyEvent(v, env));
      if (TERMINAL_EVENT_TYPES.has(env.type)) {
        // The server closes after a terminal event; close first so the browser does not reconnect.
        stop();
        setStatus("closed");
      }
    };
    es.onerror = () => {
      if (source !== es) return;
      // CONNECTING: the browser retries on its own and sends Last-Event-ID.
      if (es.readyState === EventSource.CONNECTING) {
        setStatus("reconnecting");
        return;
      }
      // CLOSED: the browser gave up (HTTP error or a non-SSE reply). Resume from lastSeq ourselves.
      stop();
      if (retries >= LIVE.streamMaxRetries) {
        setStatus("lost");
        setView((v) =>
          v.phase === "running" || v.phase === "queued"
            ? {
                ...v,
                phase: "failed",
                failure: { stage: "event_stream", error: `stream lost after ${retries} reconnects; server run state unknown` },
              }
            : v,
        );
        return;
      }
      const delay = LIVE.streamRetryBaseMs * 2 ** retries;
      retries += 1;
      setStatus("reconnecting");
      timer = setTimeout(connect, delay);
    };
  };

  return {
    start(run: RunResponse) {
      stop();
      eventsUrl = run.events_url;
      lastSeq = 0;
      retries = 0;
      setView({
        ...EMPTY_RUN_VIEW,
        runId: run.run_id,
        scenarioId: run.scenario_id,
        profile: run.profile,
        phase: "queued",
      });
      setStatus("connecting");
      connect();
    },
    reset() {
      stop();
      eventsUrl = null;
      lastSeq = 0;
      setView(EMPTY_RUN_VIEW);
      setStatus("idle");
    },
    stop,
  };
}

export type StreamController = ReturnType<typeof createStreamController>;

/** Live run state reduced from GET /api/runs/{id}/events. */
export function useRunStream(): { view: RunView; status: StreamStatus; stream: StreamController } {
  const [view, setView] = useState<RunView>(EMPTY_RUN_VIEW);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [stream] = useState(() => createStreamController(setView, setStatus));
  useEffect(() => () => stream.stop(), [stream]);
  return { view, status, stream };
}
