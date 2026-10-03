import { ChevronDown16Regular } from "@fluentui/react-icons";
import { useEffect, useMemo, useRef } from "react";
import { cn } from "@/lib/cn";
import { clock, relative } from "@/lib/format";
import { describeEvent, TONE_VAR } from "@/api/describe";
import { useLive } from "@/api/live";
import { useJobs } from "@/api/queries";
import { Progress } from "@/components/ui/misc";
import { StatusPill } from "@/components/ui/status";
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

function JobRows() {
  const jobs = useJobs().data ?? [];
  if (!jobs.length) return <div className="px-3 py-2 text-muted">No jobs.</div>;
  return (
    <div role="table" aria-label="Jobs" className="flex flex-col">
      {jobs.map((j) => (
        <div key={j.id} role="row" className="grid h-7 items-center border-b border-line-soft px-3" style={{ gridTemplateColumns: "48px 120px 110px minmax(80px,1fr) 160px" }}>
          <span className="num text-muted">#{j.id}</span>
          <span>{j.kind.replace(/_/g, " ")}</span>
          <StatusPill status={j.status} />
          <span className="flex items-center gap-2 pr-4">
            {j.status === "running" ? <Progress value={j.progress} label={`${j.kind} progress`} /> : <span className="truncate-1 text-muted">{j.error ?? ""}</span>}
          </span>
          <span className="num text-right text-muted">{relative(j.finished_at ?? j.started_at ?? j.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

const filters: Record<Exclude<OutputTab, "jobs">, (d: ReturnType<typeof describeEvent>) => boolean> = {
  activity: (d) => !d.agentOutput || d.problem,
  agent: (d) => d.agentOutput,
  problems: (d) => d.problem,
};

/** Docked output panel (Ctrl+J): Activity · Agent output · Jobs · Problems. */
export function OutputPanel() {
  const tab = useUi((s) => s.outputTab);
  const setTab = useUi((s) => s.setOutputTab);
  const toggle = useUi((s) => s.toggleOutput);
  const events = useLive((s) => s.events);
  const jobs = useJobs().data ?? [];
  const problems = useMemo(() => events.filter((e) => describeEvent(e).problem).length, [events]);
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
        {tab === "jobs" ? <JobRows /> : <LogRows filter={filters[tab]} />}
      </div>
    </section>
  );
}
