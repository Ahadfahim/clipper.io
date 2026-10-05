// Files dragged onto the app window. Tauri reports a drop for the whole window (with real file paths),
// not for the element under the pointer, so each drop zone registers itself here and the zone under the
// pointer gets the files. A plain browser can't see where a dropped file lives, so there the zones only
// explain that (and tests can drive a drop through `window.__clipperTestDrop`).
import { FIXTURE_MODE } from "@/api/client";
import { IN_TAURI } from "./tauri";

export const VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm", "m4v", "avi"] as const;

export type DropZone = {
  el: () => HTMLElement | null;
  onHover: (over: boolean) => void;
  onDrop: (paths: string[]) => void;
};

/** "C:\Users\you\Downloads\episode.mp4" → "episode.mp4". */
export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function isVideoPath(path: string): boolean {
  const ext = /\.([^.\\/]+)$/.exec(path)?.[1]?.toLowerCase();
  return ext !== undefined && (VIDEO_EXTENSIONS as readonly string[]).includes(ext);
}

/** Explorer's "Copy as path" wraps the path in quotes. */
export function cleanPath(text: string): string {
  return text.trim().replace(/^"(.*)"$/, "$1");
}

/** What a drop of these paths means: the first video, how many files came with it, or why none will do. */
export function pickVideo(paths: string[]): { path: string; extra: number } | { error: string } {
  const video = paths.find(isVideoPath);
  if (!video) {
    return { error: paths.length === 0 ? "Nothing was dropped." : `${fileName(paths[0]!)} isn't a video. Drop an mp4, mov, mkv, webm, m4v or avi file.` };
  }
  return { path: video, extra: paths.length - 1 };
}

const zones = new Set<DropZone>();
let listening = false;

/** The registered zone under a point (physical pixels, as Tauri reports them); the newest wins. */
export function zoneAt(x: number, y: number, dpr: number = window.devicePixelRatio || 1): DropZone | undefined {
  const px = x / dpr;
  const py = y / dpr;
  return [...zones].reverse().find((z) => {
    const r = z.el()?.getBoundingClientRect();
    return r !== undefined && px >= r.left && px <= r.right && py >= r.top && py <= r.bottom;
  });
}

let hovered: DropZone | undefined;
function hover(next: DropZone | undefined) {
  if (next === hovered) return;
  hovered?.onHover(false);
  hovered = next;
  next?.onHover(true);
}

type DragPayload =
  | { type: "enter" | "over"; position: { x: number; y: number }; paths?: string[] }
  | { type: "drop"; position: { x: number; y: number }; paths: string[] }
  | { type: "leave" };

export function handleDrag(p: DragPayload): void {
  if (p.type === "leave") return hover(undefined);
  const zone = zoneAt(p.position.x, p.position.y);
  if (p.type === "drop") {
    hover(undefined);
    zone?.onDrop(p.paths);
    return;
  }
  hover(zone);
}

async function listen() {
  if (listening || !IN_TAURI) return;
  listening = true;
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  await getCurrentWebview().onDragDropEvent((e) => handleDrag(e.payload as DragPayload));
}

/** Make an element take dropped files. Returns the function that stops it. */
export function registerDropZone(zone: DropZone): () => void {
  zones.add(zone);
  void listen();
  return () => {
    zones.delete(zone);
    if (hovered === zone) hovered = undefined;
  };
}

declare global {
  interface Window {
    /** Fixture and dev builds only: drop these paths on the newest zone, as the desktop app would. */
    __clipperTestDrop?: (paths: string[]) => boolean;
  }
}

if (typeof window !== "undefined" && (FIXTURE_MODE || import.meta.env.DEV)) {
  window.__clipperTestDrop = (paths) => {
    const zone = [...zones].pop();
    zone?.onDrop(paths);
    return zone !== undefined;
  };
}
