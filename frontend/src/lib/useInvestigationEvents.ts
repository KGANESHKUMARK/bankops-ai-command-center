import { useEffect, useRef, useState } from "react";
import { endpoints } from "../api/endpoints";
import { streamInvestigation, type StreamStatus } from "../api/sse";
import type { InvestigationEvent } from "../api/types";

const ACTIVE = new Set(["queued", "running"]);
const STATE_CHANGING = new Set(["step_completed", "step_failed", "status_change", "policy_decision", "action_executed", "approval_invalidated"]);

function merge(current: InvestigationEvent[], incoming: InvestigationEvent[]): InvestigationEvent[] {
  const bySeq = new Map(current.map((event) => [event.seq, event]));
  for (const event of incoming) bySeq.set(event.seq, event);
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

/**
 * Loads the full event history (JSON), then live-streams new events over SSE while the run is active.
 * `onStateChange` fires for events that change persisted investigation state, so callers can refetch.
 */
export function useInvestigationEvents(runId: string | undefined, status: string | undefined, onStateChange: () => void) {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("connecting");
  const lastSeq = useRef(0);
  const callback = useRef(onStateChange);

  useEffect(() => {
    callback.current = onStateChange;
  });

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    lastSeq.current = 0;
    setEvents([]);
    setHistoryLoaded(false);
    (async () => {
      let after = 0;
      for (let page = 0; page < 25; page++) {
        const result = await endpoints.investigationEvents(runId, after);
        if (cancelled) return;
        if (result.events.length) {
          after = result.last_seq;
          lastSeq.current = after;
          setEvents((current) => merge(current, result.events));
        }
        if (result.events.length < 200) break;
      }
      setHistoryLoaded(true);
    })().catch(() => {
      if (!cancelled) {
        setStreamStatus("error");
        setHistoryLoaded(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const active = ACTIVE.has(status ?? "");
  useEffect(() => {
    if (!runId || !historyLoaded) return;
    if (!active) {
      setStreamStatus("ended");
      return;
    }
    return streamInvestigation({
      investigationId: runId,
      afterSeq: lastSeq.current,
      onEvent: (event) => {
        lastSeq.current = Math.max(lastSeq.current, event.seq);
        setEvents((current) => merge(current, [event]));
        if (STATE_CHANGING.has(event.event_type)) callback.current();
      },
      onEnd: () => callback.current(),
      onStatus: setStreamStatus,
    });
  }, [runId, active, historyLoaded]);

  return { events, streamStatus, historyLoaded };
}
