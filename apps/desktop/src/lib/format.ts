// Number, money and time formatting. Numbers render in Cascadia Mono (`.num`) at the call site.
import { nowMs } from "./now";

const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const compactFmt = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const intFmt = new Intl.NumberFormat("en-US");

export function money(v: number | null | undefined, opts: { cents?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) >= 1000 && !opts.cents) return `$${compactFmt.format(v)}`;
  return (opts.cents ?? Math.abs(v) < 1000) ? usd2.format(v) : usd0.format(v);
}

export function cpm(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : usd2.format(v);
}

export function compact(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Math.abs(v) < 10_000 ? intFmt.format(v) : compactFmt.format(v);
}

export function int(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : intFmt.format(v);
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function signedPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "";
  const s = v > 0 ? "▲" : v < 0 ? "▼" : "";
  return `${s}${Math.abs(v).toFixed(Math.abs(v) >= 10 ? 0 : 1)}%`;
}

/** 42 → "0:42", 3725 → "1:02:05" */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** Seconds with tenths for timelines: 14.2 → "0:14.2" */
export function timecode(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

/** 2h 14m / 45m / 3d */
export function span(ms: number): string {
  const abs = Math.abs(ms);
  if (abs < 60_000) return "<1m";
  const min = Math.round(abs / 60_000);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h}h ${String(min % 60).padStart(2, "0")}m`;
  return `${Math.round(h / 24)}d`;
}

/** "in 2h 10m", "5m ago" */
export function relative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const delta = Date.parse(iso) - nowMs();
  if (Math.abs(delta) < 60_000) return "now";
  return delta > 0 ? `in ${span(delta)}` : `${span(delta)} ago`;
}

/** "~2 days" for run-out predictions */
export function roughly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const days = (Date.parse(iso) - nowMs()) / 86_400_000;
  if (days < 0) return "ran out";
  if (days < 1) return `~${Math.max(1, Math.round(days * 24))}h`;
  const d = Math.round(days);
  return `~${d} day${d === 1 ? "" : "s"}`;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** 14:32:07 (local time) */
export function clock(iso: string | null | undefined, seconds = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return seconds ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const dayTimeFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false });

export function day(iso: string | null | undefined): string {
  return iso ? dayFmt.format(new Date(iso)) : "—";
}

export function dayTime(iso: string | null | undefined): string {
  return iso ? dayTimeFmt.format(new Date(iso)) : "—";
}

export function titleCase(s: string): string {
  return s.length ? s[0]!.toUpperCase() + s.slice(1).replace(/_/g, " ") : s;
}
