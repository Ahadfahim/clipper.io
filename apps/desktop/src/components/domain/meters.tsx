import { useId, useState } from "react";
import { cn } from "@/lib/cn";
import { money, pct, relative, roughly, signedPct, span } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { MARKET_LABEL, MARKET_SERIES } from "@/lib/platforms";
import { Tooltip } from "@/components/ui/misc";
import type { Schemas } from "@/api/client";

/** 2px line in the de-emphasis gray, current value as an accent end-dot; hover shows each point. */
export function Sparkline({ values, width = 72, height = 22, label }: { values: number[]; width?: number; height?: number; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (values.length < 2) return <span style={{ width, height }} className="inline-block" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 4;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / (values.length - 1);
  const y = (v: number) => height - pad - ((v - min) / (max - min || 1)) * (height - 2 * pad);
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const last = values.length - 1;
  const hi = hover ?? last;
  return (
    <span className="relative inline-flex">
      <svg width={width} height={height} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        <polyline points={pts} fill="none" stroke="var(--series-muted)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={height} stroke="var(--line)" strokeWidth={1} />}
        <circle cx={x(hi)} cy={y(values[hi]!)} r={3.5} fill="var(--accent)" stroke="var(--panel)" strokeWidth={1.5} />
        {values.map((_, i) => (
          <rect key={i} x={x(i) - (width / values.length) / 2} y={0} width={width / values.length} height={height} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hover !== null && (
        <span className="num pointer-events-none absolute -top-5 left-1/2 z-10 -translate-x-1/2 rounded-[3px] border border-line bg-panel px-1 text-[11px] whitespace-nowrap shadow">
          {values[hover]!.toLocaleString("en-US", { maximumFractionDigits: 2 })}
        </span>
      )}
    </span>
  );
}

/** One cell of the KPI strip: label, value, change vs yesterday, 14-day sparkline. */
export function KpiTile({ kpi, className }: { kpi: Schemas["Kpi"]; className?: string }) {
  const good = kpi.delta_pct !== null && kpi.delta_pct !== undefined && kpi.delta_pct >= 0;
  const body = (
    <div className={cn("flex min-w-0 items-center gap-3 px-3 py-1.5", className)}>
      <div className="flex min-w-0 flex-col">
        <span className="truncate-1 text-muted">{kpi.label}</span>
        <span className="flex items-baseline gap-1.5">
          <span className="num text-[16px] font-semibold">{kpi.display}</span>
          {kpi.delta_pct !== null && kpi.delta_pct !== undefined && (
            <span className={cn("num text-[11px]", good ? "text-ok" : "text-bad")}>
              {signedPct(kpi.delta_pct)} <span className="sr-only">vs yesterday</span>
            </span>
          )}
        </span>
      </div>
      <span className="flex-1" />
      {kpi.spark.length > 1 && <Sparkline values={kpi.spark} label={`${kpi.label}, last ${kpi.spark.length} days`} />}
    </div>
  );
  if (!kpi.split) return body;
  return (
    <Tooltip
      content={
        <div className="flex flex-col gap-0.5">
          <span className="text-muted">By marketplace</span>
          {Object.entries(kpi.split).map(([m, v]) => (
            <span key={m} className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-[2px]" style={{ background: MARKET_SERIES[m] }} />
              <span className="w-12">{MARKET_LABEL[m] ?? m}</span>
              <span className="num">{money(v, { cents: true })}</span>
            </span>
          ))}
        </div>
      }
    >
      <div tabIndex={0}>{body}</div>
    </Tooltip>
  );
}

/** Claude plan usage in the current window: accent, amber from 80%, red at the limit. */
export function UsageMeter({ usage, compact = false, className }: { usage: Schemas["UsageOut"]; compact?: boolean; className?: string }) {
  const u = usage.utilization;
  const fill = u >= 0.95 || usage.rate_limited ? "var(--bad)" : u >= 0.8 ? "var(--warn-strong)" : "var(--accent)";
  const resets = usage.resets_at ? span(Date.parse(usage.resets_at) - nowMs()) : null;
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        role="meter"
        aria-label="Claude usage"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(u * 100)}
        className="relative inline-block h-1.5 overflow-hidden rounded-[2px]"
        style={{ width: compact ? 48 : 120, background: `color-mix(in srgb, ${fill} 22%, transparent)` }}
      >
        <span className="absolute inset-y-0 left-0" style={{ width: `${Math.min(1, u) * 100}%`, background: fill }} />
      </span>
      <span className="num">{pct(u)}</span>
      {!compact && resets && <span className="text-muted">resets in {resets}</span>}
      {usage.rate_limited && <span className="text-bad">rate limited</span>}
    </span>
  );
}

/** Budget left with a marker where it's predicted to run out (relative to the deadline). */
export function BudgetBurnBar({
  left,
  total,
  runsOut,
  deadline,
  className,
}: {
  left: number | null | undefined;
  total: number | null | undefined;
  runsOut: string | null | undefined;
  deadline: string | null | undefined;
  className?: string;
}) {
  const share = left !== null && left !== undefined && total ? Math.max(0, Math.min(1, left / total)) : null;
  const now = nowMs();
  const marker =
    runsOut && deadline && Date.parse(deadline) > now ? Math.max(0, Math.min(1, (Date.parse(runsOut) - now) / (Date.parse(deadline) - now))) : null;
  const early = marker !== null && marker < 1;
  const label = `Budget left ${money(left)}${total ? ` of ${money(total)}` : ""}${runsOut ? `, runs out ${roughly(runsOut)}` : ""}`;
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)} title={label}>
      <span role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={share === null ? undefined : Math.round(share * 100)} className="relative inline-block h-1.5 min-w-[40px] flex-1 border border-line bg-panel-2">
        {share !== null && <span className="absolute inset-y-0 left-0 bg-muted" style={{ width: `${share * 100}%` }} />}
        {marker !== null && <span aria-hidden="true" className={cn("absolute -top-1 -bottom-1 w-0.5", early ? "bg-warn-strong" : "bg-fg")} style={{ left: `calc(${marker * 100}% - 1px)` }} />}
      </span>
      <span className="num shrink-0">{money(left)}</span>
    </span>
  );
}

