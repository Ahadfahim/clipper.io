// Read-only view of the EDL JSON (core/clipper/media/edl/schema.py) for the Edit preview and
// timeline. Segments, camera keys and captions are in SOURCE time; overlays in OUTPUT time.

export type EdlSegment = { start: number; end: number; kind: string };
export type EdlCameraKey = { t: number; layout: "crop" | "split" | "fit" | string; focus_x: number; focus_y: number; zoom: number; focus2_x: number | null };
export type EdlWord = { t: number; end: number; text: string; emphasis: boolean; speaker: string | null };
export type EdlOverlay = { id: string; type: string; t_in: number; t_out: number; props: Record<string, unknown> };
export type Edl = {
  segments: EdlSegment[];
  camera: EdlCameraKey[];
  captions: { enabled: boolean; style: string; words: EdlWord[]; safe_zone: string; max_words_per_line: number };
  overlays: EdlOverlay[];
  hook: { type: string; text: string | null; range: number[] | null };
  output: { width: number; height: number; fps: number };
  source: { duration: number; width: number; height: number };
};

export type Span<T = undefined> = { from: number; to: number; data: T };

export function asEdl(raw: Record<string, unknown>): Edl {
  const e = raw as Partial<Edl>;
  return {
    segments: e.segments ?? [],
    camera: e.camera ?? [],
    captions: e.captions ?? { enabled: false, style: "clean", words: [], safe_zone: "none", max_words_per_line: 3 },
    overlays: e.overlays ?? [],
    hook: e.hook ?? { type: "none", text: null, range: null },
    output: e.output ?? { width: 1080, height: 1920, fps: 30 },
    source: e.source ?? { duration: 0, width: 1920, height: 1080 },
  };
}

/** Kept segments with their output-time offsets. */
export function outputSegments(edl: Edl): { start: number; end: number; outStart: number; outEnd: number }[] {
  let t = 0;
  return [...edl.segments]
    .sort((a, b) => a.start - b.start)
    .map((s) => {
      const len = Math.max(0, s.end - s.start);
      const out = { start: s.start, end: s.end, outStart: t, outEnd: t + len };
      t += len;
      return out;
    });
}

export function outputDuration(edl: Edl): number {
  const segs = outputSegments(edl);
  return segs.length ? segs[segs.length - 1]!.outEnd : 0;
}

/** Source time → output time, or null when that moment was cut. */
export function srcToOut(edl: Edl, t: number): number | null {
  for (const s of outputSegments(edl)) if (t >= s.start && t <= s.end) return s.outStart + (t - s.start);
  return null;
}

/** Output time → source time. */
export function outToSrc(edl: Edl, t: number): number {
  const segs = outputSegments(edl);
  for (const s of segs) if (t >= s.outStart && t <= s.outEnd) return s.start + (t - s.outStart);
  return segs.length ? segs[segs.length - 1]!.end : 0;
}

/** A source-time range clipped to what survives, in output time (for the violet agent range). */
export function srcRangeToOut(edl: Edl, from: number, to: number): [number, number] | null {
  const parts = outputSegments(edl)
    .map((s) => [Math.max(from, s.start), Math.min(to, s.end), s] as const)
    .filter(([a, b]) => b > a)
    .map(([a, b, s]) => [s.outStart + (a - s.start), s.outStart + (b - s.start)] as const);
  if (!parts.length) return null;
  return [parts[0]![0], parts[parts.length - 1]![1]];
}

/** Camera layout spans in output time (a layout holds until the next key). */
export function cameraSpans(edl: Edl): Span<EdlCameraKey>[] {
  const total = outputDuration(edl);
  const keys = [...edl.camera].sort((a, b) => a.t - b.t);
  const spans: Span<EdlCameraKey>[] = [];
  keys.forEach((k, i) => {
    const from = srcToOut(edl, k.t) ?? (i === 0 ? 0 : null);
    if (from === null) return;
    const nextKey = keys[i + 1];
    const to = nextKey ? (srcToOut(edl, nextKey.t) ?? total) : total;
    const prev = spans[spans.length - 1];
    if (prev && prev.data.layout === k.layout) prev.to = to;
    else spans.push({ from, to, data: k });
  });
  if (!spans.length && total > 0) spans.push({ from: 0, to: total, data: { t: 0, layout: "crop", focus_x: 0.5, focus_y: 0.5, zoom: 1, focus2_x: null } });
  if (spans[0]) spans[0].from = 0;
  return spans;
}

export type IndexedWord = EdlWord & { index: number };

/** Caption words that survive the cut, in output time (`index` = position in the EDL word list). */
export function captionSpans(edl: Edl): Span<IndexedWord>[] {
  return edl.captions.words
    .map((w, index) => {
      if (!w.text) return null; // hidden word
      const a = srcToOut(edl, w.t);
      const b = srcToOut(edl, w.end);
      return a === null || b === null ? null : { from: a, to: b, data: { ...w, index } };
    })
    .filter((x): x is Span<IndexedWord> => x !== null);
}

/** Words on screen at output time t, grouped like the renderer (max words per line). */
export function captionAt(edl: Edl, t: number): { words: IndexedWord[]; active: number } | null {
  const spans = captionSpans(edl);
  const idx = spans.findIndex((s) => t >= s.from && t < s.to);
  if (idx < 0) return null;
  const per = Math.max(1, edl.captions.max_words_per_line);
  const start = Math.floor(idx / per) * per;
  return { words: spans.slice(start, start + per).map((s) => s.data), active: idx - start };
}

/** Camera key in effect at output time t. */
export function cameraAt(edl: Edl, t: number): EdlCameraKey | undefined {
  return cameraSpans(edl).find((s) => t >= s.from && t < s.to)?.data ?? cameraSpans(edl)[0]?.data;
}
