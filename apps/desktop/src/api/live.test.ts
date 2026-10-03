import { describe, expect, it } from "vitest";
import { describeEvent } from "./describe";
import { keysFor, useLive, wsUrl } from "./live";
import { qk } from "./queries";
import { fixtureFileName } from "./client";

describe("live events", () => {
  it("maps events to the queries they make stale", () => {
    expect(keysFor({ type: "review.decided", payload: { clip_id: 3, batch_id: 1 } })).toEqual(expect.arrayContaining([qk.batch(1), qk.batches, qk.overview]));
    expect(keysFor({ type: "agent.event", payload: { session_id: 2 } })).toEqual(expect.arrayContaining([qk.board, qk.session(2)]));
    expect(keysFor({ type: "edit.op", payload: { clip_id: 3 } })).toEqual([qk.edit(3), qk.clip(3)]);
    expect(keysFor({ type: "toggles.changed", payload: { name: "whop" } })).toEqual(expect.arrayContaining([qk.switches, qk.campaigns]));
    expect(keysFor({ type: "note.added", payload: { scope: "clip", scope_id: "3" } })).toEqual(expect.arrayContaining([qk.edit(3)]));
    expect(keysFor({ type: "something.else", payload: {} })).toEqual([]);
  });
  it("keeps a ring buffer, dedupes by id and tracks the live edit status", () => {
    const { push } = useLive.getState();
    push([
      { id: 1, ts: "2026-10-02T17:00:00Z", type: "alert", entity: null, entity_id: null, payload: { level: "warning", text: "x", source: "publish" } },
      { id: 2, ts: "2026-10-02T17:01:00Z", type: "edit.status", entity: "clip", entity_id: "3", payload: { clip_id: 3, text: "Removing fillers", range: [2, 5], actor: "session:1" } },
    ]);
    push([{ id: 2, ts: "2026-10-02T17:01:00Z", type: "edit.status", entity: "clip", entity_id: "3", payload: { clip_id: 3, text: "dup", range: null, actor: "x" } }]);
    const s = useLive.getState();
    expect(s.events.map((e) => e.id)).toEqual([1, 2]);
    expect(s.editStatus[3]?.text).toBe("Removing fillers");
  });
  it("describes events in plain words", () => {
    expect(describeEvent({ type: "agent.event", payload: { kind: "blocked", tool: "mcp__publish__schedule_post", summary: "[approval] not approved" } })).toMatchObject({
      source: "guard",
      text: "Blocked publish.schedule_post · not approved",
      problem: true,
    });
    expect(describeEvent({ type: "toggles.changed", payload: { name: "whop", enabled: false, via: "discord" } }).text).toBe("Whop turned off (discord)");
    expect(describeEvent({ type: "job.done", payload: { kind: "download", status: "failed", error: "boom" } }).problem).toBe(true);
  });
  it("builds socket and fixture names", () => {
    expect(wsUrl(42)).toBe("ws://127.0.0.1:8765/api/ws?after=42");
    expect(fixtureFileName(new URL("http://x/api/switches/preview?level=social&name=x"))).toBe("api/switches/preview__level=social&name=x.json");
    expect(fixtureFileName(new URL("http://x/api/overview"))).toBe("api/overview.json");
  });
});
