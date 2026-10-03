import { describe, expect, it } from "vitest";
import { canDrop, dayStart, moveToDay, weekDays } from "./calendar";

const H = 3_600_000;
const now = Date.parse("2026-10-02T18:00:00Z");
const acct = { id: 1, cap_today: 2, min_gap_min: 120, enabled: true, status: "active" };
const post = (id: number, at: number, status = "scheduled") => ({ id, account_id: 1, scheduled_at: new Date(at).toISOString(), status });

describe("calendar drop rules", () => {
  it("moves a post to another day at the same time", () => {
    const days = weekDays(now, 3);
    expect(days).toHaveLength(3);
    expect(moveToDay("2026-10-02T20:10:00Z", days[1]!)).toBe("2026-10-03T20:10:00.000Z");
    expect(dayStart(Date.parse("2026-10-02T20:10:00Z"))).toBe(Date.parse("2026-10-02T00:00:00Z"));
  });
  it("allows a drop that respects cap and gap", () => {
    const p = post(1, now + 2 * H);
    expect(canDrop(p, acct, [p], new Date(now + 26 * H).toISOString(), now)).toEqual({ ok: true });
  });
  it("blocks the daily cap, the minimum gap, the past and paused accounts", () => {
    const p = post(1, now + 2 * H);
    const others = [p, post(2, now + 20 * H), post(3, now + 24 * H)];
    expect(canDrop(p, acct, others, new Date(now + 27 * H).toISOString(), now).reason).toMatch(/cap/);
    const gap = [p, post(2, now + 24 * H)];
    expect(canDrop(p, { ...acct, cap_today: 5 }, gap, new Date(now + 25 * H).toISOString(), now).reason).toMatch(/120 min/);
    expect(canDrop(p, acct, [p], new Date(now - H).toISOString(), now).reason).toMatch(/passed/);
    expect(canDrop(p, { ...acct, status: "paused" }, [p], new Date(now + 26 * H).toISOString(), now).ok).toBe(false);
    // cancelled posts don't count
    expect(canDrop(p, acct, [p, post(2, now + 20 * H, "cancelled"), post(3, now + 24 * H, "cancelled")], new Date(now + 27 * H).toISOString(), now).ok).toBe(true);
  });
});
