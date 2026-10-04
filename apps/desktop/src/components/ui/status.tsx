import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { titleCase } from "@/lib/format";

export type StatusTone = "ok" | "warn" | "bad" | "agent" | "accent" | "muted" | "off";

export const TONE_BG: Record<StatusTone, string> = {
  ok: "bg-ok",
  warn: "bg-warn-strong",
  bad: "bg-bad",
  agent: "bg-agent",
  accent: "bg-accent",
  muted: "bg-muted",
  off: "bg-faint",
};

export const TONE_TEXT: Record<StatusTone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  agent: "text-agent",
  accent: "text-accent",
  muted: "text-muted",
  off: "text-faint",
};

/** Small status dot. Color is never the only signal: always pair it with a word. */
export function Dot({ tone, className, pulse }: { tone: StatusTone; className?: string; pulse?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-block size-2 shrink-0 rounded-full", TONE_BG[tone], pulse && "animate-pulse", className)}
    />
  );
}

export function StatusText({ tone, children, className }: { tone: StatusTone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <Dot tone={tone} />
      <span className={cn(tone === "muted" || tone === "off" ? "text-muted" : "")}>{children}</span>
    </span>
  );
}

/** running / paused / blocked / dry run / waiting: a dot plus a label (UI.md StatusPill). */
export function StatusPill({ status, className }: { status: string; className?: string }) {
  const s = status.toLowerCase();
  const tone: StatusTone =
    s === "running" || s === "active" || s === "live" || s === "approved" || s === "ok" || s === "done" || s === "connected" || s === "posted" || s === "simulated"
      ? "ok"
      : s.includes("dry") || s === "paused" || s === "waiting" || s === "pending" || s === "in_review" || s === "needs_user" || s === "suggested" || s === "scheduled" || s === "queued" || s === "warn"
        ? "warn"
        : s === "blocked" || s === "failed" || s === "rejected" || s === "error" || s === "fail" || s.includes("challenge")
          ? "bad"
          : s === "editing" || s === "thinking" || s === "agent"
            ? "agent"
            : "muted";
  return <StatusText tone={tone} className={className}>{titleCase(status)}</StatusText>;
}
