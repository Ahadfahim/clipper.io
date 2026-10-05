import { ChevronDown16Regular } from "@fluentui/react-icons";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/cn";
import { clock, relative } from "@/lib/format";
import { describeEvent, TONE_VAR } from "@/api/describe";
import { useLive } from "@/api/live";
import { useCancelJob, useCancelRetryJob, useRetryJob } from "@/api/actions";
import { useJobs, useOverview } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/misc";
import { Dot, StatusPill } from "@/components/ui/status";
import { age } from "@/lib/needsYou";
import { useUi, type OutputTab } from "@/state/ui";

function LogRows({ filter }: { filter: (d: ReturnType<typeof describeEvent>) => boolean }) {
  const events = useLive((s) => s.events);
  const rows = useMemo(
    () =>
      events
        .map((e) => ({ e, d: describeEvent(e) }))
        .filter((r) => filter(r.d))
        .reverse(),
    [events, filter],
  );
  if (!rows.length) return <div className="px-3 py-2 text-muted">Nothing yet.</div>;
  return (
    <div role="log" aria-live="polite" className="num flex flex-col gap-0.5 px-3 py-1.5 text-[12px]">
      {rows.map(({ e, d }) => (
        <div key={e.id} className="flex gap-3 whitespace-nowrap">
          <span className="text-muted">{clock(e.ts)}</span>
          <span className="w-[120px] shrink-0 truncate-1" style={{ color: TONE_VAR[d.tone] }}>
            {d.source}
          </span>
          <span className="selectable truncate-1 font-ui">{d.text}</span>
        </div>
      ))}
    </div>
  );
}

/** What needs a look comes first: a stalled job, then the ones still running or waiting, then the finished ones. */
const rank = (j: { stalled: boolean; status: string }) => (j.stalled ? 0 : j.status === "running" ? 1 : j.status === "queued" ? 2 : 3);

function JobRows() {
  const all = useJobs().data;
  const jobs = [...(all ?? [])].sort((a, b) => rank(a) - rank(b) || b.id - a.id);
  const retry = useRetryJob();
  const cancel = useCancelJob();
  const cancelRetry = useCancelRetryJob();
  if (!jobs.length) return <div className="px-3 py-2 text-muted">No jobs.</div>;
  return (
    <div role="table" aria-label="Jobs" className="flex flex-col">
      {jobs.map((j) => {
        const live = j.status === "running" || j.status === "queued";
        return (
          <div
            key={j.id}
            role="row"
            className={cn("grid h-7 items-center border-b border-line-soft px-3", j.stalled && "bg-warn-soft")}
            style={{ gridTemplateColumns: "48px 120px 110px minmax(80px,1fr) 150px 84px" }}
          >
            <span className="num text-muted">#{j.id}</span>
            <span title={j.label || undefined}>{j.kind.replace(/_/g, " ")}</span>
            {j.stalled ? <span className="text-warn">Stalled</span> : <StatusPill status={j.status} />}
            <span className="flex min-w-0 items-center gap-2 pr-4">
              {j.status === "running" ? (
                <>
                  <Progress value={j.progress} label={`${j.kind} progress`} className="max-w-[160px] shrink-0" />
                  <span className="truncate-1 min-w-0 text-muted" title={j.detail ?? undefined}>
                    {[j.detail, j.stalled ? `no progress for ${relative(j.progress_at ?? j.started_at ?? j.created_at).replace(" ago", "")}` : null].filter(Boolean).join(" · ")}
                  </span>
                </>
              ) : (
                <span className="truncate-1 text-muted" title={j.error ?? undefined}>
                  {j.error ?? ""}
                </span>
              )}
            </span>
            <span className="flex gap-1">
              {live && (
                <Button size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate(j.id)}>
                  Cancel
                </Button>
              )}
              {j.stalled && (
                <Button size="sm" variant="primary" disabled={cancelRetry.isPending} onClick={() => cancelRetry.mutate(j.id)} title="Cancel it and queue the same work again">
                  Retry
                </Button>
              )}
              {(j.status === "failed" || j.status === "cancelled") && (
                <Button size="sm" disabled={retry.isPending} onClick={() => retry.mutate(j.id)}>
                  Retry
                </Button>
              )}
            </span>
            <span className="num text-right text-muted">{relative(j.finished_at ?? j.started_at ?? j.created_at)}</span>
          </div>
        );
      })}
    </div>
  );
}

