import { cn } from "@/lib/cn";
import { MARKET_LABEL, MARKET_SERIES, PLATFORM_LABEL, PLATFORM_SHORT } from "@/lib/platforms";
import { Dot, type StatusTone } from "@/components/ui/status";

/** Vyro / Whop label with its series swatch (color follows the marketplace everywhere). */
export function MarketBadge({ market, className }: { market: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span aria-hidden="true" className="inline-block size-2 rounded-[2px]" style={{ background: MARKET_SERIES[market] ?? "var(--muted)" }} />
      {MARKET_LABEL[market] ?? market}
    </span>
  );
}

export function PlatformTag({ platform, on = true, className }: { platform: string; on?: boolean; className?: string }) {
  return (
    <span
      title={PLATFORM_LABEL[platform] ?? platform}
      className={cn(
        "num inline-flex h-[18px] min-w-[24px] items-center justify-center rounded-[3px] border px-1 text-[10px] leading-none",
        on ? "border-line text-fg" : "border-dashed border-line text-faint",
        className,
      )}
    >
      {PLATFORM_SHORT[platform] ?? platform}
    </span>
  );
}

export function accountTone(status: string, enabled = true): StatusTone {
  if (!enabled) return "off";
  if (status === "active") return "ok";
  if (status.startsWith("paused")) return "warn";
  if (status === "blocked" || status === "failed") return "bad";
  return "muted";
}

/** Platform + handle + health dot. */
export function AccountChip({ platform, handle, status = "active", enabled = true, className }: { platform: string; handle: string; status?: string; enabled?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", !enabled && "text-faint", className)}>
      <Dot tone={accountTone(status, enabled)} />
      <PlatformTag platform={platform} on={enabled} />
      <span className="truncate-1">{handle}</span>
    </span>
  );
}

/** Score as a mono number; 80+ reads green (the review threshold), under 60 muted. */
export function Score({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) return <span className={cn("num text-muted", className)}>—</span>;
  return <span className={cn("num", value >= 80 ? "text-ok" : value < 60 ? "text-muted" : "", className)}>{Math.round(value)}</span>;
}
