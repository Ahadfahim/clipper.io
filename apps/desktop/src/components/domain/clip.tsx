import { ArrowStepBack16Regular, ArrowStepOver16Regular, Pause16Filled, Play16Filled, Speaker216Regular, SpeakerMute16Regular } from "@fluentui/react-icons";
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { compact, duration, timecode } from "@/lib/format";
import { Dot, type StatusTone } from "@/components/ui/status";
import { PlatformTag, Score } from "./badges";
import type { Schemas } from "@/api/client";

const NONE: never[] = [];

export function clipTone(c: Pick<Schemas["ClipRow"], "status" | "decision">): StatusTone {
  if (c.decision === "approved" || c.status === "posted" || c.status === "approved") return "ok";
  if (c.decision === "rejected" || c.status === "failed" || c.status === "rejected") return "bad";
  if (c.status === "in_review" || c.decision === "pending") return "warn";
  if (c.status === "rendering" || c.status === "recut" || c.status === "editing") return "agent";
  return "muted";
}

/** 9:16 thumbnail card (Library, Review queue): score, length, status, platforms, views; plays on hover. */
export function ClipCard({
  clip,
  thumb,
  preview,
  selected,
  onOpen,
  className,
}: {
  clip: Schemas["ClipRow"];
  thumb?: string;
  preview?: string;
  selected?: boolean;
  onOpen?: () => void;
  className?: string;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onOpen}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      className={cn(
        "group flex w-full flex-col overflow-hidden rounded-[var(--radius)] border bg-panel text-left",
        selected ? "border-accent outline-1 outline-accent" : "border-line hover:border-muted",
        className,
      )}
    >
      <span className="relative block aspect-[9/16] w-full bg-media">
        {hover && preview ? (
          <video src={preview} poster={thumb} autoPlay muted loop playsInline className="absolute inset-0 size-full object-cover" />
        ) : thumb ? (
          <img src={thumb} alt="" loading="lazy" className="absolute inset-0 size-full object-cover" />
        ) : null}
        <span className="absolute top-1 left-1 rounded-[3px] bg-black/70 px-1 text-white">
          <Score value={clip.score} className={clip.score >= 80 ? "text-[#6ccb5f]" : "text-white"} />
        </span>
        <span className="num absolute top-1 right-1 rounded-[3px] bg-black/70 px-1 text-white">{duration(clip.duration)}</span>
        {clip.editing_live && <span className="absolute bottom-1 left-1 rounded-[3px] bg-black/75 px-1 text-[11px] text-[#cfc2ff]">Editing live</span>}
      </span>
      <span className="flex flex-col gap-1 px-1.5 py-1">
        <span className="truncate-1">{clip.hook || `Clip ${clip.id}`}</span>
        <span className="flex items-center gap-1 text-muted">
          <Dot tone={clipTone(clip)} />
          <span className="truncate-1 flex-1">{clip.status.replace(/_/g, " ")}</span>
          {clip.platforms_posted.map((p) => (
            <PlatformTag key={p} platform={p} />
          ))}
          {clip.views > 0 && <span className="num">{compact(clip.views)}</span>}
        </span>
      </span>
    </button>
  );
}

export type PlayerHandle = {
  toggle: () => void;
  step: (frames: number) => void;
  seek: (t: number) => void;
  video: HTMLVideoElement | null;
};

/** Native <video> with frame stepping and an optional trim strip (Re-cut). */
export const ClipPlayer = forwardRef<
  PlayerHandle,
  {
    src?: string;
    poster?: string;
    autoPlay?: boolean;
    width?: number;
    fps?: number;
    onTime?: (t: number) => void;
    overlay?: ReactNode;
    trim?: { start: number; end: number; extra: number; onChange: (start: number, end: number) => void } | null;
    className?: string;
    label: string;
  }
