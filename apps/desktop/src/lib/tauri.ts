// Thin wrapper over the Tauri APIs: every call is a no-op in a plain browser (dev, fixtures,
// Playwright), so screens never branch on the runtime themselves.
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export const IN_TAURI: boolean = typeof window !== "undefined" && isTauri();

export async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | undefined> {
  if (!IN_TAURI) return undefined;
  return invoke<T>(cmd, args);
}

/** Windows accent color as "#rrggbb" (src-tauri/src/theme.rs), or undefined outside the desktop app. */
export function windowsAccent(): Promise<string | undefined> {
  return call<string>("accent_color");
}

/** Native menu items and tray actions arrive as `menu` events carrying a command id (src/shell/commands.ts). */
export async function onNativeMenu(handler: (command: string) => void): Promise<UnlistenFn> {
  if (!IN_TAURI) return () => undefined;
  return listen<string>("menu", (e) => handler(e.payload));
}

/** Pop Review or Edit out into its own window (src-tauri/src/windows.rs); in a browser, open a tab. */
export async function popOut(kind: "review" | "edit", id: number): Promise<void> {
  const path = `/popout/${kind}/${id}`;
  if (IN_TAURI) {
    await invoke("pop_out", { kind, id, path });
  } else {
    window.open(path, `${kind}-${id}`, "popup,width=1080,height=1920");
  }
}

/** Windows toast (tauri-plugin-notification); the browser build logs instead. */
export async function toast(title: string, body: string): Promise<void> {
  if (!IN_TAURI) return;
  await invoke("notify", { title, body });
}

/** External links open in the default browser (never inside the app window). */
export async function openUrl(url: string): Promise<void> {
  if (!/^https?:\/\//.test(url)) return;
  if (IN_TAURI) await invoke("open_url", { url });
  else window.open(url, "_blank", "noopener,noreferrer");
}

export async function openPath(path: string): Promise<void> {
  await call("open_path", { path });
}

/** Opens the Chrome window of a Clipper profile; the core launches Chrome (it knows the paths). */
export async function openProfile(profile: string): Promise<void> {
  const { api } = await import("@/api/client");
  await api.POST("/api/browser/profiles/{profile}/open", { params: { path: { profile } } });
}

export async function quitApp(): Promise<void> {
  await call("quit");
}

export function autostartGet(): Promise<boolean | undefined> {
  return call<boolean>("autostart_get");
}

export async function autostartSet(enabled: boolean): Promise<void> {
  await call("autostart_set", { enabled });
}

/** Keeps the native tray menu (Pause all / Dry run checkmarks, today's stats) in sync. */
export async function syncTray(state: { paused: boolean; dryRun: boolean; today: string }): Promise<void> {
  await call("sync_tray", state);
}
