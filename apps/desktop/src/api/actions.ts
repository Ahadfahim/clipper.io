// Mutations. Every change goes through the core API (same services and guards the agents use).
import type { QueryClient } from "@tanstack/react-query";
import { api, unwrap, type Schemas } from "./client";
import { qk, useAction } from "./queries";

type Via = "dashboard";
const via: Via = "dashboard";
const reviewer = "you";

/* ---------------------------------------------------------------- system */

export function useControl() {
  return useAction({
    run: (v: { key: Schemas["ControlIn"]["key"]; value: unknown }) =>
      unwrap(api.POST("/api/control", { body: { key: v.key, value: v.value, via: "app" } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["StatusOut"]>(qk.status, (s) => (s ? { ...s, control: { ...s.control, [v.key]: v.value } } : s)),
    invalidate: () => [qk.status, qk.board, qk.overview],
  });
}

/** Show, hide or toggle Clipper's own Chrome for a profile (it runs hidden by default). */
export function useBrowserWindow() {
  return useAction({
    run: (v: { profile: string; action: "show" | "hide" | "toggle" }) =>
      unwrap(api.POST("/api/browser/profiles/{profile}/{action}", { params: { path: { profile: v.profile, action: v.action } } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["StatusOut"]>(qk.status, (s) =>
        s
          ? {
              ...s,
              browser: s.browser.map((b) =>
                b.name === v.profile ? { ...b, running: true, visible: v.action === "toggle" ? !b.visible : v.action === "show" } : b,
              ),
            }
          : s,
      ),
    invalidate: () => [qk.status],
  });
}

export type SwitchVars = {
  level: "marketplace" | "social" | "account";
  name: string;
  enabled: boolean;
  on_active?: "finish" | "pause";
  on_scheduled?: "cancel" | "keep";
};

function applySwitch(s: Schemas["SwitchesOut"] | undefined, v: SwitchVars): Schemas["SwitchesOut"] | undefined {
  if (!s) return s;
  if (v.level === "marketplace" && s.marketplaces[v.name])
    return { ...s, marketplaces: { ...s.marketplaces, [v.name]: { ...s.marketplaces[v.name]!, enabled: v.enabled } } };
  if (v.level === "social" && s.socials[v.name])
    return { ...s, socials: { ...s.socials, [v.name]: { ...s.socials[v.name]!, enabled: v.enabled } } };
  if (v.level === "account")
    return { ...s, accounts: s.accounts.map((a) => (String(a.id) === v.name ? { ...a, enabled: v.enabled } : a)) };
  return s;
}

export function useSwitch() {
  return useAction({
    run: (v: SwitchVars) =>
      unwrap(
        api.POST("/api/switches", {
          body: { on_active: "finish", on_scheduled: "keep", ...v, via: "app" },
        }),
      ),
    optimistic: (v, qc) => qc.setQueryData<Schemas["SwitchesOut"]>(qk.switches, (s) => applySwitch(s, v)),
    invalidate: () => [qk.switches, qk.status, qk.overview, qk.campaigns, qk.calendar, qk.accounts],
  });
}

export function useAnswer() {
  return useAction({
    run: (v: { questionId: number; answer: string }) =>
      unwrap(api.POST("/api/questions/{question_id}/answer", { params: { path: { question_id: v.questionId } }, body: { answer: v.answer, by: reviewer, via } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["OverviewOut"]>(qk.overview, (o) =>
        o
          ? { ...o, needs_you: o.needs_you.filter((n) => !(n.kind === "question" && n.actions.some((a) => a.args?.["question_id"] === v.questionId))) }
          : o,
      ),
    invalidate: () => [qk.overview, qk.questions, qk.status],
  });
}

export function useAddNote() {
  return useAction({
    run: (v: Schemas["NoteIn"]) => unwrap(api.POST("/api/notes", { body: v })),
    optimistic: (v, qc) => {
      const note: Schemas["NoteOut"] = {
        id: -Date.now(),
        author: "you",
        created_at: new Date().toISOString(),
        pinned: v.pinned ?? false,
        response: null,
        scope: v.scope,
        scope_id: v.scope_id ?? null,
        text: v.text,
      };
      if (v.scope === "global") qc.setQueryData<Schemas["OverviewOut"]>(qk.overview, (o) => (o ? { ...o, notes: [...o.notes, note] } : o));
      if (v.scope === "clip" && v.scope_id)
        qc.setQueryData<Schemas["EditState"]>(qk.edit(Number(v.scope_id)), (e) => (e ? { ...e, notes: [...e.notes, note] } : e));
    },
    invalidate: (v) => [qk.overview, qk.notes, ...(v.scope === "clip" && v.scope_id ? [qk.edit(Number(v.scope_id))] : [])],
  });
}

export function useDeleteNote() {
  return useAction({
    run: (id: number) => unwrap(api.DELETE("/api/notes/{note_id}", { params: { path: { note_id: id } } })),
    optimistic: (id, qc) => qc.setQueryData<Schemas["OverviewOut"]>(qk.overview, (o) => (o ? { ...o, notes: o.notes.filter((n) => n.id !== id) } : o)),
    invalidate: () => [qk.overview, qk.notes],
  });
}

/* ---------------------------------------------------------------- agents */

export function useDirectorChat() {
  return useAction({
    run: (text: string) => unwrap(api.POST("/api/agents/director/chat", { body: { text, via: "dashboard" } })),
    optimistic: (text, qc) =>
      qc.setQueryData<Schemas["AgentEventOut"][]>(qk.director, (m) => [
        ...(m ?? []),
        { id: -Date.now(), input: {}, output: {}, session_id: null, subagent: null, text, tool: null, ts: new Date().toISOString(), type: "user" },
      ]),
    invalidate: () => [qk.director],
  });
}

export const useInterrupt = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/agents/sessions/{session_id}/interrupt", { params: { path: { session_id: id } } })),
    invalidate: (id) => [qk.board, qk.session(id), qk.sessions],
  });

export const useNudge = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/agents/sessions/{session_id}/nudge", { params: { path: { session_id: id } } })),
    invalidate: (id) => [qk.board, qk.session(id)],
  });

export const useBump = () =>
  useAction({
    run: (v: { requestId: number; priority: number }) =>
      unwrap(api.POST("/api/agents/requests/{request_id}/bump", { params: { path: { request_id: v.requestId } }, body: { priority: v.priority } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["BoardOut"]>(qk.board, (b) =>
        b ? { ...b, queue: b.queue.map((q) => (q.request_id === v.requestId ? { ...q, priority: v.priority } : q)).sort((a, z) => a.priority - z.priority) } : b,
      ),
    invalidate: () => [qk.board],
  });

export const useCancelRequest = () =>
  useAction({
    run: (requestId: number) => unwrap(api.DELETE("/api/agents/requests/{request_id}", { params: { path: { request_id: requestId } } })),
    optimistic: (id, qc) => qc.setQueryData<Schemas["BoardOut"]>(qk.board, (b) => (b ? { ...b, queue: b.queue.filter((q) => q.request_id !== id) } : b)),
    invalidate: () => [qk.board],
  });

/* ---------------------------------------------------------------- campaigns */

function setCampaignStatus(qc: QueryClient, id: number, status: string) {
  qc.setQueryData<Schemas["CampaignRow"][]>(qk.campaigns, (rows) => rows?.map((r) => (r.id === id ? { ...r, status } : r)));
  qc.setQueryData<Schemas["OverviewOut"]>(qk.overview, (o) =>
    o ? { ...o, needs_you: o.needs_you.filter((n) => !(n.kind === "campaign" && n.actions.some((a) => a.args?.["campaign_id"] === id))) } : o,
  );
}

export const useTakeCampaign = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/campaigns/{campaign_id}/take", { params: { path: { campaign_id: id }, query: { via } } })),
    optimistic: (id, qc) => setCampaignStatus(qc, id, "active"),
    invalidate: (id) => [qk.campaigns, qk.campaign(id), qk.overview, qk.status],
  });

export const useSkipCampaign = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/campaigns/{campaign_id}/skip", { params: { path: { campaign_id: id }, query: { via } } })),
    optimistic: (id, qc) => setCampaignStatus(qc, id, "skipped"),
    invalidate: (id) => [qk.campaigns, qk.campaign(id), qk.overview, qk.status],
  });

export const usePauseCampaign = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/campaigns/{campaign_id}/pause", { params: { path: { campaign_id: id } } })),
    optimistic: (id, qc) => setCampaignStatus(qc, id, "paused"),
    invalidate: (id) => [qk.campaigns, qk.campaign(id), qk.overview],
  });

export const useSaveSpec = () =>
  useAction({
    run: (v: { id: number; spec: Schemas["ClipSpec"] }) =>
      unwrap(api.PUT("/api/campaigns/{campaign_id}/spec", { params: { path: { campaign_id: v.id } }, body: v.spec })),
    optimistic: (v, qc) => qc.setQueryData<Schemas["CampaignDetail"]>(qk.campaign(v.id), (d) => (d ? { ...d, spec: v.spec } : d)),
    invalidate: (v) => [qk.campaign(v.id)],
  });

export const useManualCampaign = () =>
  useAction({
    run: (v: Schemas["ManualCampaignIn"]) => unwrap(api.POST("/api/campaigns/manual", { body: v })),
    invalidate: () => [qk.campaigns, qk.overview],
  });

/* ---------------------------------------------------------------- review */

function patchReviewClip(qc: QueryClient, batchId: number, clipId: number, patch: Partial<Schemas["ReviewClip"]>) {
  qc.setQueryData<Schemas["BatchDetail"]>(qk.batch(batchId), (b) => {
    if (!b) return b;
    const clips = b.clips.map((c) => (c.clip.id === clipId ? { ...c, ...patch, clip: { ...c.clip, decision: patch.decision ?? c.clip.decision } } : c));
    const count = (d: string) => clips.filter((c) => c.decision === d).length;
    return { ...b, clips, batch: { ...b.batch, approved: count("approved"), rejected: count("rejected"), pending: count("pending") } };
  });
}

export type DecisionVars = {
  batchId: number;
  clipId: number;
  decision: "approved" | "rejected" | "pending";
  reason?: string | null;
  platforms?: string[] | null;
};

export const useDecide = () =>
  useAction({
    run: (v: DecisionVars) =>
      unwrap(
        api.POST("/api/review/clips/{clip_id}/decision", {
          params: { path: { clip_id: v.clipId } },
          body: { decision: v.decision, reason: v.reason ?? null, platforms: v.platforms ?? null, reviewer, via },
        }),
      ),
    optimistic: (v, qc) =>
      patchReviewClip(qc, v.batchId, v.clipId, {
        decision: v.decision,
        decision_reason: v.reason ?? null,
        reviewer,
        via,
        ...(v.platforms ? { platforms: v.platforms } : {}),
      }),
    invalidate: (v) => [qk.batch(v.batchId), qk.batches, qk.overview, qk.status, qk.clips],
  });

export const useCaption = () =>
  useAction({
    run: (v: { batchId: number; clipId: number; platform: "youtube" | "tiktok" | "instagram" | "x"; text: string }) =>
      unwrap(api.PUT("/api/review/clips/{clip_id}/caption", { params: { path: { clip_id: v.clipId } }, body: { platform: v.platform, text: v.text, via } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["BatchDetail"]>(qk.batch(v.batchId), (b) =>
        b ? { ...b, clips: b.clips.map((c) => (c.clip.id === v.clipId ? { ...c, captions: { ...c.captions, [v.platform]: v.text } } : c)) } : b,
      ),
    invalidate: (v) => [qk.batch(v.batchId)],
  });

export const useRecut = () =>
  useAction({
    run: (v: { batchId: number; clipId: number; start_delta: number; end_delta: number; layout: "crop" | "split" | "fit" | null; note: string | null }) =>
      unwrap(
        api.POST("/api/review/clips/{clip_id}/recut", {
          params: { path: { clip_id: v.clipId } },
          body: { start_delta: v.start_delta, end_delta: v.end_delta, layout: v.layout, note: v.note, via },
        }),
      ),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["BatchDetail"]>(qk.batch(v.batchId), (b) =>
        b ? { ...b, clips: b.clips.map((c) => (c.clip.id === v.clipId ? { ...c, clip: { ...c.clip, status: "recut" } } : c)) } : b,
      ),
    invalidate: (v) => [qk.batch(v.batchId), qk.clips],
  });

export const useApproveAll = () =>
  useAction({
    run: (v: { batchId: number; threshold: number }) =>
      unwrap(api.POST("/api/review/batches/{batch_id}/approve-all", { params: { path: { batch_id: v.batchId } }, body: { threshold: v.threshold, reviewer, via } })),
    optimistic: (v, qc) => {
      const b = qc.getQueryData<Schemas["BatchDetail"]>(qk.batch(v.batchId));
      for (const c of b?.clips ?? [])
        if (c.decision === "pending" && c.clip.score >= v.threshold) patchReviewClip(qc, v.batchId, c.clip.id, { decision: "approved", reviewer, via });
    },
    invalidate: (v) => [qk.batch(v.batchId), qk.batches, qk.overview, qk.status],
  });

export const useRejectRest = () =>
  useAction({
    run: (v: { batchId: number; reason: string }) =>
      unwrap(api.POST("/api/review/batches/{batch_id}/reject-rest", { params: { path: { batch_id: v.batchId } }, body: { reason: v.reason, reviewer, via } })),
    optimistic: (v, qc) => {
      const b = qc.getQueryData<Schemas["BatchDetail"]>(qk.batch(v.batchId));
      for (const c of b?.clips ?? [])
        if (c.decision === "pending") patchReviewClip(qc, v.batchId, c.clip.id, { decision: "rejected", decision_reason: v.reason, reviewer, via });
    },
    invalidate: (v) => [qk.batch(v.batchId), qk.batches, qk.overview, qk.status],
  });

export const useShip = () =>
  useAction({
    run: (batchId: number) => unwrap(api.POST("/api/review/batches/{batch_id}/ship", { params: { path: { batch_id: batchId } }, body: { reviewer, via } })),
    optimistic: (batchId, qc) =>
      qc.setQueryData<Schemas["BatchDetail"]>(qk.batch(batchId), (b) => (b ? { ...b, batch: { ...b.batch, status: "shipped" } } : b)),
    invalidate: (batchId) => [qk.batch(batchId), qk.batches, qk.overview, qk.status, qk.calendar],
  });

/* ---------------------------------------------------------------- edit */

export const useEditOp = () =>
  useAction({
    run: (v: { clipId: number; op: string; args: Record<string, unknown>; reason: string }) =>
      unwrap(api.POST("/api/edit/{clip_id}/ops", { params: { path: { clip_id: v.clipId } }, body: { op: v.op, args: v.args, reason: v.reason } })),
    invalidate: (v) => [qk.edit(v.clipId)],
  });

export const useUndo = () =>
  useAction({
    run: (v: { clipId: number; opId: number }) =>
      unwrap(api.POST("/api/edit/{clip_id}/undo", { params: { path: { clip_id: v.clipId } }, body: { op_id: v.opId } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["EditState"]>(qk.edit(v.clipId), (e) => (e ? { ...e, history: e.history.map((h) => (h.id === v.opId ? { ...h, undone: true } : h)) } : e)),
    invalidate: (v) => [qk.edit(v.clipId)],
  });

export const useTakeOver = () =>
  useAction({
    run: (v: { clipId: number; take: boolean }) =>
      v.take
        ? unwrap(api.POST("/api/edit/{clip_id}/take-over", { params: { path: { clip_id: v.clipId } } }))
        : unwrap(api.POST("/api/edit/{clip_id}/hand-back", { params: { path: { clip_id: v.clipId } } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["EditState"]>(qk.edit(v.clipId), (e) =>
        e ? { ...e, locked_by: v.take ? "user" : null, live_status: v.take ? null : e.live_status, live_range: v.take ? null : e.live_range } : e,
      ),
    invalidate: (v) => [qk.edit(v.clipId)],
  });

/* ---------------------------------------------------------------- publishing */

export const useResumeAccount = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/publishing/accounts/{account_id}/resume", { params: { path: { account_id: id } } })),
    optimistic: (id, qc) =>
      qc.setQueryData<Schemas["AccountOut"][]>(qk.accounts, (a) => a?.map((x) => (x.id === id ? { ...x, status: "active", paused_reason: null } : x))),
    invalidate: () => [qk.accounts, qk.switches, qk.overview, qk.calendar],
  });

export const useCancelPost = () =>
  useAction({
    run: (id: number) => unwrap(api.POST("/api/publishing/posts/{post_id}/cancel", { params: { path: { post_id: id } } })),
    optimistic: (id, qc) =>
      qc.setQueryData<Schemas["CalendarOut"]>(qk.calendar, (c) => (c ? { ...c, posts: c.posts.map((p) => (p.id === id ? { ...p, status: "cancelled" } : p)) } : c)),
    invalidate: () => [qk.calendar, qk.overview],
  });

export const useReschedule = () =>
  useAction({
    run: (v: { postId: number; at: string }) =>
      unwrap(api.POST("/api/publishing/posts/{post_id}/reschedule", { params: { path: { post_id: v.postId } }, body: { scheduled_at: v.at } })),
    optimistic: (v, qc) =>
      qc.setQueryData<Schemas["CalendarOut"]>(qk.calendar, (c) => (c ? { ...c, posts: c.posts.map((p) => (p.id === v.postId ? { ...p, scheduled_at: v.at } : p)) } : c)),
    invalidate: () => [qk.calendar, qk.overview],
  });

export const useTestRecipe = () =>
  useAction({
    run: (name: string) => unwrap(api.POST("/api/publishing/recipes/{name}/test", { params: { path: { name }, query: {} } })),
    invalidate: () => [qk.recipes],
  });

/* ---------------------------------------------------------------- settings */

export const usePatchSettings = () =>
  useAction({
    run: (values: Record<string, unknown>) => unwrap(api.PATCH("/api/settings", { body: { values } })),
    invalidate: () => [qk.settings],
  });

export const useSavePrompt = () =>
  useAction({
    run: (v: { name: string; text: string }) => unwrap(api.PUT("/api/settings/prompts/{name}", { params: { path: { name: v.name } }, body: { text: v.text } })),
    invalidate: () => [qk.prompts],
  });

export const useDeleteLesson = () =>
  useAction({
    run: (id: number) => unwrap(api.DELETE("/api/settings/lessons/{lesson_id}", { params: { path: { lesson_id: id } } })),
    optimistic: (id, qc) => qc.setQueryData<Schemas["LessonOut"][]>(qk.lessons, (l) => l?.filter((x) => x.id !== id)),
    invalidate: () => [qk.lessons],
  });

export const useEditLesson = () =>
  useAction({
    run: (v: { id: number; note: string }) =>
      unwrap(api.PATCH("/api/settings/lessons/{lesson_id}", { params: { path: { lesson_id: v.id } }, body: { note: v.note } })),
    optimistic: (v, qc) => qc.setQueryData<Schemas["LessonOut"][]>(qk.lessons, (l) => l?.map((x) => (x.id === v.id ? { ...x, note: v.note } : x))),
    invalidate: () => [qk.lessons],
  });

export const useSaveSecret = () =>
  useAction({
    run: (v: { name: string; value: string }) => unwrap(api.POST("/api/settings/secrets/{name}", { params: { path: { name: v.name } }, body: { value: v.value } })),
    invalidate: () => [qk.settings],
  });

export const useTrigger = () =>
  useAction({
    run: (name: "scout" | "analyst") => unwrap(api.POST("/api/agents/trigger/{name}", { params: { path: { name } } })),
    invalidate: () => [qk.board],
  });

export const useReplay = () =>
  useAction({
    run: (eventId: number) => unwrap(api.POST("/api/agents/events/{event_id}/replay", { params: { path: { event_id: eventId } } })),
  });

/** Run a failed or cancelled job again (Jobs panel). */
export function useRetryJob() {
  return useAction({
    run: (jobId: number) => unwrap(api.POST("/api/jobs/{job_id}/retry", { params: { path: { job_id: jobId } } })),
    invalidate: () => [qk.jobs, qk.status],
  });
}

/** Try a source's download again. */
export function useRetrySource(campaignId: number) {
  return useAction({
    run: (sourceId: number) => unwrap(api.POST("/api/sources/{source_id}/retry", { params: { path: { source_id: sourceId } } })),
    invalidate: () => [qk.campaign(campaignId), qk.jobs, qk.status],
  });
}

/** Use a video you downloaded yourself as a source's footage. */
export function useAttachFile(campaignId: number) {
  return useAction({
    run: (v: { sourceId: number; path: string }) =>
      unwrap(api.POST("/api/sources/{source_id}/file", { params: { path: { source_id: v.sourceId } }, body: { path: v.path } })),
    invalidate: () => [qk.campaign(campaignId), qk.jobs, qk.status, qk.overview, qk.questions],
  });
}

/** Set which model each agent runs on (applies to the next agent session). */
export function useSaveModels() {
  return useAction({
    run: (v: Schemas["ModelsIn"]) => unwrap(api.PUT("/api/agents/models", { body: v })),
    invalidate: () => [qk.models, qk.board],
  });
}

/** One tiny turn on the plan login: can this plan use the model? */
export function useTestModel() {
  return useAction({
    run: (model: string) => unwrap(api.POST("/api/agents/models/test", { body: { model } })),
    invalidate: () => [qk.models],
  });
}
