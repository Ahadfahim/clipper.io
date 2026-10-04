import { useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts";
import { useEarnings, useManifest } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { Check } from "@/components/ui/fields";
import { SectionTitle, TitleRow } from "@/components/ui/misc";
import { MarketBadge, Score } from "@/components/domain/badges";
import { cn } from "@/lib/cn";
import { compact, day, money, pct } from "@/lib/format";
import { MARKET_LABEL, MARKET_ORDER, MARKET_SERIES } from "@/lib/platforms";

type Row = { day: string; label: string } & Record<string, number | string>;

function Legend() {
  return (
    <span className="flex items-center gap-3 text-muted">
      {MARKET_ORDER.map((m) => (
        <span key={m} className="flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-[2px]" style={{ background: MARKET_SERIES[m] }} />
          {MARKET_LABEL[m]}
        </span>
      ))}
    </span>
  );
}

function ChartTip({ active, payload, label, fmt }: TooltipProps<number, string> & { fmt: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((a, p) => a + Number(p.value ?? 0), 0);
  return (
    <div className="rounded-[var(--radius)] border border-line bg-panel px-2.5 py-1.5 shadow-md">
      <div className="mb-0.5 font-semibold">{label}</div>
      {[...payload].reverse().map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="inline-block size-2 rounded-[2px]" style={{ background: MARKET_SERIES[String(p.dataKey)] }} />
          <span className="w-12">{MARKET_LABEL[String(p.dataKey)]}</span>
          <span className="num ml-auto">{fmt(Number(p.value ?? 0))}</span>
        </div>
      ))}
      <div className="mt-0.5 flex justify-between border-t border-line pt-0.5 text-muted">
        <span>Total</span>
        <span className="num text-fg">{fmt(total)}</span>
      </div>
    </div>
  );
}