export function RunsOut({ at, deadline }: { at: string | null | undefined; deadline?: string | null }) {
  const early = at && deadline && Date.parse(at) < Date.parse(deadline);
  return <span className={cn(early ? "text-warn" : "")} title={at ? `Predicted to run out ${relative(at)}` : undefined}>{roughly(at)}</span>;
}

/** Brief → Sources → Analyze → Clips → Review → Post → Submit. */
export function StageStepper({ stages, showLabel = true, className }: { stages: Schemas["Stage"][]; showLabel?: boolean; className?: string }) {
  const id = useId();
  const activeIdx = stages.findIndex((s) => s.state === "active");
  const current = stages[activeIdx] ?? stages[stages.length - 1];
  const label = current ? `${current.name} (${activeIdx >= 0 ? activeIdx + 1 : stages.length} of ${stages.length})` : "";
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)} aria-labelledby={id}>
      <span className="flex min-w-[84px] flex-1 items-center gap-0.5" title={stages.map((s) => `${s.name}: ${s.state}`).join(" · ")}>
        {stages.map((s) => (
          <span
            key={s.name}
            className={cn("h-2 flex-1", s.state === "done" ? "bg-ok" : s.state === "active" ? "bg-warn-strong" : "bg-line")}
          />
        ))}
      </span>
      {showLabel && (
        <span id={id} className="shrink-0 text-muted">
          {current?.name}
        </span>
      )}
      {!showLabel && <span id={id} className="sr-only">{label}</span>}
    </span>
  );
}
