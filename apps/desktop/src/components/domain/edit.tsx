import { ArrowUndo16Regular, Sparkle16Regular, Person16Regular } from "@fluentui/react-icons";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { clock, timecode } from "@/lib/format";
import {
  cameraAt,
  cameraSpans,
  captionAt,
  captionSpans,
  outputDuration,
  outputSegments,
  outToSrc,
  srcRangeToOut,
  srcToOut,
  type Edl,
  type EdlCameraKey,
  type IndexedWord,
} from "@/lib/edl";
import { Button } from "@/components/ui/button";
import { Select, TextArea } from "@/components/ui/fields";
import { PaneHeader } from "@/components/ui/misc";
import type { Schemas } from "@/api/client";

/* ------------------------------------------------------------------ preview */

export type PreviewHandle = { toggle: () => void; seek: (outT: number) => void; playing: boolean };

/** Draws one camera layout of the source frame into the 9:16 canvas (same math as the renderer). */
function drawFrame(ctx: CanvasRenderingContext2D, src: CanvasImageSource, sw: number, sh: number, key: EdlCameraKey, W: number, H: number) {
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  const crop = (dx: number, dy: number, dw: number, dh: number, fx: number) => {
    const scale = Math.max(dw / sw, dh / sh) * (key.zoom || 1);
    const cw = dw / scale;
    const ch = dh / scale;
    const cx = Math.max(0, Math.min(sw - cw, fx * sw - cw / 2));
    const cy = Math.max(0, Math.min(sh - ch, (key.focus_y ?? 0.5) * sh - ch / 2));
    ctx.drawImage(src, cx, cy, cw, ch, dx, dy, dw, dh);
  };
  if (key.layout === "split") {
    crop(0, 0, W, H / 2, key.focus_x);
    crop(0, H / 2, W, H / 2, key.focus2_x ?? 1 - key.focus_x);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, H / 2 - 1, W, 2);
  } else if (key.layout === "fit") {
    ctx.globalAlpha = 0.35;
    crop(0, 0, W, H, 0.5);
    ctx.globalAlpha = 1;
    const h = (W * sh) / sw;
    ctx.drawImage(src, 0, 0, sw, sh, 0, (H - h) / 2, W, h);
  } else {
    crop(0, 0, W, H, key.focus_x);
  }
}

const SAFE_BOTTOM: Record<string, number> = { tiktok: 0.3, shorts: 0.22, reels: 0.26, none: 0.12 };

/**
 * Live preview drawn from the EDL over the source proxy: segments, crop/split/fit, captions and
 * the hook overlay, without rendering (UI.md EdlPreview). The playhead runs in OUTPUT time.
 */
export const EdlPreview = forwardRef<
  PreviewHandle,
  { edl: Edl; src?: string; poster?: string; width?: number; onTime?: (outT: number) => void; className?: string; agentRange?: [number, number] | null }