/** Stacked columns per day, one segment per marketplace (≤24px bars, 2px surface gaps, rounded tops). */
function DailyChart({ rows, fmt, tick, label, height = 220 }: { rows: Row[]; fmt: (v: number) => string; tick: (v: number) => string; label: string; height?: number }) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="28%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--line)" }} tick={{ fill: "var(--muted)", fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis tickLine={false} axisLine={false} width={52} tick={{ fill: "var(--muted)", fontSize: 11, fontFamily: "var(--font-mono)" }} tickFormatter={tick} />
          <Tooltip cursor={{ fill: "color-mix(in srgb, var(--fg) 6%, transparent)" }} content={<ChartTip fmt={fmt} />} />
          {MARKET_ORDER.map((m, i) => (
            <Bar
              key={m}
              dataKey={m}
              stackId="m"
              fill={MARKET_SERIES[m]}
              stroke="var(--panel)"
              strokeWidth={2}
              maxBarSize={24}
              radius={i === MARKET_ORDER.length - 1 ? [4, 4, 0, 0] : 0}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function SeriesTable({ rows }: { rows: Row[] }) {
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="h-[26px] bg-panel-2 text-left text-muted">
          <th className="px-2 font-normal">Day</th>
          {MARKET_ORDER.map((m) => (
            <th key={m} className="px-2 text-right font-normal">
              {MARKET_LABEL[m]} $
            </th>
          ))}
          {MARKET_ORDER.map((m) => (
            <th key={`v${m}`} className="px-2 text-right font-normal">
              {MARKET_LABEL[m]} views
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.day} className="h-6 border-b border-line-soft">
            <td className="px-2">{r.label}</td>
            {MARKET_ORDER.map((m) => (
              <td key={m} className="num px-2 text-right">
                {money(Number(r[m] ?? 0), { cents: true })}
              </td>
            ))}
            {MARKET_ORDER.map((m) => (
              <td key={`v${m}`} className="num px-2 text-right">
                {compact(Number(r[`views_${m}`] ?? 0))}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A breakdown as a table with an inline magnitude bar (one hue; the table carries the numbers). */
function Breakdown({ title, rows, marketplace = false }: { title: string; rows: Schemas["BreakdownRow"][]; marketplace?: boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.earnings));
  return (
    <section aria-label={title} className="min-w-[300px] flex-1">
      <SectionTitle>{title}</SectionTitle>
      <div className="overflow-hidden rounded-[var(--radius)] border border-line bg-panel">
        <div className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: marketplace ? "minmax(0,1.3fr) 1.3fr 64px 64px 64px 72px" : "minmax(0,1.6fr) 1.3fr 70px 52px" }}>
          <span className="px-2">{marketplace ? "Marketplace" : "Name"}</span>
          <span className="px-2">Earned</span>
          <span className="px-2 text-right">Views</span>
          {marketplace ? (
            <>
              <span className="px-2 text-right">Approved</span>
              <span className="px-2 text-right">CPM</span>
              <span className="px-2 text-right">Payout</span>
            </>
          ) : (
            <span className="px-2 text-right">Posts</span>
          )}
        </div>
        {rows.length === 0 && <div className="px-2 py-2 text-muted">No earnings yet.</div>}
        {rows.map((r) => (
          <div key={r.key} className="grid h-7 items-center border-t border-line-soft" style={{ gridTemplateColumns: marketplace ? "minmax(0,1.3fr) 1.3fr 64px 64px 64px 72px" : "minmax(0,1.6fr) 1.3fr 70px 52px" }}>
            <span className="truncate-1 px-2">{marketplace ? <MarketBadge market={r.key} /> : r.label}</span>
            <span className="flex items-center gap-2 px-2">
              <span className="relative h-2 flex-1">
                <span className="absolute inset-y-0 left-0 rounded-r-[2px]" style={{ width: `${(r.earnings / max) * 100}%`, background: marketplace ? MARKET_SERIES[r.key] : "var(--series-1)" }} />
              </span>
              <span className="num w-16 text-right">{money(r.earnings, { cents: true })}</span>
            </span>
            <span className="num px-2 text-right">{compact(r.views)}</span>
            {marketplace ? (
              <>
                <span className="num px-2 text-right">{pct(r.approval_rate)}</span>
                <span className="num px-2 text-right">{r.avg_cpm !== null && r.avg_cpm !== undefined ? `$${r.avg_cpm.toFixed(2)}` : "—"}</span>
                <span className="num px-2 text-right" title={r.payout_delay_days === null ? "Payout dates aren't tracked yet" : undefined}>
                  {r.payout_delay_days !== null && r.payout_delay_days !== undefined ? `${r.payout_delay_days}d` : "—"}
                </span>
              </>
            ) : (
              <span className="num px-2 text-right">{r.posts}</span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/** Earnings: daily earnings and views by marketplace, breakdowns, top clips, unit numbers (UI.md §3.7). */
export function EarningsScreen() {
  const e = useEarnings().data;
  const manifest = useManifest().data;
  const navigate = useNavigate();
  const [table, setTable] = useState(false);
  const [topBy, setTopBy] = useState<"earnings" | "views">("earnings");
  const rows: Row[] = useMemo(
    () =>
      (e?.series ?? []).map((p) => ({
        day: p.day,
        label: day(`${p.day}T12:00:00Z`),
        ...Object.fromEntries(MARKET_ORDER.map((m) => [m, p.earnings[m] ?? 0])),
        ...Object.fromEntries(MARKET_ORDER.map((m) => [`views_${m}`, p.views[m] ?? 0])),
      })),
    [e],
  );
  const viewRows: Row[] = useMemo(() => rows.map((r) => ({ day: r.day, label: r.label, ...Object.fromEntries(MARKET_ORDER.map((m) => [m, Number(r[`views_${m}`] ?? 0)])) })), [rows]);
  if (!e) return <div className="p-4 text-muted">Loading…</div>;
  const units = e.units;
  const top = [...e.top_clips].sort((a, b) => (topBy === "views" ? b.views - a.views : 0));
  const unitTiles: [string, string, string?][] = [
    [`Earned (${e.days}d)`, money(e.total, { cents: true })],
    ["$ per clip", units["usd_per_clip"] !== null && units["usd_per_clip"] !== undefined ? money(units["usd_per_clip"], { cents: true }) : "—"],
    ["$ per GPU hour", units["usd_per_gpu_hour"] !== null && units["usd_per_gpu_hour"] !== undefined ? money(units["usd_per_gpu_hour"], { cents: true }) : "—", "GPU time isn't metered yet"],
    ["Review approval rate", pct(units["approval_rate"])],
    ["Median find → first post", units["median_find_to_post_h"] !== null && units["median_find_to_post_h"] !== undefined ? `${Math.round(units["median_find_to_post_h"])}h` : "—"],
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-auto px-4 py-3 [&>*]:shrink-0">
      <TitleRow title="Earnings" sub={`Last ${e.days} days · ${money(e.total, { cents: true })}`} actions={<Check checked={table} onChange={setTable} label="Show as table" />} />
      <div className="grid overflow-hidden rounded-[var(--radius)] border border-line bg-panel" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        {unitTiles.map(([label, value, hint], i) => (
          <div key={label} className={cn("flex flex-col px-3 py-1.5", i > 0 && "border-l border-line-soft")} title={hint}>
            <span className="text-muted">{label}</span>
            <span className="num text-[16px] font-semibold">{value}</span>
          </div>
        ))}
      </div>
      {table ? (
        <section aria-label="Daily earnings and views" className="overflow-hidden rounded-[var(--radius)] border border-line bg-panel">
          <SeriesTable rows={rows} />
        </section>
      ) : (
        <div className="flex flex-wrap gap-3.5">
          <section aria-label="Earnings per day" className="min-w-[380px] flex-[3_1_520px] rounded-[var(--radius)] border border-line bg-panel p-3">
            <SectionTitle actions={<Legend />}>Earnings per day</SectionTitle>
            <DailyChart rows={rows} label="Earnings per day by marketplace" fmt={(v) => money(v, { cents: true })} tick={(v) => `$${v}`} />
          </section>
          <section aria-label="Views per day" className="min-w-[300px] flex-[2_1_360px] rounded-[var(--radius)] border border-line bg-panel p-3">
            <SectionTitle actions={<Legend />}>Views per day</SectionTitle>
            <DailyChart rows={viewRows} label="Views per day by marketplace" fmt={(v) => compact(v)} tick={(v) => compact(v)} />
          </section>
        </div>
      )}
      <div className="flex flex-wrap gap-3.5">
        <Breakdown title="By marketplace" rows={e.by_marketplace} marketplace />
        <Breakdown title="By campaign" rows={e.by_campaign} />
      </div>
      <div className="flex flex-wrap gap-3.5">
        <Breakdown title="By social" rows={e.by_platform} />
        <Breakdown title="By account" rows={e.by_account} />
      </div>
      <section aria-label="Top clips">
        <SectionTitle
          actions={
            <span role="radiogroup" aria-label="Rank by" className="flex gap-0.5">
              {(["earnings", "views"] as const).map((k) => (
                <button key={k} role="radio" aria-checked={topBy === k} type="button" onClick={() => setTopBy(k)} className={cn("h-6 rounded-[var(--radius)] border px-2", topBy === k ? "border-accent bg-accent-soft" : "border-line")}>
                  By {k === "earnings" ? "$" : "views"}
                </button>
              ))}
            </span>
          }
        >
          Top clips
        </SectionTitle>
        <div className="overflow-hidden rounded-[var(--radius)] border border-line bg-panel">
          {top.map((c, i) => (
            <button
              key={c.id}
              type="button"
              onClick={() => void navigate({ to: "/library/$clipId", params: { clipId: String(c.id) } })}
              className="grid h-12 w-full items-center gap-2 border-b border-line-soft px-2 text-left last:border-b-0 hover:bg-[color-mix(in_srgb,var(--fg)_4%,transparent)]"
              style={{ gridTemplateColumns: "20px 24px minmax(0,1fr) 160px 56px 80px" }}
            >
              <span className="num text-muted">{i + 1}</span>
              {c.thumb_url ? <img src={fileUrl(c.thumb_url, manifest)} alt="" className="h-10 w-[22px] object-cover" /> : <span className="h-10 w-[22px] bg-media" />}
              <span className="truncate-1">{c.hook}</span>
              <span className="truncate-1 text-muted">{c.campaign_title}</span>
              <Score value={c.score} className="text-right" />
              <span className="num text-right">{compact(c.views)} views</span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
