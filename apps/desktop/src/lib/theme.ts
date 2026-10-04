// Applies theme (system/light/dark), density and accent to <html>; see styles/tokens.css.
import { useEffect } from "react";
import { useUi } from "@/state/ui";
import { windowsAccent } from "./tauri";

/** Black or white text on an accent fill, whichever contrasts more (WCAG relative luminance). */
export function inkFor(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "#ffffff";
  const n = parseInt(m[1]!, 16);
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? "#000000" : "#ffffff";
}

export function applyAppearance(
  root: HTMLElement,
  opts: { theme: "system" | "light" | "dark"; density: "compact" | "comfortable"; accent: string | null },
): void {
  if (opts.theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", opts.theme);
  root.setAttribute("data-density", opts.density);
  if (opts.accent) {
    root.style.setProperty("--accent-user", opts.accent);
    root.style.setProperty("--accent-user-ink", inkFor(opts.accent));
    root.setAttribute("data-accent", "user");
  } else {
    root.removeAttribute("data-accent");
  }
}

/** Keeps <html> in sync with the UI store; picks up the Windows accent in the desktop app. */
export function useAppearance(): void {
  const theme = useUi((s) => s.theme);
  const density = useUi((s) => s.density);
  const accent = useUi((s) => s.accent);
  const systemAccent = useUi((s) => s.systemAccent);
  const setSystemAccent = useUi((s) => s.setSystemAccent);

  useEffect(() => {
    void windowsAccent().then((a) => a && setSystemAccent(a));
  }, [setSystemAccent]);

  useEffect(() => {
    applyAppearance(document.documentElement, { theme, density, accent: accent ?? systemAccent });
  }, [theme, density, accent, systemAccent]);
}