>(function EdlPreview({ edl, src, poster, width = 214, onTime, className }, ref) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const img = useRef<HTMLImageElement | null>(null);
  const [outT, setOutT] = useState(0);
  const outRef = useRef(0);
  const onTimeRef = useRef(onTime);
  onTimeRef.current = onTime;
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const total = outputDuration(edl);
  const height = Math.round((width * 16) / 9);
  const segs = useMemo(() => outputSegments(edl), [edl]);

  useEffect(() => {
    if (!poster) return;
    const im = new Image();
    im.onload = () => {
      img.current = im;
      setReady(true);
    };
    im.src = poster;
  }, [poster]);

  // paint loop: draw the current frame for the current output time
  useEffect(() => {
    let raf = 0;
    const paint = () => {
      const c = canvas.current;
      const ctx = c?.getContext("2d");
      const v = video.current;
      if (c && ctx) {
        let t = outRef.current;
        if (v && v.readyState >= 2) {
          const o = srcToOut(edl, v.currentTime);
          if (o === null) {
            // inside a cut: jump to the next kept segment
            const next = segs.find((s) => s.start > v.currentTime);
            v.currentTime = next ? next.start : (segs[0]?.start ?? 0);
          } else {
            t = o;
            if (o >= total - 0.02 && !v.paused) v.currentTime = segs[0]?.start ?? 0;
          }
        }
        const key = cameraAt(edl, t);
        const source = v && v.readyState >= 2 ? v : img.current;
        if (source && key) {
          const sw = source instanceof HTMLVideoElement ? source.videoWidth : source.naturalWidth;
          const sh = source instanceof HTMLVideoElement ? source.videoHeight : source.naturalHeight;
          if (sw && sh) drawFrame(ctx, source, sw, sh, key, c.width, c.height);
        }
        if (Math.abs(t - outRef.current) > 0.03) {
          outRef.current = t;
          setOutT(t);
          onTimeRef.current?.(t);
        }
      }
      raf = requestAnimationFrame(paint);
    };
    raf = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(raf);
  }, [edl, segs, total, ready]);

  useImperativeHandle(
    ref,
    () => ({
      playing,
      toggle: () => {
        const v = video.current;
        if (!v) return;
        if (v.paused) void v.play().catch(() => undefined);
        else v.pause();
      },
      seek: (t: number) => {
        const clamped = Math.max(0, Math.min(total, t));
        if (video.current) video.current.currentTime = outToSrc(edl, clamped);
        outRef.current = clamped;
        setOutT(clamped);
        onTimeRef.current?.(clamped);
      },
    }),
    [edl, total, playing],
  );

  const cap = edl.captions.enabled ? captionAt(edl, outT) : null;
  const hook = edl.overlays.find((o) => o.type === "hook_text" && outT >= o.t_in && outT < o.t_out);
  const bottom = SAFE_BOTTOM[edl.captions.safe_zone] ?? 0.2;

  return (
    <div className={cn("relative shrink-0 overflow-hidden border border-line bg-black", className)} style={{ width, height }} data-ready={ready || undefined}>
      <canvas ref={canvas} width={width * 2} height={height * 2} className="absolute inset-0 size-full" aria-label="Edit preview" role="img" />
      {src && (
        <video
          ref={video}
          src={src}
          muted
          playsInline
          preload="auto"
          className="hidden"
          onLoadedData={() => setReady(true)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      )}
      {hook && (
        <span className="absolute top-[9%] left-1/2 max-w-[86%] -translate-x-1/2 bg-black px-2 py-0.5 text-center text-[11px] font-semibold text-white">
          {String(hook.props["text"] ?? edl.hook.text ?? "")}
        </span>
      )}
      {cap && (
        <span className="absolute left-1/2 w-[88%] -translate-x-1/2 text-center text-[15px] leading-tight font-bold text-white [text-shadow:0_2px_3px_#000]" style={{ bottom: `${bottom * 100}%` }}>
          {cap.words.map((w, i) => (
            <span key={w.index} className={cn(i === cap.active && "text-[#fce100]", w.emphasis && "text-[#fce100]")}>
              {w.text}{" "}
            </span>
          ))}
        </span>
      )}
    </div>
  );
});

/* ------------------------------------------------------------------ timeline */

const LAYOUT_CLASS: Record<string, string> = {
  crop: "bg-[color-mix(in_srgb,var(--series-1)_28%,transparent)] text-fg",
  split: "bg-[color-mix(in_srgb,var(--ok)_26%,transparent)] text-fg",
  fit: "bg-[color-mix(in_srgb,var(--muted)_26%,transparent)] text-fg",
};

/**
 * Multi-track timeline (video, camera, captions, overlay, audio) in output time. A violet range
 * marks where the agent is working; in manual mode, I/O set a range and words are clickable.
 */
