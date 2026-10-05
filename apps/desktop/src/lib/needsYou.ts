// Helpers for the Needs you list: item keys, ages, and which buttons a collapsed row shows.
import type { Schemas } from "@/api/client";
import { nowMs } from "./now";

export type NeedsItem = Schemas["NeedsYouItem"];
export type NeedsAction = Schemas["NeedsYouAction"];

/** Keys have colons ("failure:job:2"); addresses and fixture file names use dashes. */
export const slugOf = (key: string): string => key.replace(/:/g, "-");

/** "4m", "2h", "3d": how long an item has waited (Cascadia Mono, so it lines up). */
export function age(iso: string | null | undefined, now: number = nowMs()): string {
  if (!iso) return "";
  const ms = Math.max(0, now - Date.parse(iso));
  const m = Math.floor(ms / 60_000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

/** Answer buttons that fit in a row (Yes / No / Skip). Anything longer waits for the expanded view. */
export const SHORT_OPTION = 16;
export const MAX_INLINE_OPTIONS = 3;

export function fitsInline(options: string[]): boolean {
  return options.length > 0 && options.length <= MAX_INLINE_OPTIONS && options.every((o) => o.length <= SHORT_OPTION);
}

/** What a collapsed row shows: at most two buttons, never a wall of long answers. */
export function inlineActions(item: NeedsItem): NeedsAction[] {
  if (item.kind === "question") {
    return fitsInline(item.options) ? item.actions : [{ label: "Answer", action: "expand", args: {} }];
  }
  if (item.kind === "alert") return item.actions.slice(0, 1);
  return item.actions.slice(0, 2);
}

/** Minutes → the label on the snooze menu. */
export function snoozeLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`;
  if (minutes === 60) return "1 hour";
  if (minutes < 1440) return `${minutes / 60} hours`;
  return minutes === 1440 ? "1 day" : `${minutes / 1440} days`;
}
