import { describe, expect, it } from "vitest";
import type { Schemas } from "@/api/client";
import { flatten, groupTranscript, shortTool } from "./transcript";

const ev = (id: number, type: string, extra: Partial<Schemas["AgentEventOut"]> = {}): Schemas["AgentEventOut"] => ({
  id,
  type,
  ts: `2026-10-02T17:50:${String(id).padStart(2, "0")}Z`,
  session_id: 1,
  subagent: null,
  text: null,
  tool: null,
  input: {},
  output: {},
  ...extra,
});

describe("groupTranscript", () => {
  it("pairs calls with results, nests subagent work, keeps blocked rows", () => {
    const items = groupTranscript([
      ev(1, "message", { text: "Polishing clip 3" }),
      ev(2, "tool_call", { tool: "mcp__state__get_campaign", input: { args: { campaign_id: 1 } } }),
      ev(4, "tool_result", { tool: "mcp__state__get_campaign", output: { status: "active" } }),
      ev(5, "subagent", { subagent: "cutter", text: "cutter: edit clip 3", tool: "Agent" }),
      ev(6, "tool_call", { subagent: "cutter", tool: "mcp__edit__set_hook", input: { args: { clip_id: 3 } } }),
      ev(7, "tool_result", { tool: "mcp__edit__set_hook", output: { error: "bad range" } }),
      ev(8, "thinking", { subagent: "cutter", text: "try medium" }),
      ev(9, "blocked", { tool: "mcp__publish__schedule_post", output: { rule: "approval", reason: "not approved" } }),
    ]);
    expect(items.map((i) => i.kind)).toEqual(["message", "tool", "subagent", "blocked"]);
    const call = items[1]!;
    expect(call.kind === "tool" && call.ok && call.ms).toBe(2000);
    const sub = items[2]!;
    expect(sub.kind === "subagent" && sub.children.map((c) => c.kind)).toEqual(["tool", "thinking"]);
    const nested = sub.kind === "subagent" ? sub.children[0]! : null;
    expect(nested?.kind === "tool" && nested.ok).toBe(false);
    const blocked = items[3]!;
    expect(blocked.kind === "blocked" && blocked.rule).toBe("approval");
    expect(flatten(items)).toHaveLength(6);
    expect(shortTool("mcp__edit__set_hook")).toBe("edit.set_hook");
  });
});