>(function ClipPlayer({ src, poster, autoPlay = true, width = 252, fps = 30, onTime, overlay, trim, className, label }, ref) {
  const v = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);

  useImperativeHandle(ref, () => ({
    toggle: () => {
      const el = v.current;
      if (!el) return;
      if (el.paused) void el.play().catch(() => undefined);
      else el.pause();
    },
    step: (frames: number) => {
      const el = v.current;
      if (!el) return;
      el.pause();
      el.currentTime = Math.max(0, Math.min(el.duration || 0, el.currentTime + frames / fps));
    },
    seek: (time: number) => {
      if (v.current) v.current.currentTime = time;
    },
    video: v.current,
  }));

  useEffect(() => {
    setT(0);
  }, [src]);

  const scrub = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (v.current && dur) v.current.currentTime = ((e.clientX - r.left) / r.width) * dur;
  };

  return (
    <div className={cn("flex flex-col items-center gap-2", className)} style={{ width }}>
      <div className="relative w-full overflow-hidden border border-line bg-media" style={{ aspectRatio: "9 / 16" }}>
        {src ? (
          <video
            ref={v}
            key={src}
            src={src}
            poster={poster}
            aria-label={label}
            autoPlay={autoPlay}
            muted={muted}
            loop
            playsInline
            onTimeUpdate={(e) => {
              setT(e.currentTarget.currentTime);
              onTime?.(e.currentTarget.currentTime);
            }}
            onLoadedMetadata={(e) => setDur(e.currentTarget.duration)}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            className="absolute inset-0 size-full object-contain"
          />
        ) : (
          poster && <img src={poster} alt="" className="absolute inset-0 size-full object-contain" />
        )}
        {overlay}
      </div>
      <div className="flex w-full items-center gap-1">
        <button type="button" aria-label="Previous frame" title="Previous frame (,)" onClick={() => (v.current ? ((v.current.currentTime -= 1 / fps), v.current.pause()) : undefined)} className="flex size-6 items-center justify-center rounded-[3px] hover:bg-panel-2">
          <ArrowStepBack16Regular />
        </button>
        <button type="button" aria-label={playing ? "Pause" : "Play"} title="Play/pause (Space)" onClick={() => (v.current?.paused ? void v.current.play().catch(() => undefined) : v.current?.pause())} className="flex size-6 items-center justify-center rounded-[3px] hover:bg-panel-2">
          {playing ? <Pause16Filled /> : <Play16Filled />}
        </button>
        <button type="button" aria-label="Next frame" title="Next frame (.)" onClick={() => (v.current ? ((v.current.currentTime += 1 / fps), v.current.pause()) : undefined)} className="flex size-6 items-center justify-center rounded-[3px] hover:bg-panel-2">
          <ArrowStepOver16Regular />
        </button>
        <span className="num w-9 text-right text-muted">{duration(t)}</span>
        <div role="slider" aria-label="Seek" aria-valuemin={0} aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(t)} tabIndex={0} onClick={scrub} className="relative mx-1 h-4 flex-1 cursor-pointer">
          <span className="absolute inset-x-0 top-1.5 h-1 bg-line" />
          <span className="absolute top-1.5 left-0 h-1 bg-accent" style={{ width: dur ? `${(t / dur) * 100}%` : 0 }} />
        </div>
        <span className="num w-9 text-muted">{duration(dur)}</span>
        <button type="button" aria-label={muted ? "Unmute" : "Mute"} onClick={() => setMuted(!muted)} className="flex size-6 items-center justify-center rounded-[3px] hover:bg-panel-2">
          {muted ? <SpeakerMute16Regular /> : <Speaker216Regular />}
        </button>
      </div>
      {trim && <TrimStrip {...trim} length={dur || 0} />}
    </div>
  );
});

