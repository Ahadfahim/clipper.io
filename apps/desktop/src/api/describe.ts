// Human-readable one-liners for bus events (Activity tab, Problems tab, toasts).
import { MARKET_LABEL, PLATFORM_LABEL } from "@/lib/platforms";
import type { Schemas } from "./client";

export type Tone = "agent" | "ok" | "warn" | "bad" | "accent" | "muted";
export type Described = { source: string; text: string; tone: Tone; problem: boolean; agentOutput: boolean };

type P = Record<string, unknown>;
const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const shortTool = (t: unknown) => str(t).replace(/^mcp__/, "").replace("__", ".");

export function describeEvent(ev: Pick<Schemas["EventOut"], "type" | "payload">): Described {
  const p = ev.payload as P;
  const d = (source: string, text: string, tone: Tone, extra: Partial<Described> = {}): Described => ({
    source,
    text,
    tone,
    problem: false,
    agentOutput: false,
    ...extra,
  });
  switch (ev.type) {
    case "agent.event": {
      const kind = str(p["kind"]);
      if (kind === "blocked") return d("guard", `Blocked ${shortTool(p["tool"])} · ${str(p["summary"]).replace(/^\[[^\]]+\]\s*/, "")}`, "bad", { problem: true, agentOutput: true });
      const tool = p["tool"] ? `${shortTool(p["tool"])} · ` : "";
      return d(`session/${str(p["session_id"])}`, `${tool}${str(p["summary"])}`, "agent", { agentOutput: true });
    }
    case "agent.log":
      return d("agent", str(p["text"]), "agent", { agentOutput: true });
    case "agent.session":
      return d(str(p["role"]), `Session ${str(p["session_id"])} ${str(p["status"])}`, "agent", { agentOutput: true });
    case "job.queued":
      return d("jobs", `Queued ${str(p["kind"])} (job ${str(p["job_id"])})`, "muted");
    case "job.progress":
      return d("jobs", `${str(p["kind"])} ${Math.round(Number(p["progress"] ?? 0) * 100)}% (job ${str(p["job_id"])})`, "muted");
    case "job.done": {
      const failed = p["status"] === "failed";
      return d("jobs", failed ? `${str(p["kind"])} failed: ${str(p["error"])}` : `${str(p["kind"])} ${str(p["status"])} (job ${str(p["job_id"])})`, failed ? "bad" : "ok", {
        problem: failed,
      });
    }
    case "review.batch_posted":
      return d("review", `Batch ${str(p["batch_id"])} ready: ${(p["clip_ids"] as unknown[] | undefined)?.length ?? 0} clips`, "warn");
    case "review.decided": {
      const via = p["via"] === "discord" ? " (Discord)" : "";
      const reason = p["reason"] ? ` · ${str(p["reason"]).replace(/_/g, " ")}` : "";
      return d("review", `Clip ${str(p["clip_id"])} ${str(p["decision"])}${via}${reason}`, p["decision"] === "rejected" ? "bad" : "accent");
    }
    case "review.shipped":
      return d("review", `Shipped batch ${str(p["batch_id"])}: ${(p["approved"] as unknown[] | undefined)?.length ?? 0} approved`, "ok");
    case "recut.requested":
      return d("review", `Re-cut requested for clip ${str(p["clip_id"])}`, "accent");
    case "caption.edited":
      return d("review", `Caption edited (${str(p["platform"])}) on clip ${str(p["clip_id"])}`, "muted");
    case "clip.updated":
      return d("clips", `Clip ${str(p["clip_id"])} → ${str(p["status"])}`, "muted");
    case "post.scheduled":
      return d(`publish/${str(p["platform"])}`, `Scheduled clip ${str(p["clip_id"])}${p["dry_run"] ? " (dry run)" : ""}`, "muted");
    case "post.status": {
      const bad = p["status"] === "failed" || p["status"] === "blocked";
      return d("publish", `Post ${str(p["post_id"])} ${str(p["status"])}${p["error"] ? `: ${str(p["error"])}` : ""}`, bad ? "bad" : "muted", { problem: bad });
    }
    case "post.live":
      return d(`publish/${str(p["platform"])}`, `Posted clip ${str(p["clip_id"])}${p["dry_run"] ? " (dry run)" : ""} · ${str(p["url"])}`, "ok");
    case "submission.status":
      return d("marketplace", `Submission for post ${str(p["post_id"])}: ${str(p["status"])}`, "muted");
    case "account.paused":
      return d("publish", `Account ${str(p["account_id"])} paused: ${str(p["reason"])}`, "bad", { problem: true });
    case "campaign.found":
      return d("scout", `Found campaign ${str(p["campaign_id"])} on ${str(p["marketplace"])}${p["score"] ? `, score ${str(p["score"])}` : ""}`, "agent");
    case "campaign.taken":
      return d("campaigns", `Took campaign ${str(p["campaign_id"])} (${str(p["via"])})`, "accent");
    case "campaign.skipped":
      return d("campaigns", `Skipped campaign ${str(p["campaign_id"])}`, "muted");
    case "campaign.updated":
      return d("campaigns", `Campaign ${str(p["campaign_id"])} updated`, "muted");
    case "campaign.ending":
      return d("campaigns", `Campaign ${str(p["campaign_id"])} ending: ${str(p["reason"])}`, "warn");
    case "spec.updated":
      return d("campaigns", `Spec updated for campaign ${str(p["campaign_id"])}`, "accent");
    case "question.asked":
      return d("question", str(p["text"]), "agent");
    case "question.answered":
      return d("question", `Answered: ${str(p["answer"])}`, "accent");
    case "toggles.changed":
      return d("switches", `${MARKET_LABEL[str(p["name"])] ?? PLATFORM_LABEL[str(p["name"])] ?? str(p["name"])} turned ${p["enabled"] ? "on" : "off"} (${str(p["via"])})`, "accent");
    case "control.changed":
      return d("control", `${str(p["key"]).replace("_", " ")} → ${str(p["value"])} (${str(p["via"])})`, "accent");
    case "note.added":
      return d("notes", `Note (${str(p["scope"])}): ${str(p["text"])}`, "accent");
    case "user.chat":
      return d("you", str(p["text"]), "accent");
    case "alert": {
      const level = str(p["level"]);
      return d(str(p["source"]) || "alert", str(p["text"]), level === "error" ? "bad" : level === "warning" ? "warn" : "muted", {
        problem: level !== "info",
      });
    }
    case "report":
      return d(str(p["source"]) || "report", "New report", "agent");
    case "edit.op":
      return d(`edit/${str(p["clip_id"])}`, `${str(p["actor"]).startsWith("session") ? "Claude" : "You"}: ${str(p["op"]).replace(/_/g, " ")}${p["reason"] ? ` · ${str(p["reason"])}` : ""}`, "agent", { agentOutput: true });
    case "edit.status":
      return d(`edit/${str(p["clip_id"])}`, str(p["text"]), "agent", { agentOutput: true });
    case "agenda.updated":
      return d("agenda", `Agenda updated (${str(p["scope"])})`, "muted");
    case "wakeup.due":
      return d("supervisor", `Wake-up: ${str(p["reason"])}`, "muted");
    case "watchdog.nudge":
      return d("watchdog", `Nudged campaign ${str(p["campaign_id"])} after ${Math.round(Number(p["idle_minutes"] ?? 0))}m idle`, "warn");
    case "trigger.fired":
      return d("supervisor", `${str(p["name"])} run started`, "muted");
    case "usage.updated":
      return d("usage", `Claude usage ${Math.round(Number(p["utilization"] ?? 0) * 100)}%${p["rate_limited"] ? " · rate limited" : ""}`, p["rate_limited"] ? "warn" : "muted", {
        problem: Boolean(p["rate_limited"]),
      });
    default:
      return d(ev.type, JSON.stringify(p).slice(0, 160), "muted");
  }
}

export const TONE_VAR: Record<Tone, string> = {
  agent: "var(--agent)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  bad: "var(--bad)",
  accent: "var(--accent)",
  muted: "var(--muted)",
};
