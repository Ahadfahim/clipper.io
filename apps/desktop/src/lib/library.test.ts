import { describe, expect, it } from "vitest";
import clips from "../../public/fixtures/api/clips.json";
import scrapped from "../../public/fixtures/api/clips__status=scrapped.json";
import { bytesLabel, CLIP_STATUSES, clickSelect, EMPTY_SELECTION, prune, purgeLabel, selectAll } from "./library";

const order = [10, 11, 12, 13, 14];
const mods = { ctrl: false, shift: false };

describe("selection", () => {
  it("a plain click selects one card", () => {
    const a = clickSelect(EMPTY_SELECTION, order, 11, mods);
    expect([...a.ids]).toEqual([11]);
    expect([...clickSelect(a, order, 13, mods).ids]).toEqual([13]);
  });
  it("Ctrl toggles cards in and out", () => {
    let s = clickSelect(EMPTY_SELECTION, order, 11, mods);
    s = clickSelect(s, order, 13, { ctrl: true, shift: false });
    expect([...s.ids].sort()).toEqual([11, 13]);
    s = clickSelect(s, order, 11, { ctrl: true, shift: false });
    expect([...s.ids]).toEqual([13]);
  });
  it("Shift selects the range from the last clicked card, in either direction", () => {
    const s = clickSelect(EMPTY_SELECTION, order, 11, mods);
    expect([...clickSelect(s, order, 13, { ctrl: false, shift: true }).ids]).toEqual([11, 12, 13]);
    const up = clickSelect(clickSelect(EMPTY_SELECTION, order, 14, mods), order, 12, { ctrl: false, shift: true });
    expect([...up.ids].sort()).toEqual([12, 13, 14]);
    const more = clickSelect(clickSelect(s, order, 13, { ctrl: true, shift: false }), order, 14, { ctrl: true, shift: true });
    expect([...more.ids].sort()).toEqual([11, 13, 14]);
  });
  it("select all and prune", () => {
    expect(selectAll(order).ids.size).toBe(5);
    const s = prune(selectAll(order), [10, 12]);
    expect([...s.ids]).toEqual([10, 12]);
    expect(s.anchor).toBe(10);
    expect(prune(s, [10, 12])).toBe(s); // nothing changed: the same object, so no re-render
  });
});

describe("labels", () => {
  it("sizes and the days until files are deleted", () => {
    expect([512, 20_000, 130 * 1024 ** 2, 1.4 * 1024 ** 3].map(bytesLabel)).toEqual(["512 B", "20 KB", "130 MB", "1.4 GB"]);
    const now = Date.parse("2026-10-02T18:00:00Z");
    expect(purgeLabel("2026-10-07T18:00:00Z", false, now)).toBe("Deleted in 5 days");
    expect(purgeLabel("2026-10-03T10:00:00Z", false, now)).toBe("Deleted in 1 day");
    expect(purgeLabel("2026-10-02T10:00:00Z", false, now)).toBe("Deleted today");
    expect(purgeLabel("2026-10-02T10:00:00Z", true, now)).toBe("Files deleted");
  });
});

describe("the status filter", () => {
  it("offers every status the data has, and no status that doesn't exist", () => {
    const seen = new Set([...(clips as { status: string }[]), ...(scrapped as { status: string }[])].map((c) => c.status));
    for (const s of seen) expect([...CLIP_STATUSES, "scrapped"], `status ${s} is missing from the filter`).toContain(s);
    expect(CLIP_STATUSES).not.toContain("candidate");
    expect(CLIP_STATUSES).not.toContain("scheduled");
  });
});
