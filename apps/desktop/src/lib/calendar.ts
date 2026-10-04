// Week calendar math and the drop rules the Publishing calendar checks while dragging. The core
// enforces the same caps on reschedule (services/posting.py); this only gives instant feedback.
import type { Schemas } from "@/api/client";

type Post = Pick<Schemas["PostOut"], "id" | "account_id" | "scheduled_at" | "status">;
type Account = Pick<Schemas["AccountOut"], "id" | "cap_today" | "min_gap_min" | "enabled" | "status">;

export const ACTIVE_POST = new Set(["scheduled", "posting", "live", "simulated"]);

/** Local midnight of the day containing `ms`. */
export function dayStart(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function weekDays(fromMs: number, days = 7): number[] {
  const start = dayStart(fromMs);
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d.getTime();
  });
}

/** Same time of day, moved to another day. */
export function moveToDay(iso: string, day: number): string {
  const src = new Date(iso);
  const d = new Date(day);
  d.setHours(src.getHours(), src.getMinutes(), 0, 0);
  return d.toISOString();
}

export type DropCheck = { ok: boolean; reason?: string };

export function canDrop(post: Post, account: Account, posts: Post[], newIso: string, nowMs: number): DropCheck {
  if (!account.enabled) return { ok: false, reason: "Account is off" };
  if (account.status !== "active") return { ok: false, reason: `Account is ${account.status}` };
  const t = Date.parse(newIso);
  if (t < nowMs) return { ok: false, reason: "That time has passed" };
  const others = posts.filter((p) => p.id !== post.id && p.account_id === account.id && ACTIVE_POST.has(p.status));
  const day = dayStart(t);
  const sameDay = others.filter((p) => dayStart(Date.parse(p.scheduled_at)) === day);
  if (sameDay.length >= account.cap_today) return { ok: false, reason: `Daily cap ${account.cap_today} reached` };
  const gapMs = account.min_gap_min * 60_000;
  const clash = others.find((p) => Math.abs(Date.parse(p.scheduled_at) - t) < gapMs);
  if (clash) return { ok: false, reason: `Less than ${account.min_gap_min} min from another post` };
  return { ok: true };
}