/** Re-cut trim handles with ±extra seconds of source visible on each side. */
function TrimStrip({ start, end, extra, length, onChange }: { start: number; end: number; extra: number; length: number; onChange: (s: number, e: number) => void }) {
  const total = length + 2 * extra || 1;
  const left = ((extra + start) / total) * 100;
  const right = ((extra + length + end) / total) * 100;
  const bar = useRef<HTMLDivElement>(null);
  const drag = (which: "start" | "end") => (e: React.PointerEvent) => {
    const el = bar.current;
    if (!el) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const sec = ((ev.clientX - r.left) / r.width) * total - extra;
      if (which === "start") onChange(Math.max(-extra, Math.min(sec, length + end - 1)), end);
      else onChange(start, Math.max(start - length + 1, Math.min(sec - length, extra)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const key = (which: "start" | "end") => (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowLeft" ? -0.1 : e.key === "ArrowRight" ? 0.1 : 0;
    if (!d) return;
    e.preventDefault();
    e.stopPropagation();
    if (which === "start") onChange(Math.max(-extra, start + d), end);
    else onChange(start, Math.min(extra, end + d));
  };
  return (
    <div className="flex w-full flex-col gap-1">
      <div ref={bar} className="relative h-6 w-full border border-line bg-panel-2">
        <span className="absolute inset-y-0 bg-accent-soft" style={{ left: `${left}%`, right: `${100 - right}%` }} />
        <span className="absolute inset-y-0 border-l border-dashed border-muted" style={{ left: `${(extra / total) * 100}%` }} />
        <span className="absolute inset-y-0 border-l border-dashed border-muted" style={{ left: `${((extra + length) / total) * 100}%` }} />
        {(["start", "end"] as const).map((w) => (
          <span
            key={w}
            role="slider"
            tabIndex={0}
            aria-label={w === "start" ? "Trim start" : "Trim end"}
            aria-valuenow={Number((w === "start" ? start : end).toFixed(1))}
            onPointerDown={drag(w)}
            onKeyDown={key(w)}
            className="absolute inset-y-[-3px] w-2 cursor-ew-resize rounded-[2px] bg-accent"
            style={{ left: `calc(${w === "start" ? left : right}% - 4px)` }}
          />
        ))}
      </div>
      <div className="num flex justify-between text-[11px] text-muted">
        <span>start {start >= 0 ? "+" : ""}{start.toFixed(1)}s</span>
        <span>end {end >= 0 ? "+" : ""}{end.toFixed(1)}s</span>
      </div>
    </div>
  );
}

/** Words highlight as the video plays; click a word to seek there. */
export function TranscriptView({ words, time, onSeek, className }: { words: Schemas["WordOut"][]; time: number; onSeek?: (t: number) => void; className?: string }) {
  const activeRef = useRef<HTMLButtonElement>(null);
  const active = words.findIndex((w) => time >= w.t && time < w.end);
  useLayoutEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [active]);
  return (
    <div className={cn("selectable flex flex-wrap content-start gap-x-1 gap-y-0.5 p-3 leading-6", className)}>
      {words.map((w, i) => (
        <button
          key={i}
          ref={i === active ? activeRef : undefined}
          type="button"
          onClick={() => onSeek?.(w.t)}
          title={timecode(w.t)}
          className={cn("rounded-[2px] px-0.5", i === active ? "bg-accent text-accent-ink" : time > w.end ? "text-fg" : "text-muted", "hover:outline-1 hover:outline-line")}
        >
          {w.text}
        </button>
      ))}
    </div>
  );
}

/**
 * The whole source: replay heatmap (one hue, more is darker), scene cuts and energy spikes, with
 * this clip's window highlighted and other strong moments shown faintly. Hover reads the value.
 */
export function SignalTimeline({
  signals,
  range,
  moments = NONE,
  height = 64,
  className,
}: {
  signals: Record<string, unknown>;
  range: number[];
  moments?: { start: number; end: number }[];
  height?: number;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number; v: number } | null>(null);
  const heat = (signals["heatmap"] as number[] | undefined) ?? NONE;
  const total = Number(signals["source_duration"] ?? signals["duration"] ?? 0) || 1;
  const cuts = (signals["scene_cuts"] as number[] | undefined) ?? NONE;
  const spikes = (signals["energy_spikes"] as { t: number }[] | undefined) ?? NONE;

  useEffect(() => {
    const canvas = ref.current;
    const box = wrap.current;
    if (!canvas || !box) return;
    const draw = () => {
      const w = box.clientWidth;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const css = getComputedStyle(canvas);
      const col = (n: string) => css.getPropertyValue(n).trim() || "#888";
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, height);
      const plotH = height - 14;
      // moment windows (faint), this clip's window (accent wash)
      for (const m of moments) {
        ctx.fillStyle = col("--line");
        ctx.fillRect((m.start / total) * w, 0, Math.max(1, ((m.end - m.start) / total) * w), plotH);
      }
      if (range.length === 2) {
        ctx.fillStyle = col("--accent-soft");
        ctx.fillRect((range[0]! / total) * w, 0, Math.max(2, ((range[1]! - range[0]!) / total) * w), plotH);
      }
      // heatmap columns: single hue (series-1), opacity carries magnitude
      const bw = w / Math.max(1, heat.length);
      heat.forEach((v, i) => {
        const h = Math.max(1, v * (plotH - 4));
        ctx.globalAlpha = 0.25 + 0.75 * v;
        ctx.fillStyle = col("--series-1");
        ctx.fillRect(i * bw + 1, plotH - h, Math.max(1, bw - 2), h);
      });
      ctx.globalAlpha = 1;
      // baseline, scene cuts (ticks), energy spikes (dots)
      ctx.fillStyle = col("--line");
      ctx.fillRect(0, plotH, w, 1);
      ctx.fillStyle = col("--muted");
      for (const c of cuts) ctx.fillRect((c / total) * w, plotH + 2, 1, 5);
      ctx.fillStyle = col("--agent");
      for (const s of spikes) {
        ctx.beginPath();
        ctx.arc((s.t / total) * w, plotH + 9, 3, 0, Math.PI * 2);
        ctx.fill();
      }
      if (range.length === 2) {
        ctx.strokeStyle = col("--accent");
        ctx.lineWidth = 1;
        ctx.strokeRect((range[0]! / total) * w + 0.5, 0.5, Math.max(2, ((range[1]! - range[0]!) / total) * w) - 1, plotH - 1);
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(box);
    return () => ro.disconnect();
  }, [heat, total, cuts, spikes, range, moments, height]);

  return (
    <div
      ref={wrap}
      className={cn("relative w-full", className)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - r.left;
        const t = (x / r.width) * total;
        const i = Math.min(heat.length - 1, Math.floor((x / r.width) * heat.length));
        setHover({ x, t, v: heat[i] ?? 0 });
      }}
      onMouseLeave={() => setHover(null)}
    >
      <canvas ref={ref} role="img" aria-label={`Source signals: replay heatmap over ${duration(total)}, clip window ${range.map((x) => duration(x)).join("–")}`} />
      {hover && (
        <>
          <span className="pointer-events-none absolute top-0 bottom-3.5 w-px bg-fg/40" style={{ left: hover.x }} />
          <span className="num pointer-events-none absolute -top-6 z-10 -translate-x-1/2 rounded-[3px] border border-line bg-panel px-1 text-[11px] whitespace-nowrap shadow" style={{ left: hover.x }}>
            {duration(hover.t)} · replays {Math.round(hover.v * 100)}%
          </span>
        </>
      )}
    </div>
  );
}
