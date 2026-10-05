// Library helpers: the statuses a clip can have, how a selection grows with clicks (like Explorer),
// and small formatters for the scrap dialogs.
import { nowMs } from "./now";

/** Every status a clip can have (core/clipper/db/types.py ClipStatus), plus the two views that are
 * not statuses in the list: Scrapped and Hidden. A test keeps this in step with the data. */
export const CLIP_STATUSES = ["draft", "rendering", "ready", "in_review", "approved", "rejected", "final", "posted", "failed"] as const;
export const LIBRARY_VIEWS = [
  ...CLIP_STATUSES.map((s) => ({ value: s as string, label: s.replace(/_/g, " ") })),
  { value: "scrapped", label: "scrapped" },
  { value: "hidden", label: "hidden" },
];

export type Selection = { ids: Set<number>; anchor: number | null };
export const EMPTY_SELECTION: Selection = { ids: new Set(), anchor: null };

/** A click on card `id` in a grid showing `order`: plain click selects it alone, Ctrl toggles it, Shift
 * selects the range from the last clicked card. */
export function clickSelect(sel: Selection, order: number[], id: number, mods: { ctrl: boolean; shift: boolean }): Selection {
  if (mods.shift && sel.anchor !== null && order.includes(sel.anchor)) {
    const a = order.indexOf(sel.anchor);
    const b = order.indexOf(id);
    const [from, to] = a < b ? [a, b] : [b, a];
    const range = order.slice(from, to + 1);
    return { ids: new Set(mods.ctrl ? [...sel.ids, ...range] : range), anchor: sel.anchor };
  }
  if (mods.ctrl) {
    const ids = new Set(sel.ids);
    if (ids.has(id)) ids.delete(id);
    else ids.add(id);
    return { ids, anchor: id };
  }
  return { ids: new Set([id]), anchor: id };
}

export const selectAll = (order: number[]): Selection => ({ ids: new Set(order), anchor: order[0] ?? null });

/** Keep only the ids that are still shown (a filter changed, clips were scrapped). */
export function prune(sel: Selection, order: number[]): Selection {
  const shown = new Set(order);
  const ids = new Set([...sel.ids].filter((i) => shown.has(i)));
  return ids.size === sel.ids.size ? sel : { ids, anchor: sel.anchor !== null && shown.has(sel.anchor) ? sel.anchor : null };
}

/** 130 MB, 1.4 GB, 12 KB. */
export function bytesLabel(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 ** 3) return `${Math.round(n / 1024 ** 2)} MB`;
  return `${(n / 1024 ** 3).toFixed(1)} GB`;
}

/** "Deleted in 5 days", "Deleted today", "Files deleted". */
export function purgeLabel(purgeAt: string | null | undefined, purged: boolean, now: number = nowMs()): string {
  if (purged) return "Files deleted";
  if (!purgeAt) return "";
  const days = Math.ceil((Date.parse(purgeAt) - now) / 86_400_000);
  if (days <= 0) return "Deleted today";
  return days === 1 ? "Deleted in 1 day" : `Deleted in ${days} days`;
}

export const SCRAP_REASONS = ["Weak hook", "Bad framing", "Off-brief", "Duplicate", "Bad source"] as const;
