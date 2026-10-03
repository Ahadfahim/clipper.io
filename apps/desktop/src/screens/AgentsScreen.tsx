import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo, useRef, useState, useEffect } from "react";
import { useBump, useCancelRequest, useDirectorChat, useInterrupt, useNudge, useReplay } from "@/api/actions";
import { useBoard, useDirector, useSession, useSessions, useStatus } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Check, Select, TextField } from "@/components/ui/fields";
import { Dialog } from "@/components/ui/dialog";
import { PaneHeader, PropertyGrid, TitleRow, Toolbar } from "@/components/ui/misc";
import { Pane, Panes, Splitter } from "@/components/ui/splitter";
import { Dot } from "@/components/ui/status";
import { AgentEventRow, SlotBoard } from "@/components/domain/agents";
import { UsageMeter } from "@/components/domain/meters";
import { cn } from "@/lib/cn";
import { clock, compact, relative } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/platforms";
import { flatten, groupTranscript, type TranscriptItem } from "@/lib/transcript";

const GROUPS: { key: string; label: string; match: (s: Schemas["SessionOut"]) => boolean }[] = [
  { key: "running", label: "Running", match: (s) => s.status === "running" },
  { key: "waiting", label: "Waiting on event", match: (s) => s.status === "waiting" || s.status === "idle" || s.status === "rate_limited" },
  { key: "done", label: "Done today", match: (s) => !["running", "waiting", "idle", "rate_limited"].includes(s.status) },
];

