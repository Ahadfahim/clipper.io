// Keyboard shortcuts (UI.md §6). Combos look like "ctrl+k", "ctrl+shift+p", "a", "shift+a", "arrowleft".
import { useEffect, useRef } from "react";

export function comboOf(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  const key = e.key === " " ? "space" : e.key.toLowerCase();
  if (!["control", "meta", "alt", "shift"].includes(key)) parts.push(key);
  return parts.join("+");
}

/** True when the key press belongs to a text field (single-letter shortcuts must not fire there). */
export function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || t.isContentEditable;
}

type Handlers = Record<string, (e: KeyboardEvent) => void>;

/**
 * Binds shortcuts while the component is mounted. Plain-letter combos are ignored while typing;
 * ctrl combos always fire. Handlers are read through a ref, so callers can pass inline objects.
 */
export function useHotkeys(handlers: Handlers, enabled = true): void {
  const ref = useRef(handlers);
  ref.current = handlers;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const combo = comboOf(e);
      const fn = ref.current[combo];
      if (!fn) return;
      if (isTyping(e) && !combo.startsWith("ctrl+") && combo !== "escape") return;
      e.preventDefault();
      fn(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