export function Timeline({
  edl,
  t,
  onSeek,
  agentRange,
  agentLabel,
  selection,
  manual,
  onWord,
  className,
}: {
  edl: Edl;
  t: number;
  onSeek: (t: number) => void;
  agentRange?: number[] | null;
  agentLabel?: string | null;
  selection?: [number, number] | null;
  manual?: boolean;
  onWord?: (w: IndexedWord) => void;
  className?: string;
}) {
  const total = Math.max(0.1, outputDuration(edl));
  const segs = outputSegments(edl);
  const cams = cameraSpans(edl);
  const words = captionSpans(edl);
  const pct = (x: number) => `${(x / total) * 100}%`;
  const agent = agentRange && agentRange.length === 2 ? srcRangeToOut(edl, agentRange[0]!, agentRange[1]!) : null;
  const ticks = Array.from({ length: 6 }, (_, i) => (total * i) / 5);
  // speech activity per 0.25s bucket, from the caption words (no waveform is shipped to the UI)
  const buckets = Math.max(20, Math.min(120, Math.round(total * 4)));
  const speech = Array.from({ length: buckets }, (_, i) => {
    const a = (i / buckets) * total;
    const b = ((i + 1) / buckets) * total;
    const on = words.some((w) => w.to > a && w.from < b);
    return on ? 0.45 + 0.5 * Math.abs(Math.sin(i * 1.7)) : 0.08;
  });

  const seekFrom = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSeek(((e.clientX - r.left) / r.width) * total);
  };

  const Track = ({ name, h = 26, children }: { name: string; h?: number; children: ReactNode }) => (
    <div className="grid items-center border-b border-line-soft" style={{ gridTemplateColumns: "80px minmax(0,1fr)", height: h }}>
      <span className="px-2 text-muted">{name}</span>
      <div className="relative mr-2 h-[70%]" onClick={seekFrom}>
        {children}
      </div>
    </div>
  );

  return (
    <section aria-label="Timeline" className={cn("border-t border-line bg-chrome", className)}>
      <div className="num grid h-[22px] items-center border-b border-line text-[11px] text-muted" style={{ gridTemplateColumns: "80px minmax(0,1fr)" }}>
        <span className="px-2 text-fg">{timecode(t)}</span>
        <div className="relative mr-2 h-full cursor-pointer" onClick={seekFrom}>
          {ticks.map((x, i) => (
            <span key={i} className="absolute top-1" style={{ left: pct(x), transform: i === 0 ? "none" : i === ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>
              {timecode(x).replace(/\.\d$/, "")}
            </span>
          ))}
        </div>
      </div>
      <div className="relative">
        <Track name="Video" h={30}>
          {segs.map((s, i) => (
            <span key={i} title={`${timecode(s.outStart)}–${timecode(s.outEnd)} (source ${timecode(s.start)}–${timecode(s.end)})`} className="absolute inset-y-0 border-r-2 border-chrome bg-[color-mix(in_srgb,var(--muted)_45%,transparent)]" style={{ left: pct(s.outStart), width: pct(s.outEnd - s.outStart) }} />
          ))}
        </Track>
        <Track name="Camera">
          {cams.map((c, i) => (
            <span key={i} className={cn("truncate-1 absolute inset-y-0 border-r-2 border-chrome pl-1 text-[11px] leading-[18px]", LAYOUT_CLASS[c.data.layout] ?? LAYOUT_CLASS["crop"])} style={{ left: pct(c.from), width: pct(c.to - c.from) }}>
              {c.data.layout}
            </span>
          ))}
        </Track>
        <Track name="Captions">
          {words.map((w) => (
            <button
              key={w.data.index}
              type="button"
              title={`${w.data.text}${manual ? " · click to edit" : ""}`}
              disabled={!manual}
              onClick={(e) => {
                e.stopPropagation();
                onWord?.(w.data);
              }}
              className={cn("absolute inset-y-[3px] border-r border-chrome disabled:cursor-default", w.data.emphasis ? "bg-emph" : "bg-[color-mix(in_srgb,var(--muted)_55%,transparent)]", manual && "hover:outline-1 hover:outline-accent")}
              style={{ left: pct(w.from), width: pct(Math.max(0.05, w.to - w.from)) }}
            />
          ))}
        </Track>
        <Track name="Overlay">
          {edl.overlays.map((o) => (
            <span key={o.id} className="truncate-1 absolute inset-y-0 bg-[color-mix(in_srgb,var(--warn-strong)_22%,transparent)] pl-1 text-[11px] leading-[18px]" style={{ left: pct(o.t_in), width: pct(Math.min(total, o.t_out) - o.t_in) }}>
              {o.type === "hook_text" ? "hook" : o.type.replace("_", " ")}
            </span>
          ))}
        </Track>
        <Track name="Audio" h={34}>
          <span className="absolute inset-0 flex items-center gap-px">
            {speech.map((h, i) => (
              <span key={i} className="flex-1 bg-[color-mix(in_srgb,var(--ok)_60%,transparent)]" style={{ height: `${h * 100}%` }} />
            ))}
          </span>
        </Track>
        {/* overlays spanning the tracks */}
        <div className="pointer-events-none absolute inset-y-0 right-2 left-[80px]">
          {selection && <span className="absolute inset-y-0 border-x border-accent bg-accent-soft" style={{ left: pct(selection[0]), width: pct(selection[1] - selection[0]) }} />}
          {agent && (
            <span aria-label={agentLabel ?? "Claude is editing here"} className="absolute inset-y-0 border border-agent bg-agent-soft" style={{ left: pct(agent[0]), width: pct(agent[1] - agent[0]) }} />
          )}
          <span className="absolute -top-[22px] bottom-0 w-px bg-bad" style={{ left: pct(Math.min(t, total)) }} />
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ history + agenda */

export function actorIsAgent(actor: string): boolean {
  return actor.startsWith("session") || actor === "agent" || actor === "system";
}

/** Every edit step (✦ Claude, ● you); hover for the reason, click ↺ to undo. */
export function EditHistory({
  history,
  liveText,
  onUndo,
  selected,
  onSelect,
}: {
  history: Schemas["EditOpOut"][];
  liveText?: string | null;
  onUndo: (opId: number) => void;
  selected?: number | null;
  onSelect?: (opId: number) => void;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PaneHeader>History</PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        {history.map((h) => {
          const agent = actorIsAgent(h.actor);
          return (
            <div
              key={h.id}
              role="button"
              tabIndex={0}
              title={h.reason}
              onClick={() => onSelect?.(h.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect?.(h.id)}
              className={cn(
                "group grid grid-cols-[18px_minmax(0,1fr)_22px] items-start gap-1.5 border-b border-line-soft px-2.5 py-1.5",
                selected === h.id && "bg-accent-soft",
                h.undone && "text-faint line-through",
              )}
            >
              <span className={cn("pt-0.5", agent ? "text-agent" : "text-accent")} aria-label={agent ? "Claude" : "You"}>
                {agent ? <Sparkle16Regular /> : <Person16Regular />}
              </span>
              <span className="min-w-0">
                <span className="block">{h.op.replace(/_/g, " ")}</span>
                <span className="block truncate-1 text-muted">{h.reason}</span>
              </span>
              {h.op !== "init" && !h.undone && (
                <button
                  type="button"
                  aria-label={`Undo ${h.op.replace(/_/g, " ")}`}
                  title="Undo this step"
                  onClick={(e) => {
                    e.stopPropagation();
                    onUndo(h.id);
                  }}
                  className="flex size-5 items-center justify-center rounded-[3px] text-muted opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 hover:bg-panel-2 hover:text-fg"
                >
                  <ArrowUndo16Regular />
                </button>
              )}
            </div>
          );
        })}
        {liveText && (
          <div className="grid grid-cols-[18px_minmax(0,1fr)] gap-1.5 border-b border-line-soft bg-agent-soft px-2.5 py-1.5">
            <span className="pt-0.5 text-agent">
              <Sparkle16Regular />
            </span>
            <span>
              <span className="block">{liveText}</span>
              <span className="block text-muted">in progress</span>
            </span>
          </div>
        )}
      </div>
      <div className="px-2.5 py-1.5 text-muted">Ctrl+Z undoes the last step</div>
    </div>
  );
}

const PLAN_MARK: Record<string, string> = { done: "✓", in_progress: "◐", queued: "○", skipped: "✗" };

/** The agent's plan for this clip (ticked off live) and your notes with replies. */
export function AgendaPanel({
  plan,
  notes,
  onSend,
  scopeLabel = "this clip",
  noteRef,
}: {
  plan: Schemas["AgendaItemOut"][];
  notes: Schemas["NoteOut"][];
  onSend: (text: string, scope: "clip" | "campaign" | "creator") => void;
  scopeLabel?: string;
  noteRef?: React.Ref<HTMLTextAreaElement>;
}) {
  const [text, setText] = useState("");
  const [scope, setScope] = useState<"clip" | "campaign" | "creator">("clip");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PaneHeader>Agenda · {scopeLabel}</PaneHeader>
      <ul className="flex flex-col gap-1 px-2.5 py-1.5" aria-label="Plan">
        {plan.length === 0 && <li className="text-muted">No plan yet.</li>}
        {plan.map((p) => (
          <li key={p.id} className={cn("flex items-start gap-2", p.status === "done" || p.status === "skipped" ? "text-muted" : "")}>
            <span aria-hidden="true" className={cn("num w-3 text-center", p.status === "in_progress" && "text-agent", p.status === "skipped" && "text-bad")}>
              {PLAN_MARK[p.status] ?? "○"}
            </span>
            <span className="min-w-0 flex-1">
              {p.text}
              {p.status === "in_progress" && <span className="text-agent"> · working</span>}
              {p.status === "skipped" && p.result && <span className="text-muted"> · {p.result}</span>}
              <span className="sr-only"> ({p.status.replace("_", " ")})</span>
            </span>
          </li>
        ))}
      </ul>
      <PaneHeader className="border-t">Your notes</PaneHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto px-2.5 py-1.5">
        {notes.map((n) => (
          <div key={n.id}>
            <div>
              "{n.text}" <span className="text-muted">· {n.scope === "clip" ? "this clip" : n.scope}</span>
            </div>
            {n.response ? <div className="text-agent">Claude: {n.response}</div> : <div className="text-muted">Sent {clock(n.created_at, false)} · waiting for the agent</div>}
          </div>
        ))}
      </div>
      <form
        className="flex flex-col gap-1.5 border-t border-line px-2.5 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          onSend(text.trim(), scope);
          setText("");
        }}
      >
        <label htmlFor="agenda-note" className="text-muted">
          New note
        </label>
        <TextArea id="agenda-note" ref={noteRef} rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="No zoom on this one" />
        <div className="flex gap-1.5">
          <label htmlFor="agenda-scope" className="sr-only">
            Applies to
          </label>
          <Select id="agenda-scope" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)} className="flex-1">
            <option value="clip">This clip</option>
            <option value="campaign">This campaign</option>
            <option value="creator">Always for this creator</option>
          </Select>
          <Button type="submit" variant="primary" disabled={!text.trim()}>
            Send
          </Button>
        </div>
      </form>
    </div>
  );
}
