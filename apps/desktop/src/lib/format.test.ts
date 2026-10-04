import { describe, expect, it } from "vitest";
import { clock, compact, cpm, duration, money, pct, relative, roughly, signedPct, span, timecode, titleCase } from "./format";
import { FIXTURE_NOW } from "./now";

describe("format", () => {
  it("money", () => {
    expect(money(48.2, { cents: true })).toBe("$48.20");
    expect(money(18400)).toBe("$18.4K");
    expect(money(null)).toBe("—");
    expect(cpm(3)).toBe("$3.00");
  });
  it("numbers", () => {
    expect(compact(9145)).toBe("9,145");
    expect(compact(79459)).toBe("79.5K");
    expect(pct(0.384)).toBe("38%");
    expect(signedPct(12.4)).toBe("▲12%");
    expect(signedPct(-3.25)).toBe("▼3.3%");
    expect(signedPct(null)).toBe("");
  });
  it("durations", () => {
    expect(duration(42)).toBe("0:42");
    expect(duration(3725)).toBe("1:02:05");
    expect(timecode(14.2)).toBe("0:14.2");
    expect(span(2 * 3600_000 + 14 * 60_000)).toBe("2h 14m");
    expect(span(30_000)).toBe("<1m");
    expect(span(5 * 86_400_000)).toBe("5d");
  });
  it("relative times use the fixture clock in fixture mode", () => {
    expect(relative(new Date(FIXTURE_NOW + 2 * 3600_000 + 10 * 60_000).toISOString())).toBe("in 2h 10m");
    expect(relative(new Date(FIXTURE_NOW - 5 * 60_000).toISOString())).toBe("5m ago");
    expect(roughly(new Date(FIXTURE_NOW + 2.2 * 86_400_000).toISOString())).toBe("~2 days");
    expect(roughly(new Date(FIXTURE_NOW - 1000).toISOString())).toBe("ran out");
  });
  it("clock and labels", () => {
    expect(clock("2026-10-02T14:32:07Z")).toBe("14:32:07");
    expect(titleCase("in_review")).toBe("In review");
  });
});
