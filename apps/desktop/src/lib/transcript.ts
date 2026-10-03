// Groups raw agent_event rows into transcript items: a tool call joins its result, subagent
// work nests under the subagent's block (UI.md §3.2 live transcript).
import type { Schemas } from "@/api/client";

type Ev = Schemas["AgentEventOut"];

export type ToolItem = { kind: "tool"; id: number; ts: string; tool: string; input: Record<string, unknown>; output: Record<string, unknown> | null; ms: number | null; ok: boolean | null; subagent: string | null };
export type TranscriptItem =
  | { kind: "message"; id: number; ts: string; text: string; subagent: string | null }
  | { kind: "thinking"; id: number; ts: string; text: string; subagent: string | null }
  | { kind: "blocked"; id: number; ts: string; tool: string; rule: string; reason: string; subagent: string | null }
  | { kind: "user"; id: number; ts: string; text: string }
  | ToolItem
  | { kind: "subagent"; id: number; ts: string; name: string; task: string; children: TranscriptItem[] };

export const shortTool = (t: string | null | undefined): string => (t ?? "").replace(/^mcp__/, "").replace("__", ".");

export function groupTranscript(events: Ev[]): TranscriptItem[] {
  const out: TranscriptItem[] = [];
  let block: Extract<TranscriptItem, { kind: "subagent" }> | null = null;
  const open: ToolItem[] = []; // calls waiting for their result
  const push = (item: TranscriptItem, sub: string | null) => {
    if (block && sub === block.name) block.children.push(item);
    else {
      if (sub === null && item.kind !== "tool") block = null;
      out.push(item);
    }
  };
  for (const e of events) {
    const sub = e.subagent ?? null;
    switch (e.type) {
      case "subagent": {
        block = { kind: "subagent", id: e.id, ts: e.ts, name: sub ?? "subagent", task: e.text ?? "", children: [] };
        out.push(block);
        break;
      }
      case "tool_call": {
        const item: ToolItem = { kind: "tool", id: e.id, ts: e.ts, tool: e.tool ?? "", input: (e.input["args"] as Record<string, unknown>) ?? e.input, output: null, ms: null, ok: null, subagent: sub };
        open.push(item);
        push(item, sub);
        break;
      }
      case "tool_result": {
        const idx = open.findIndex((c) => c.tool === e.tool);
        if (idx >= 0) {
          const call = open.splice(idx, 1)[0]!;
          call.output = e.output;
          call.ms = Date.parse(e.ts) - Date.parse(call.ts);
          call.ok = !("error" in e.output);
        } else {
          push({ kind: "tool", id: e.id, ts: e.ts, tool: e.tool ?? "", input: {}, output: e.output, ms: null, ok: !("error" in e.output), subagent: sub }, sub);
        }
        break;
      }
      case "blocked": {
        const out_ = e.output as { rule?: string; reason?: string };
        const idx = open.findIndex((c) => c.tool === e.tool);
        if (idx >= 0) open.splice(idx, 1);
        push({ kind: "blocked", id: e.id, ts: e.ts, tool: e.tool ?? "", rule: out_.rule ?? "guard", reason: out_.reason ?? e.text ?? "", subagent: sub }, sub);
        break;
      }
      case "thinking":
        push({ kind: "thinking", id: e.id, ts: e.ts, text: e.text ?? "", subagent: sub }, sub);
        break;
      case "user":
        out.push({ kind: "user", id: e.id, ts: e.ts, text: e.text ?? "" });
        block = null;
        break;
      default:
        push({ kind: "message", id: e.id, ts: e.ts, text: e.text ?? String(e.input["text"] ?? ""), subagent: sub }, sub);
    }
  }
  return out;
}

export function flatten(items: TranscriptItem[]): TranscriptItem[] {
  return items.flatMap((i) => (i.kind === "subagent" ? [i, ...flatten(i.children)] : [i]));
}