const filters: Record<Exclude<OutputTab, "jobs" | "problems">, (d: ReturnType<typeof describeEvent>) => boolean> = {
  activity: (d) => !d.agentOutput || d.problem,
  agent: (d) => d.agentOutput,
};

const isBlock = (d: ReturnType<typeof describeEvent>) => d.problem && d.source === "guard";
const PROBLEM_KINDS = new Set(["challenge", "alert", "failure", "stuck", "footage"]);

/** What is wrong right now: the same unresolved items Overview lists (blocked accounts, alerts, failed
 * jobs), plus the calls the safety rules blocked. A fixed problem leaves; it doesn't stay in a log. */
function useProblems() {
  const items = useOverview().data?.needs_you.filter((i) => PROBLEM_KINDS.has(i.kind)) ?? [];
  const events = useLive((s) => s.events);
  const blocks = useMemo(
    () =>
      events
        .map((e) => ({ e, d: describeEvent(e) }))
        .filter((r) => isBlock(r.d))
        .reverse(),
    [events],
  );
  return { items, blocks };
}

function ProblemRows() {
  const navigate = useNavigate();
  const { items, blocks } = useProblems();
  if (!items.length && !blocks.length) return <div className="px-3 py-2 text-muted">No problems.</div>;
  return (
    <div className="flex flex-col py-1">
      {items.map((i) => (
        <button
          key={i.key}
          type="button"
          onClick={() => void navigate({ to: "/", search: { item: i.key } })}
          className="flex h-6 items-center gap-3 px-3 text-left hover:bg-panel-2"
          title="Open it on Overview"
        >
          <span className="num w-10 shrink-0 text-muted">{age(i.since)}</span>
          <span className="flex w-[120px] shrink-0 items-center gap-1.5">
            <Dot tone={i.kind === "alert" || i.kind === "footage" ? "warn" : "bad"} />
            {{ challenge: "Blocked", alert: "Alert", stuck: "Stuck", footage: "Footage" }[i.kind as string] ?? "Failed"}
          </span>
          <span className="truncate-1 min-w-0 flex-1">{i.title}</span>
          {i.campaign_title && <span className="truncate-1 max-w-[200px] text-muted">{i.campaign_title}</span>}
        </button>
      ))}
      {blocks.length > 0 && (
        <div role="log" className="num flex flex-col gap-0.5 px-3 py-1 text-[12px]">
          {blocks.map(({ e, d }) => (
            <div key={e.id} className="flex gap-3 whitespace-nowrap">
              <span className="text-muted">{clock(e.ts)}</span>
              <span className="w-[120px] shrink-0 truncate-1" style={{ color: TONE_VAR[d.tone] }}>
                {d.source}
              </span>
              <span className="selectable truncate-1 font-ui">{d.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Docked output panel (Ctrl+J): Activity · Agent output · Jobs · Problems. */
export function OutputPanel() {
  const tab = useUi((s) => s.outputTab);
  const setTab = useUi((s) => s.setOutputTab);
  const toggle = useUi((s) => s.toggleOutput);
  const jobs = useJobs().data ?? [];
  const { items: problemItems, blocks } = useProblems();
  const problems = problemItems.length + blocks.length;
  const activeJobs = jobs.filter((j) => j.status === "running" || j.status === "queued").length;
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 });
  }, [tab]);
  const tabs: { id: OutputTab; label: string }[] = [
    { id: "activity", label: "Activity" },
    { id: "agent", label: "Agent output" },
    { id: "jobs", label: `Jobs (${activeJobs})` },
    { id: "problems", label: `Problems (${problems})` },
  ];
  return (
    <section aria-label="Output" className="flex h-full min-h-0 flex-col bg-panel">
      <div role="tablist" aria-label="Output panel" className="flex h-[30px] shrink-0 items-end gap-0.5 border-b border-line px-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn("h-7 border-b-2 px-3", tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg")}
          >
            {t.label}
          </button>
        ))}
        <span className="flex-1" />
        <button type="button" aria-label="Hide output panel (Ctrl+J)" title="Hide (Ctrl+J)" onClick={() => toggle(false)} className="mb-1 flex size-6 items-center justify-center rounded-[3px] text-muted hover:bg-panel-2">
          <ChevronDown16Regular />
        </button>
      </div>
      <div ref={scroller} role="tabpanel" className="min-h-0 flex-1 overflow-auto">
        {tab === "jobs" ? <JobRows /> : tab === "problems" ? <ProblemRows /> : <LogRows filter={filters[tab]} />}
      </div>
    </section>
  );
}