function SessionList({ sessions, selected, onSelect }: { sessions: Schemas["SessionOut"][]; selected?: number; onSelect: (id: number) => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PaneHeader>Sessions</PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto" role="listbox" aria-label="Agent sessions">
        {GROUPS.map((g) => {
          const items = sessions.filter(g.match);
          if (!items.length) return null;
          return (
            <div key={g.key}>
              <div className="px-2.5 pt-2 pb-1 text-[11px] text-muted">
                {g.label} <span className="num">({items.length})</span>
              </div>
              {items.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  role="option"
                  aria-selected={selected === s.id}
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    "flex w-full flex-col gap-0.5 border-b border-line-soft px-2.5 py-1.5 text-left",
                    selected === s.id ? "bg-accent-soft" : "hover:bg-[color-mix(in_srgb,var(--fg)_4%,transparent)]",
                  )}
                >
                  <span className="flex items-center gap-1.5">
                    <Dot tone={s.status === "running" ? "agent" : s.status === "waiting" ? "warn" : "off"} />
                    <span className="truncate-1 flex-1">
                      {ROLE_LABEL[s.role] ?? s.role}
                      {s.campaign_title ? ` · ${s.campaign_title}` : ""}
                    </span>
                  </span>
                  <span className="num flex gap-2 pl-3.5 text-[11px] text-muted">
                    <span>
                      {s.turns}/{s.max_turns} turns
                    </span>
                    <span>{compact(s.input_tokens + s.output_tokens)} tok</span>
                    <span className="ml-auto">{relative(s.last_active)}</span>
                  </span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Transcript({ detail, onReplay }: { detail?: Schemas["SessionDetail"]; onReplay: (item: TranscriptItem) => void }) {
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [onlyBlocked, setOnlyBlocked] = useState(false);
  const items = useMemo(() => groupTranscript(detail?.events ?? []), [detail]);
  const shown = useMemo(() => {
    if (!onlyErrors && !onlyBlocked) return items;
    return flatten(items).filter((i) => (onlyBlocked && i.kind === "blocked") || (onlyErrors && (i.kind === "blocked" || (i.kind === "tool" && i.ok === false))));
  }, [items, onlyErrors, onlyBlocked]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [detail?.events.length]);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PaneHeader
        actions={
          <span className="flex items-center gap-2 text-fg">
            <Check checked={onlyErrors} onChange={setOnlyErrors} label="Only errors" />
            <Check checked={onlyBlocked} onChange={setOnlyBlocked} label="Only blocked by rules" />
          </span>
        }
      >
        Live transcript
        {detail && (
          <span className="text-fg">
            {" "}
            · {ROLE_LABEL[detail.session.role] ?? detail.session.role}
            {detail.session.campaign_title ? ` · ${detail.session.campaign_title}` : ""}
          </span>
        )}
      </PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto bg-panel" aria-live="polite">
        {!detail && <div className="p-3 text-muted">Pick a session.</div>}
        {detail && shown.length === 0 && <div className="p-3 text-muted">Nothing matches the filters.</div>}
        {shown.map((i) => (
          <AgentEventRow key={`${i.kind}-${i.id}`} item={i} onReplay={onReplay} />
        ))}
        {detail?.session.status === "running" && (
          <div className="flex items-center gap-2 px-2.5 py-1.5 text-agent">
            <Dot tone="agent" pulse /> working…
          </div>
        )}
        <div ref={end} />
      </div>
    </div>
  );
}

function Context({ detail }: { detail?: Schemas["SessionDetail"] }) {
  const interrupt = useInterrupt();
  const nudge = useNudge();
  const navigate = useNavigate();
  if (!detail) return <PaneHeader>Context</PaneHeader>;
  const s = detail.session;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PaneHeader>Context</PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        <PropertyGrid
          labelWidth={100}
          rows={[
            ["Role", ROLE_LABEL[s.role] ?? s.role],
            [
              "Campaign",
              s.campaign_id ? (
                <button type="button" className="text-accent hover:underline" onClick={() => void navigate({ to: "/campaigns", search: { open: s.campaign_id ?? undefined } })}>
                  {s.campaign_title}
                </button>
              ) : (
                "—"
              ),
            ],
            ["Status", s.status.replace("_", " ")],
            [
              "Turns",
              <span key="t" className="num">
                {s.turns} / {s.max_turns}
              </span>,
            ],
            ["Tokens", <span key="k" className="num">{`${compact(s.input_tokens)} in · ${compact(s.output_tokens)} out`}</span>],
            ["Started", relative(s.started)],
            ["Last active", relative(s.last_active)],
            ["SDK session", <span key="sdk" className="num text-[11px]">{s.sdk_session_id ?? "—"}</span>],
            ["Summary", s.summary ?? "—"],
          ]}
        />
        <div className="flex flex-wrap gap-1.5 border-t border-line p-2.5">
          <Button size="sm" onClick={() => interrupt.mutate(s.id)} disabled={s.status !== "running"}>
            Interrupt
          </Button>
          <Button size="sm" onClick={() => nudge.mutate(s.id)} disabled={!s.campaign_id}>
            Nudge
          </Button>
          <Button size="sm" onClick={() => nudge.mutate(s.id)} disabled={s.status === "running" || !s.campaign_id} title="Wake the session with a resume message">
            Resume
          </Button>
          <Button size="sm" disabled title="Forking a session needs SDK session forks (not wired yet)">
            Fork
          </Button>
        </div>
        <div className="border-t border-line">
          <div className="px-2.5 pt-2 pb-1 text-[11px] text-muted">Events → resumes</div>
          {detail.requests.length === 0 && <div className="px-2.5 pb-2 text-muted">No pending resumes.</div>}
          {detail.requests.map((r) => (
            <div key={r.request_id} className="flex gap-2 px-2.5 py-0.5">
              <span className="num text-muted">{clock(r.queued_at, false)}</span>
              <span className="num">P{r.priority}</span>
              <span className="truncate-1">{r.kind}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DirectorChat() {
  const msgs = useDirector().data ?? [];
  const chat = useDirectorChat();
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [msgs.length]);
  return (
    <section aria-label="Director chat" className="flex min-h-0 flex-1 flex-col">
      <PaneHeader>Director · same conversation as #control in Discord</PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto bg-panel px-3 py-2" aria-live="polite">
        {msgs.map((m) => (
          <div key={m.id} className="mb-1.5 flex gap-2.5">
            <span className="num w-11 shrink-0 text-muted">{clock(m.ts, false)}</span>
            <span className={cn("w-16 shrink-0", m.type === "user" ? "text-accent" : "text-agent")}>{m.type === "user" ? "You" : "Director"}</span>
            <span className={cn("selectable min-w-0 flex-1", m.type !== "user" && "voice text-[13px]")}>{m.text}</span>
          </div>
        ))}
        <div ref={end} />
      </div>
      <form
        className="flex gap-1.5 border-t border-line bg-chrome px-2.5 py-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          chat.mutate(text.trim());
          setText("");
        }}
      >
        <label htmlFor="director-input" className="sr-only">
          Message the Director
        </label>
        <TextField id="director-input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about earnings or campaigns, or tell the agents what to do" className="flex-1" />
        <Button type="submit" variant="primary" disabled={!text.trim()}>
          Send
        </Button>
      </form>
    </section>
  );
}

/** What are the agents doing: slots + queue, sessions, live transcript, context, Director chat (UI.md §3.2). */
export function AgentsScreen() {
  const search = useSearch({ from: "/shell/agents" });
  const navigate = useNavigate();
  const sessions = useSessions().data ?? [];
  const board = useBoard().data;
  const status = useStatus().data;
  const [role, setRole] = useState("all");
  const filtered = sessions.filter((s) => role === "all" || s.role === role);
  const selected = search.session ?? filtered.find((s) => s.status === "running")?.id ?? filtered[0]?.id;
  const detail = useSession(selected).data;
  const bump = useBump();
  const cancel = useCancelRequest();
  const replay = useReplay();
  const [replayOut, setReplayOut] = useState<Schemas["ReplayOut"] | null>(null);
  const busy = board?.slots.filter((s) => s.role).length ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-2.5 px-4 pt-3 pb-2.5">
        <TitleRow
          title="Agents"
          sub={board ? `${busy} of ${board.slots.length} slots busy · ${board.queue.length} queued${board.p01_only ? " · only P0–P1 (usage high)" : ""}${board.halted ? " · halted" : ""}` : undefined}
          actions={status && <UsageMeter usage={status.usage} />}
        />
        {board && (
          <SlotBoard
            board={board}
            onBump={(id, p) => bump.mutate({ requestId: id, priority: p })}
            onCancel={(id) => cancel.mutate(id)}
            onOpenSession={(id) => void navigate({ to: "/agents", search: { session: id } })}
          />
        )}
      </div>
      <Toolbar label="Session filters" className="border-t">
        <label htmlFor="role-filter" className="px-1 text-muted">
          Role
        </label>
        <Select id="role-filter" value={role} onChange={(e) => setRole(e.target.value)} className="h-6 w-36">
          <option value="all">All roles</option>
          {Object.entries(ROLE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <span className="flex-1" />
        <span className="text-muted">{sessions.length} sessions</span>
      </Toolbar>
      <Panes direction="vertical" autoSaveId="clipper.agents.v" className="flex-1">
        <Pane defaultSize={68} minSize={30}>
          <Panes direction="horizontal" autoSaveId="clipper.agents.h">
            <Pane defaultSize={22} minSize={14} className="bg-panel">
              <SessionList sessions={filtered} selected={selected} onSelect={(id) => void navigate({ to: "/agents", search: { session: id } })} />
            </Pane>
            <Splitter />
            <Pane defaultSize={52} minSize={30}>
              <Transcript
                detail={detail}
                onReplay={(item) =>
                  replay.mutate(item.id, {
                    onSuccess: (out) => setReplayOut(out as Schemas["ReplayOut"]),
                  })
                }
              />
            </Pane>
            <Splitter />
            <Pane defaultSize={26} minSize={16} className="bg-panel">
              <Context detail={detail} />
            </Pane>
          </Panes>
        </Pane>
        <Splitter direction="vertical" />
        <Pane defaultSize={32} minSize={14}>
          <DirectorChat />
        </Pane>
      </Panes>
      <Dialog open={replayOut !== null} onOpenChange={(o) => !o && setReplayOut(null)} title="Replay in dry-run" width={560}>
        {replayOut && !replayOut.tool && <p className="m-0 text-muted">Replay needs the core running (fixture data is read-only).</p>}
        {replayOut?.tool && (
          <div className="flex flex-col gap-2">
            <PropertyGrid
              rows={[
                ["Tool", <span key="t" className="num">{replayOut.tool}</span>],
                ["Guard today", replayOut.allowed ? <span key="a" className="text-ok">Allowed</span> : <span key="b" className="text-bad">Blocked by “{replayOut.rule}”: {replayOut.reason}</span>],
                ["Executed", replayOut.executed ? "Yes (read-only tool)" : replayOut.detail || "No"],
              ]}
            />
            {replayOut.output && <pre className="num selectable m-0 max-h-[300px] overflow-auto rounded-[3px] bg-bg p-2 text-[11px]">{JSON.stringify(replayOut.output, null, 1)}</pre>}
          </div>
        )}
      </Dialog>
    </div>
  );
}
