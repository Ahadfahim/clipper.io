import { ChevronDown12Regular, ChevronRight12Regular, Dismiss12Regular, ArrowUp12Regular } from "@fluentui/react-icons";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { clock, span } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { ROLE_LABEL, modelLabel } from "@/lib/platforms";
import { shortTool, type TranscriptItem } from "@/lib/transcript";
import { Dot } from "@/components/ui/status";
import { Tooltip } from "@/components/ui/misc";
import type { Schemas } from "@/api/client";

const P = (p: number | null | undefined) => (p === null || p === undefined ? "" : `P${p}`);

function slotName(s: Schemas["SlotOut"]): string {
  if (!s.role) return "Idle";
  const role = ROLE_LABEL[s.role] ?? s.role;
  return s.campaign_title ? `${role} · ${s.campaign_title}` : role;
}

/**
 * Agent slots with their current tool and elapsed time, plus the waiting queue (P0–P3) with
 * bump/cancel. Dimmed slots = the pool shrank because Claude usage is high.
 */
export function SlotBoard({
  board,
  onBump,
  onCancel,
  onOpenSession,
  showQueue = true,
}: {
  board: Schemas["BoardOut"];
  onBump?: (requestId: number, priority: number) => void;
  onCancel?: (requestId: number) => void;
  onOpenSession?: (sessionId: number) => void;
  showQueue?: boolean;
}) {
  const now = nowMs();
  const cols = "34px minmax(0,1.4fr) 34px minmax(0,1.5fr) 74px 56px";
  return (
    <div className="flex flex-wrap gap-3.5">
      <div role="table" aria-label="Agent slots" className="min-w-[380px] flex-[3_1_420px] overflow-hidden rounded-[var(--radius)] border border-line">
        <div role="row" className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
          <span role="columnheader" className="px-2">#</span>
          <span role="columnheader" className="px-2">Agent</span>
          <span role="columnheader" className="px-1">Pri</span>
          <span role="columnheader" className="px-2">Current tool</span>
          <span role="columnheader" className="px-2">Model</span>
          <span role="columnheader" className="px-2 text-right">Time</span>
        </div>
        {board.slots.map((s) => {
          const busy = s.role !== null;
          const reserved = !busy && s.slot === board.slots.length - 1 && !board.halted;
          return (
            <div
              key={s.slot}
              role="row"
              onDoubleClick={() => s.session_id && onOpenSession?.(s.session_id)}
              className={cn("grid h-7 items-center border-t border-line bg-panel", s.dimmed && "opacity-45")}
              style={{ gridTemplateColumns: cols }}
              title={s.dimmed ? "Paused: the pool shrinks while Claude usage is high" : undefined}
            >
              <span role="cell" className="num px-2 text-muted">{s.slot + 1}</span>
              <span role="cell" className="flex min-w-0 items-center gap-1.5 px-2">
                <Dot tone={busy ? "agent" : s.dimmed ? "off" : "ok"} />
                <span className="truncate-1">{busy ? slotName(s) : s.dimmed ? "Paused (usage)" : reserved ? "Reserved for you" : "Idle"}</span>
              </span>
              <span role="cell" className="num px-1">{busy ? P(s.priority) : reserved ? "P0" : ""}</span>
              <span role="cell" className={cn("num truncate-1 px-2", busy ? "text-agent" : "text-muted")}>{busy ? shortTool(s.current_tool) || "thinking" : "idle"}</span>
              <span role="cell" className="truncate-1 px-2 text-muted">{busy ? modelLabel(s.model) : ""}</span>
              <span role="cell" className="num px-2 text-right">{s.started ? span(now - Date.parse(s.started)) : "—"}</span>
            </div>
          );
        })}
      </div>
      {showQueue && (
        <div role="table" aria-label="Queue" className="min-w-[280px] flex-[2_1_300px] overflow-hidden rounded-[var(--radius)] border border-line">
          <div role="row" className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: "34px minmax(0,1fr) 64px 52px" }}>
            <span role="columnheader" className="px-2">Pri</span>
            <span role="columnheader" className="px-2">Waiting</span>
            <span role="columnheader" className="px-2 text-right">Queued</span>
            <span role="columnheader" className="sr-only">Actions</span>
          </div>
          {board.queue.length === 0 && <div className="border-t border-line bg-panel px-2 py-1.5 text-muted">Nothing waiting.</div>}
          {board.queue.map((q) => (
            <div key={q.request_id} role="row" className="group grid h-7 items-center border-t border-line bg-panel" style={{ gridTemplateColumns: "34px minmax(0,1fr) 64px 52px" }}>
              <span role="cell" className={cn("num px-2", q.priority === 0 && "text-accent")}>{P(q.priority)}</span>
              <span role="cell" className="truncate-1 px-2">
                {ROLE_LABEL[q.role] ?? q.role}
                {q.campaign_title ? ` · ${q.campaign_title}` : ""} <span className="text-muted">· {q.kind}{q.merged ? ` (+${q.merged})` : ""}</span>
              </span>
              <span role="cell" className="num px-2 text-right text-muted">{clock(q.queued_at, false)}</span>
              <span role="cell" className="flex justify-end gap-0.5 px-1">
                {onBump && q.priority > 0 && (
                  <Tooltip content="Bump priority">
                    <button type="button" aria-label={`Bump ${q.kind} to P${q.priority - 1}`} onClick={() => onBump(q.request_id, q.priority - 1)} className="flex size-5 items-center justify-center rounded-[3px] hover:bg-panel-2">
                      <ArrowUp12Regular />
                    </button>
                  </Tooltip>
                )}
                {onCancel && (
                  <Tooltip content="Cancel request">
                    <button type="button" aria-label={`Cancel ${q.kind}`} onClick={() => onCancel(q.request_id)} className="flex size-5 items-center justify-center rounded-[3px] hover:bg-panel-2">
                      <Dismiss12Regular />
                    </button>
                  </Tooltip>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  return <pre className="num selectable m-0 overflow-auto rounded-[3px] bg-bg p-1.5 text-[11px] whitespace-pre-wrap">{JSON.stringify(value, null, 1)}</pre>;
}

/** One transcript row: message · tool call (collapsible input/output) · subagent block · blocked · thinking. */
export function AgentEventRow({ item, depth = 0, onReplay }: { item: TranscriptItem; depth?: number; onReplay?: (item: TranscriptItem) => void }) {
  const [open, setOpen] = useState(item.kind === "subagent");
  const time = <span className="num w-[58px] shrink-0 text-muted">{clock(item.ts)}</span>;
  const pad = { paddingLeft: 10 + depth * 18 };
  if (item.kind === "message" || item.kind === "user")
    return (
      <div className="flex gap-2 border-b border-line-soft py-1 pr-2.5" style={pad}>
        {time}
        <span className={cn("selectable min-w-0 flex-1", item.kind === "user" && "text-accent")}>{item.kind === "user" ? `You: ${item.text}` : item.text}</span>
      </div>
    );
  if (item.kind === "thinking")
    return (
      <div className="flex gap-2 border-b border-line-soft py-1 pr-2.5 text-muted italic" style={pad}>
        {time}
        <span className="selectable min-w-0 flex-1">{item.text}</span>
      </div>
    );
  if (item.kind === "blocked")
    return (
      <div className="flex gap-2 border-b border-line-soft bg-bad-soft py-1 pr-2.5" style={pad}>
        {time}
        <span className="min-w-0 flex-1">
          <span className="text-bad">Blocked by rule “{item.rule}”</span> <span className="num">{shortTool(item.tool)}</span>
          <span className="block text-muted">{item.reason}</span>
        </span>
      </div>
    );
  if (item.kind === "subagent")
    return (
      <div className="border-b border-line-soft">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 py-1 pr-2.5 text-left hover:bg-panel-2" style={pad}>
          {time}
          <span className="text-muted">{open ? <ChevronDown12Regular /> : <ChevronRight12Regular />}</span>
          <span className="text-agent">Subagent {item.name}</span>
          <span className="truncate-1 min-w-0 flex-1 text-muted">{item.task.replace(`${item.name}: `, "")}</span>
          <span className="num text-muted">{item.children.length} steps</span>
        </button>
        {open && (
          <div className="border-l-2 border-agent/40" style={{ marginLeft: 10 + depth * 18 + 62 }}>
            {item.children.map((c) => (
              <AgentEventRow key={c.id} item={c} depth={0} onReplay={onReplay} />
            ))}
          </div>
        )}
      </div>
    );
  return (
    <div className="border-b border-line-soft">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 py-1 pr-2.5 text-left hover:bg-panel-2" style={pad}>
        {time}
        <span className="text-muted">{open ? <ChevronDown12Regular /> : <ChevronRight12Regular />}</span>
        <span className="num text-agent">{shortTool(item.tool)}</span>
        <span className="truncate-1 min-w-0 flex-1 text-muted">{Object.entries(item.input).map(([k, v]) => `${k}=${typeof v === "object" ? "…" : String(v)}`).join(" ")}</span>
        {item.ms !== null && <span className="num text-muted">{item.ms < 1000 ? `${item.ms}ms` : `${(item.ms / 1000).toFixed(1)}s`}</span>}
        <span className={cn("w-3 text-center", item.ok === false ? "text-bad" : item.ok ? "text-ok" : "text-agent")} aria-label={item.ok === false ? "failed" : item.ok ? "done" : "running"}>
          {item.ok === false ? "✗" : item.ok ? "✓" : "…"}
        </span>
      </button>
      {open && (
        <div className="grid grid-cols-2 gap-2 pr-2.5 pb-2" style={{ paddingLeft: 10 + depth * 18 + 62 }}>
          <div>
            <div className="text-muted">Input</div>
            <Json value={item.input} />
          </div>
          <div>
            <div className="text-muted">Output</div>
            {item.output ? <Json value={item.output} /> : <span className="text-agent">running…</span>}
          </div>
          {onReplay && (
            <div className="col-span-2">
              <button type="button" onClick={() => onReplay(item)} className="text-accent hover:underline">
                Replay in dry-run
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
