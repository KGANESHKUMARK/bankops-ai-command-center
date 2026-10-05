/**
 * Investigation progress over Server-Sent Events.
 *
 * The native EventSource API cannot send an Authorization header, and putting bearer tokens in URLs leaks
 * them into logs. This reader uses fetch() streaming instead, resumes with `Last-Event-ID` after network
 * errors (bounded exponential backoff), and falls back to JSON polling if streaming keeps failing.
 */
import { API_BASE, getToken, notifyUnauthorized } from "./client";
import type { InvestigationEvent } from "./types";

export type StreamStatus = "connecting" | "live" | "reconnecting" | "polling" | "ended" | "error";

export interface SseMessage {
  id: string | null;
  event: string;
  data: string;
}

/** Parse one SSE block (lines separated by \n, block terminated by a blank line). */
export function parseSseBlock(block: string): SseMessage | null {
  let id: string | null = null;
  let event = "message";
  const data: string[] = [];
  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(":")) continue;
    const colon = rawLine.indexOf(":");
    const field = colon === -1 ? rawLine : rawLine.slice(0, colon);
    const value = colon === -1 ? "" : rawLine.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length && id === null && event === "message") return null;
  return { id, event, data: data.join("\n") };
}

export interface StreamOptions {
  investigationId: string;
  afterSeq: number;
  onEvent: (event: InvestigationEvent) => void;
  onEnd: (status: string) => void;
  onStatus: (status: StreamStatus) => void;
  maxRetries?: number;
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });

export function streamInvestigation(options: StreamOptions): () => void {
  const controller = new AbortController();
  const { signal } = controller;
  const maxRetries = options.maxRetries ?? 5;
  let lastSeq = options.afterSeq;
  let failures = 0;

  const deliver = (event: InvestigationEvent) => {
    if (event.seq > lastSeq) {
      lastSeq = event.seq;
      options.onEvent(event);
    }
  };

  const poll = async () => {
    options.onStatus("polling");
    while (!signal.aborted) {
      try {
        const res = await fetch(`${API_BASE}/investigations/${encodeURIComponent(options.investigationId)}/events?after=${lastSeq}`, {
          headers: { Accept: "application/json", Authorization: `Bearer ${getToken() ?? ""}` },
          signal,
        });
        if (res.status === 401) {
          notifyUnauthorized();
          return;
        }
        if (res.ok) {
          const page = (await res.json()) as { status: string; events: InvestigationEvent[] };
          page.events.forEach(deliver);
          if (!page.events.length && ["completed", "failed", "cancelled", "awaiting_approval", "interrupted"].includes(page.status)) {
            options.onStatus("ended");
            options.onEnd(page.status);
            return;
          }
        }
      } catch {
        if (signal.aborted) return;
      }
      await sleep(2000, signal);
    }
  };

  const run = async () => {
    while (!signal.aborted) {
      options.onStatus(failures ? "reconnecting" : "connecting");
      try {
        const res = await fetch(`${API_BASE}/investigations/${encodeURIComponent(options.investigationId)}/events`, {
          headers: { Accept: "text/event-stream", Authorization: `Bearer ${getToken() ?? ""}`, "Last-Event-ID": String(lastSeq) },
          signal,
        });
        if (res.status === 401) {
          notifyUnauthorized();
          options.onStatus("error");
          return;
        }
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
        options.onStatus("live");
        failures = 0;
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const message = parseSseBlock(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
            if (!message) continue;
            if (message.event === "investigation_event") deliver(JSON.parse(message.data) as InvestigationEvent);
            else if (message.event === "end") {
              options.onStatus("ended");
              options.onEnd((JSON.parse(message.data) as { status: string }).status);
              await reader.cancel().catch(() => undefined);
              return;
            } else if (message.event === "auth_expired") {
              notifyUnauthorized();
              options.onStatus("error");
              return;
            }
          }
        }
        // Server closed the stream without an end event (e.g. periodic `reconnect`): reconnect from lastSeq.
      } catch {
        if (signal.aborted) return;
        failures += 1;
        if (failures > maxRetries) {
          await poll();
          return;
        }
        await sleep(Math.min(8000, 400 * 2 ** failures), signal);
      }
    }
  };

  void run();
  return () => controller.abort();
}
