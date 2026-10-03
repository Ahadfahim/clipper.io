import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useAddNote, useAnswer, useDeleteNote, useResumeAccount, useSkipCampaign, useTakeCampaign } from "@/api/actions";
import { useBoard, useOverview, useStatus } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/fields";
import { SectionTitle, TitleRow } from "@/components/ui/misc";
import { Dot, type StatusTone } from "@/components/ui/status";
import { NeedsYouList } from "@/components/domain/attention";
import { AccountChip, MarketBadge } from "@/components/domain/badges";
import { BudgetBurnBar, KpiTile, RunsOut, StageStepper } from "@/components/domain/meters";
import { SlotBoard } from "@/components/domain/agents";
import { cn } from "@/lib/cn";
import { clock, money, relative, span } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { openProfile } from "@/lib/tauri";

const HEALTH_TONE: Record<string, StatusTone> = { ok: "ok", warn: "warn", fail: "bad", skip: "off" };

function Health({ items }: { items: Schemas["HealthItem"][] }) {
  return (
    <section aria-label="Health" className="min-w-[220px] flex-[1_1_220px]">
      <SectionTitle>Health</SectionTitle>
      <ul className="m-0 flex list-none flex-col overflow-hidden rounded-[var(--radius)] border border-line bg-panel p-0">
        {items.map((h) => (
          <li key={h.name} className="flex h-7 items-center gap-2 border-b border-line-soft px-2.5 last:border-b-0" title={h.fix || undefined}>
            <Dot tone={HEALTH_TONE[h.status] ?? "muted"} />
            <span className="flex-1 truncate-1">{h.name}</span>
            <span className="truncate-1 text-muted">{h.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CampaignsTable({ rows }: { rows: Schemas["ActiveCampaign"][] }) {
  const navigate = useNavigate();
  const cols = "60px minmax(0,2fr) minmax(150px,1.1fr) minmax(0,1.2fr) 90px";
  return (
    <div role="table" aria-label="Active campaigns" className="overflow-hidden rounded-[var(--radius)] border border-line">
      <div role="row" className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
        <span role="columnheader" className="px-2">Source</span>
        <span role="columnheader" className="px-2">Campaign</span>
        <span role="columnheader" className="px-2">Stage</span>
        <span role="columnheader" className="px-2">Budget left</span>
        <span role="columnheader" className="px-2">Runs out</span>
      </div>
      {rows.length === 0 && <div className="border-t border-line bg-panel px-2 py-2 text-muted">No active campaigns. Take one from the suggestions.</div>}
      {rows.map((c) => (
        <div
          key={c.id}
          role="row"
          tabIndex={0}
          onDoubleClick={() => void navigate({ to: "/campaigns", search: { open: c.id } })}
          onKeyDown={(e) => e.key === "Enter" && void navigate({ to: "/campaigns", search: { open: c.id } })}
          className="grid h-[30px] items-center border-t border-line bg-panel hover:bg-[color-mix(in_srgb,var(--fg)_4%,var(--panel))]"
          style={{ gridTemplateColumns: cols }}
        >
          <span role="cell" className="px-2">
            <MarketBadge market={c.marketplace} />
          </span>
          <span role="cell" className="truncate-1 px-2">{c.title}</span>
          <span role="cell" className="px-2">
            <StageStepper stages={c.stages} />
          </span>
          <span role="cell" className="px-2">
            <BudgetBurnBar left={c.budget_left} total={c.budget_total} runsOut={c.runs_out_at} deadline={c.deadline} />
          </span>
          <span role="cell" className="px-2">
            <RunsOut at={c.runs_out_at} deadline={c.deadline} />
          </span>
        </div>
      ))}
    </div>
  );
}

function Agenda({ entries, notes }: { entries: Schemas["AgendaEntry"][]; notes: Schemas["NoteOut"][] }) {
  const [text, setText] = useState("");
  const add = useAddNote();
  const del = useDeleteNote();
  return (
    <section aria-label="Agenda" className="min-w-[300px] flex-[2_1_300px]">
      <SectionTitle>Agenda</SectionTitle>
      <div className="flex flex-col gap-1 rounded-[var(--radius)] border border-line bg-panel px-2.5 py-1.5">
        {entries.length === 0 && <div className="text-muted">Nothing planned.</div>}
        {entries.slice(0, 7).map((e, i) => (
          <div key={i} className="flex gap-2.5">
            <span className="num w-11 shrink-0 text-muted">{e.when && Date.parse(e.when) > nowMs() ? clock(e.when, false) : "now"}</span>
            <span className="w-7 shrink-0 text-muted">{e.kind === "post" ? "post" : e.priority !== null ? `P${e.priority}` : ""}</span>
            <span className="truncate-1">{e.text}</span>
          </div>
        ))}
        <div className="mt-0.5 flex flex-col gap-1 border-t border-line pt-1.5">
          {notes.map((n) => (
            <div key={n.id} className="group flex items-center gap-2.5">
              <span className="w-11 shrink-0 text-accent">Note</span>
              <span className="flex-1 truncate-1">{n.text}</span>
              <button type="button" onClick={() => del.mutate(n.id)} className="text-muted opacity-0 group-hover:opacity-100 hover:text-fg focus:opacity-100">
                Clear
              </button>
            </div>
          ))}
          <form
            className="flex gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (!text.trim()) return;
              add.mutate({ scope: "global", text: text.trim(), pinned: true, scope_id: null, campaign_id: null });
              setText("");
            }}
          >
            <label htmlFor="global-note" className="sr-only">
              Add a note for all agents
            </label>
            <TextField id="global-note" value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note for all agents" className="h-[26px] flex-1" />
            <Button type="submit" size="sm" variant="primary" disabled={!text.trim()}>
              Pin
            </Button>
          </form>
        </div>
      </div>
    </section>
  );
}

/** Next 24h posts: one strip per account, posts placed by time. */
function Next24h({ posts }: { posts: Schemas["UpcomingPost"][] }) {
  const now = nowMs();
  const end = now + 24 * 3_600_000;
  const byAccount = new Map<string, Schemas["UpcomingPost"][]>();
  for (const p of posts) {
    const k = `${p.platform}|${p.handle}`;
    byAccount.set(k, [...(byAccount.get(k) ?? []), p]);
  }
  const hours = [0, 6, 12, 18, 24];
  return (
    <section aria-label="Next 24 hours of posts">
      <SectionTitle count={posts.length}>Next 24h posts</SectionTitle>
      <div className="overflow-hidden rounded-[var(--radius)] border border-line bg-panel">
        <div className="num grid h-[22px] items-center border-b border-line bg-panel-2 text-[11px] text-muted" style={{ gridTemplateColumns: "200px minmax(0,1fr)" }}>
          <span className="px-2 font-ui text-[12px]">Account</span>
          <span className="relative mr-3 h-full">
            {hours.map((h) => (
              <span key={h} className="absolute top-1" style={{ left: `${(h / 24) * 100}%`, transform: h === 24 ? "translateX(-100%)" : h ? "translateX(-50%)" : "none" }}>
                {clock(new Date(now + h * 3_600_000).toISOString(), false)}
              </span>
            ))}
          </span>
        </div>
        {byAccount.size === 0 && <div className="px-2 py-2 text-muted">Nothing scheduled in the next 24 hours.</div>}
        {[...byAccount.entries()].map(([k, ps]) => {
          const [platform, handle] = k.split("|");
          return (
            <div key={k} className="grid h-7 items-center border-b border-line-soft last:border-b-0" style={{ gridTemplateColumns: "200px minmax(0,1fr)" }}>
              <span className="px-2">
                <AccountChip platform={platform!} handle={handle!} />
              </span>
              <span className="relative mr-3 h-full">
                <span className="absolute inset-x-0 top-1/2 h-px bg-line" />
                {ps
                  .filter((p) => Date.parse(p.scheduled_at) <= end)
                  .map((p) => (
                    <span
                      key={p.id}
                      title={`Clip ${p.clip_id} at ${clock(p.scheduled_at, false)} (${relative(p.scheduled_at)})`}
                      className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel bg-accent"
                      style={{ left: `${((Date.parse(p.scheduled_at) - now) / (end - now)) * 100}%` }}
                    />
                  ))}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Home: what needs me → what are the agents doing → is it making money (UI.md §3.1). */
export function OverviewScreen() {
  const ov = useOverview().data;
  const status = useStatus().data;
  const board = useBoard().data;
  const navigate = useNavigate();
  const answer = useAnswer();
  const take = useTakeCampaign();
  const skip = useSkipCampaign();
  const resume = useResumeAccount();

  const onAction = (a: Schemas["NeedsYouAction"]) => {
    const args = a.args ?? {};
    switch (a.action) {
      case "open_profile":
        void openProfile(String(args["profile"] ?? ""));
        break;
      case "resume_account":
        resume.mutate(Number(args["account_id"]));
        break;
      case "answer":
        answer.mutate({ questionId: Number(args["question_id"]), answer: String(args["answer"]) });
        break;
      case "review":
        void navigate({ to: "/review/$batchId", params: { batchId: String(args["batch_id"]) } });
        break;
      case "take":
        take.mutate(Number(args["campaign_id"]));
        break;
      case "skip":
        skip.mutate(Number(args["campaign_id"]));
        break;
      case "open_campaign":
        void navigate({ to: "/campaigns", search: { open: Number(args["campaign_id"]) } });
        break;
      default:
        break;
    }
  };

  const nextScout = ov?.next_scout_in_s !== null && ov?.next_scout_in_s !== undefined ? span(ov.next_scout_in_s * 1000) : null;
  const busy = board?.slots.filter((s) => s.role).length ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-auto px-4 py-3 [&>*]:shrink-0">
      <TitleRow
        title="Overview"
        sub={
          status
            ? `${status.agents_running} agent${status.agents_running === 1 ? "" : "s"} running${nextScout ? ` · next scout in ${nextScout}` : ""} · ${money(status.earned_today, { cents: true })} today`
            : "Loading…"
        }
      />
      {ov && (
        <div className="grid overflow-hidden rounded-[var(--radius)] border border-line bg-panel" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(190px, 1fr))` }}>
          {ov.kpis.map((k, i) => (
            <KpiTile key={k.key} kpi={k} className={cn(i > 0 && "border-l border-line-soft")} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-3.5">
        <section aria-label="Needs you" className="min-w-0 flex-[4_1_560px]">
          <SectionTitle count={ov?.needs_you.length ?? 0}>Needs you</SectionTitle>
          <NeedsYouList
            items={ov?.needs_you ?? []}
            onAction={onAction}
            empty={`You're all caught up.${nextScout ? ` Next scout run in ${nextScout}.` : ""}`}
          />
        </section>
        {ov && <Health items={ov.health} />}
      </div>
      <section aria-label="Campaigns">
        <SectionTitle count={`${ov?.active_campaigns.length ?? 0} active`}>Campaigns</SectionTitle>
        <CampaignsTable rows={ov?.active_campaigns ?? []} />
      </section>
      <div className="flex flex-wrap gap-3.5">
        <section aria-label="Agent slots" className="min-w-0 flex-[3_1_420px]">
          <SectionTitle count={board ? `${busy} of ${board.slots.length} busy · ${board.queue.length} queued` : undefined}>Agent slots</SectionTitle>
          {board && <SlotBoard board={board} showQueue={false} onOpenSession={(id) => void navigate({ to: "/agents", search: { session: id } })} />}
        </section>
        <Agenda entries={ov?.agenda ?? []} notes={ov?.notes ?? []} />
      </div>
      <Next24h posts={ov?.upcoming_posts ?? []} />
    </div>
  );
}
