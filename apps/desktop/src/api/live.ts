// Live updates: one WebSocket to /api/ws streams bus events; each event refreshes the cached
// queries it affects and lands in the output panel's ring buffer. Fixture mode replays the
// exported event log instead (no socket).
import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect } from "react";
import { create } from "zustand";
import { toast } from "@/lib/tauri";
import { API_BASE, api, FIXTURE_MODE, unwrap, type Schemas } from "./client";
import { describeEvent } from "./describe";
import { qk } from "./queries";

export type LiveEvent = Schemas["EventOut"];
export type ConnState = "connecting" | "open" | "closed" | "fixture";

const MAX_EVENTS = 500;

type LiveStore = {
  events: LiveEvent[];
  lastId: number;
  conn: ConnState;
  editStatus: Record<number, { text: string; range: number[] | null; actor: string; ts: string } | undefined>;
  push: (evs: LiveEvent[]) => void;
  setConn: (c: ConnState) => void;
};

export const useLive = create<LiveStore>()((set) => ({
  events: [],
  lastId: 0,
  conn: FIXTURE_MODE ? "fixture" : "connecting",
  editStatus: {},
  push: (evs) =>
    set((s) => {
      const fresh = evs.filter((e) => e.id > s.lastId);
      if (!fresh.length) return s;
      const editStatus = { ...s.editStatus };
      for (const e of fresh) {
        if (e.type === "edit.status") {
          const p = e.payload as { clip_id: number; text: string; range: number[] | null; actor: string };
          editStatus[p.clip_id] = { text: p.text, range: p.range, actor: p.actor, ts: e.ts };
        }
      }
      return {
        events: [...s.events, ...fresh].slice(-MAX_EVENTS),
        lastId: fresh[fresh.length - 1]!.id,
        editStatus,
      };
    }),
  setConn: (conn) => set({ conn }),
}));

/** Query keys an event makes stale. Kept as data so it's testable (live.test.ts). */
export function keysFor(ev: Pick<LiveEvent, "type" | "payload">): QueryKey[] {
  const p = ev.payload as Record<string, unknown>;
  const num = (k: string) => (typeof p[k] === "number" ? (p[k] as number) : undefined);
  const campaign = num("campaign_id");
  const clip = num("clip_id");
  const batch = num("batch_id");
  const session = num("session_id");
  const withC = (keys: QueryKey[]) => (campaign !== undefined ? [...keys, qk.campaign(campaign)] : keys);
  const t = ev.type;
  if (t === "agent.event" || t === "agent.session" || t === "agent.log")
    return [qk.board, qk.sessions, ...(session !== undefined ? [qk.session(session)] : []), ...(t === "agent.session" ? [qk.director] : [])];
  if (t.startsWith("job.")) return withC([qk.jobs, qk.status, ...(t === "job.done" ? [qk.clips, qk.overview] : [])]);
  if (t === "clip.updated" || t === "review.preview_replaced")
    return withC([qk.clips, ...(clip !== undefined ? [qk.clip(clip), qk.edit(clip)] : []), qk.batches, ...(batch !== undefined ? [qk.batch(batch)] : [])]);
  if (t.startsWith("review.") || t === "caption.edited" || t === "recut.requested")
    return withC([qk.batches, ...(batch !== undefined ? [qk.batch(batch)] : []), qk.overview, qk.status, qk.clips, qk.autoApprove]);
  if (t.startsWith("post.") || t === "submission.status" || t === "account.paused")
    return withC([qk.calendar, qk.accounts, qk.overview, qk.status, qk.earnings, qk.switches]);
  if (t.startsWith("campaign.") || t === "spec.updated") return withC([qk.campaigns, qk.overview, qk.status]);
  if (t.startsWith("question.")) return [qk.questions, qk.overview, qk.status];
  if (t === "toggles.changed" || t === "control.changed") return [qk.switches, qk.status, qk.overview, qk.board, qk.campaigns, qk.accounts];
  if (t === "edit.op") return clip !== undefined ? [qk.edit(clip), qk.clip(clip)] : [];
  if (t === "agenda.updated" || t === "note.added")
    return [qk.overview, qk.notes, ...(p["scope"] === "clip" && p["scope_id"] ? [qk.edit(Number(p["scope_id"]))] : [])];
  if (t === "usage.updated") return [qk.status, qk.board];
  if (t === "user.chat") return [qk.director];
  if (t === "alert") return [qk.overview];
  return [];
}

function makeInvalidator(qc: QueryClient) {
  const pending = new Map<string, QueryKey>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  return (keys: QueryKey[]) => {
    for (const k of keys) pending.set(JSON.stringify(k), k);
    timer ??= setTimeout(() => {
      for (const k of pending.values()) void qc.invalidateQueries({ queryKey: k });
      pending.clear();
      timer = null;
    }, 200);
  };
}

function notifyFor(ev: LiveEvent): void {
  if (ev.type === "review.batch_posted") {
    const n = (ev.payload as { clip_ids?: unknown[] }).clip_ids?.length ?? 0;
    void toast("Clips ready for review", `${n} clips are waiting in Review`);
  } else if (ev.type === "alert" || ev.type === "account.paused") {
    const d = describeEvent(ev);
    if (d.problem) void toast(d.source, d.text);
  }
}

export function wsUrl(after: number): string {
  const base = API_BASE.replace(/^http/, "ws");
  return `${base}/api/ws?after=${after}`;
}

/** Mount once (in the shell). Opens the socket, reconnects with backoff, resumes after the last id. */
export function useLiveEvents(): void {
  const qc = useQueryClient();
  useEffect(() => {
    const store = useLive.getState();
    if (FIXTURE_MODE) {
      void unwrap(api.GET("/api/events", { params: { query: { after: 0 } } })).then((evs) => store.push(evs));
      return;
    }
    const invalidate = makeInvalidator(qc);
    let socket: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let retry: ReturnType<typeof setTimeout> | null = null;

    // backlog for the output panel (last 200), then the live stream picks up from there
    const connect = () => {
      if (stopped) return;
      useLive.getState().setConn("connecting");
      socket = new WebSocket(wsUrl(useLive.getState().lastId));
      socket.onopen = () => {
        attempt = 0;
        useLive.getState().setConn("open");
      };
      socket.onmessage = (msg) => {
        const ev = JSON.parse(String(msg.data)) as LiveEvent | { type: "ping" };
        if (ev.type === "ping" || !("id" in ev)) return;
        useLive.getState().push([ev]);
        invalidate(keysFor(ev));
        notifyFor(ev);
      };
      socket.onclose = () => {
        useLive.getState().setConn("closed");
        if (stopped) return;
        attempt += 1;
        retry = setTimeout(connect, Math.min(15_000, 500 * 2 ** attempt));
      };
    };
    void unwrap(api.GET("/api/events", { params: { query: { latest: true, limit: 200 } } }))
      .then((evs) => useLive.getState().push(evs))
      .catch(() => undefined)
      .finally(connect);
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, [qc]);
}
