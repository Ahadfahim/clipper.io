import { ArrowUpload16Regular, Checkmark16Regular, Dismiss16Regular, Edit16Regular, Cut16Regular, WindowNew16Regular } from "@fluentui/react-icons";
import { Navigate, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApproveAll, useCaption, useControl, useDecide, useRecut, useRejectRest, useShip } from "@/api/actions";
import { useAutoApprove, useBatch, useBatches, useManifest, useSwitches } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { useLive } from "@/api/live";
import { Button } from "@/components/ui/button";
import { Check, Field, Radio, TextArea } from "@/components/ui/fields";
import { DropdownMenu } from "@/components/ui/menu";
import { Empty, Kbd, PaneHeader, PropertyGrid, Toolbar, ToolbarSep } from "@/components/ui/misc";
import { Dot } from "@/components/ui/status";
import { ClipPlayer, type PlayerHandle } from "@/components/domain/clip";
import { Score } from "@/components/domain/badges";
import { cn } from "@/lib/cn";
import { duration, relative } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { PLATFORM_LABEL, PLATFORM_ORDER, REJECT_REASONS } from "@/lib/platforms";
import { popOut } from "@/lib/tauri";
import { useUi } from "@/state/ui";

type RC = Schemas["ReviewClip"];

const DECISION_MARK: Record<string, { mark: string; cls: string; label: string }> = {
  approved: { mark: "✓", cls: "text-ok", label: "Approved" },
  rejected: { mark: "✗", cls: "text-bad", label: "Rejected" },
  pending: { mark: "●", cls: "text-muted", label: "Pending" },
};

/** /review → the batch that needs you, or the list. */
export function ReviewIndex() {
  const batches = useBatches();
  const navigate = useNavigate();
  if (batches.isLoading) return <Empty>Loading…</Empty>;
  const open = batches.data?.find((b) => b.pending > 0) ?? batches.data?.find((b) => b.status !== "shipped");
  if (open) return <Navigate to="/review/$batchId" params={{ batchId: String(open.id) }} replace />;
  return (
    <div className="p-4">
      <h1 className="mb-2 text-[16px] font-semibold">Review</h1>
      <p className="text-muted">Nothing to review. Batches appear here (and in Discord) when clips are ready.</p>
      <ul>
        {(batches.data ?? []).map((b) => (
          <li key={b.id}>
            <button type="button" className="text-accent hover:underline" onClick={() => void navigate({ to: "/review/$batchId", params: { batchId: String(b.id) } })}>
              Batch {b.id} · {b.campaign_title} · {b.status}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Queue({ clips, current, onPick, liveEditing }: { clips: RC[]; current?: number; onPick: (id: number) => void; liveEditing: Set<number> }) {
  const cols = "30px 46px 46px minmax(0,1fr) 112px";
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [current]);
  return (
    <div ref={ref} role="listbox" aria-label="Clips in this batch" className="min-h-0 flex-1 overflow-auto bg-panel">
      <div className="sticky top-0 z-10 grid h-[26px] items-center border-b border-line bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
        <span className="px-2">#</span>
        <span className="px-2">Score</span>
        <span className="px-2">Len</span>
        <span className="px-2">Hook</span>
        <span className="px-2">Status</span>
      </div>
      {clips.map((c, i) => {
        const d = DECISION_MARK[c.decision] ?? DECISION_MARK["pending"]!;
        const sel = c.clip.id === current;
        const editing = c.clip.editing_live || liveEditing.has(c.clip.id);
        return (
          <button
            key={c.clip.id}
            type="button"
            role="option"
            aria-selected={sel}
            onClick={() => onPick(c.clip.id)}
            className={cn(
              "grid h-7 w-full items-center border-b border-line-soft text-left",
              sel ? "bg-accent-soft outline-1 -outline-offset-1 outline-accent" : "hover:bg-[color-mix(in_srgb,var(--fg)_4%,transparent)]",
            )}
            style={{ gridTemplateColumns: cols }}
          >
            <span className="num px-2 text-muted">{i + 1}</span>
            <span className="px-2">
              <Score value={c.clip.score} />
            </span>
            <span className="num px-2">{duration(c.clip.duration)}</span>
            <span className="truncate-1 px-2">
              {editing && <span className="mr-1 text-agent" title="An agent is editing this clip right now">✦</span>}
              {c.clip.hook}
            </span>
            <span className={cn("truncate-1 px-2", d.cls)} title={c.via === "discord" ? "Decided in Discord" : undefined}>
              {d.mark} {c.clip.status === "recut" ? "Re-rendering" : d.label}
              {c.via === "discord" && c.decision !== "pending" && <span className="text-muted"> · Discord</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function CaptionField({ batchId, clip, platform }: { batchId: number; clip: RC; platform: "youtube" | "tiktok" | "instagram" | "x" }) {
  const save = useCaption();
  const saved = clip.captions[platform] ?? "";
  const [v, setV] = useState(saved);
  useEffect(() => {
    setV(saved);
  }, [saved, clip.clip.id]);
  const label = platform === "youtube" ? "YouTube title" : `${PLATFORM_LABEL[platform]} caption`;
  return (
    <Field label={label}>
      {(id) => (
        <TextArea
          id={id}
          rows={2}
          value={v}
          onChange={(e) => setV(e.target.value)}
          onBlur={() => v !== saved && save.mutate({ batchId, clipId: clip.clip.id, platform, text: v })}
          className="text-[12px]"
        />
      )}
    </Field>
  );
}

function Properties({ batchId, clip, enabled }: { batchId: number; clip: RC; enabled: Set<string> }) {
  const decide = useDecide();
  const allowed = PLATFORM_ORDER.filter((p) => clip.platforms_allowed.includes(p) && enabled.has(p));
  const togglePlatform = (p: string, on: boolean) => {
    const next = on ? [...new Set([...clip.platforms, p])] : clip.platforms.filter((x) => x !== p);
    decide.mutate({ batchId, clipId: clip.clip.id, decision: clip.decision as "approved" | "rejected" | "pending", platforms: next, reason: clip.decision_reason });
  };
  return (
    <aside aria-label="Properties" className="flex min-h-0 flex-1 flex-col bg-panel">
      <PaneHeader>Properties</PaneHeader>
      <div className="min-h-0 flex-1 overflow-auto">
        <PropertyGrid
          rows={[
            ["Score", <Score key="s" value={clip.clip.score} />],
            ["Length", <span key="l" className="num">{duration(clip.clip.duration)}</span>],
            ["Source range", <span key="r" className="num">{`${duration(clip.source_range[0])}–${duration(clip.source_range[1])}`}</span>],
            ["Layout", clip.clip.layout],
            ["Captions", clip.clip.caption_style],
            ["Hook", clip.clip.hook],
            ["Why", clip.reason || "—"],
            ["QA", clip.qa_ok === null ? "not run" : clip.qa_ok ? <span key="q" className="text-ok">passed</span> : <span key="q" className="text-bad">failed: open Edit to see why</span>],
            ...(clip.decision !== "pending"
              ? ([["Decision", `${clip.decision}${clip.decision_reason ? ` · ${clip.decision_reason.replace(/_/g, " ")}` : ""}${clip.via ? ` · via ${clip.via === "dashboard" ? "app" : clip.via}` : ""}`]] as [string, string][])
              : []),
          ]}
        />
        <fieldset className="m-0 flex flex-wrap gap-3.5 border-0 border-t border-line px-2.5 pt-2 pb-2.5">
          <legend className="pt-2 pb-1 text-muted">Post to</legend>
          {allowed.length === 0 && <span className="text-muted">No enabled socials allowed by this campaign.</span>}
          {allowed.map((p) => (
            <Check key={p} checked={clip.platforms.includes(p)} onChange={(on) => togglePlatform(p, on)} label={PLATFORM_LABEL[p]} />
          ))}
        </fieldset>
        <div className="flex flex-col gap-2 border-t border-line px-2.5 pt-1.5 pb-3">
          {allowed.map((p) => (
            <CaptionField key={p} batchId={batchId} clip={clip} platform={p} />
          ))}
        </div>
      </div>
    </aside>
  );
}

function RecutPanel({ batchId, clip, trim, onDone }: { batchId: number; clip: RC; trim: { start: number; end: number }; onDone: () => void }) {
  const recut = useRecut();
  const [layout, setLayout] = useState<"crop" | "split" | "fit" | null>(null);
  const [note, setNote] = useState("");
  return (
    <div className="flex w-full max-w-[360px] flex-col gap-2 rounded-[var(--radius)] border border-accent/60 bg-panel p-2.5">
      <div className="font-semibold">Re-cut</div>
      <div className="flex flex-wrap gap-3">
        <span className="text-muted">Layout</span>
        <Radio name="recut-layout" checked={layout === null} onChange={() => setLayout(null)} label="Keep" />
        {(["crop", "split", "fit"] as const).map((l) => (
          <Radio key={l} name="recut-layout" checked={layout === l} onChange={() => setLayout(l)} label={l[0]!.toUpperCase() + l.slice(1)} />
        ))}
      </div>
      <label htmlFor="recut-note" className="sr-only">
        Note for the agent
      </label>
      <TextArea id="recut-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note for the agent (optional)" />
      <div className="flex gap-2">
        <Button
          variant="primary"
          onClick={() => {
            recut.mutate({ batchId, clipId: clip.clip.id, start_delta: trim.start, end_delta: trim.end, layout, note: note || null });
            onDone();
          }}
        >
          Send re-cut
        </Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );
}

function AutoApproveOffer({ offer }: { offer: Schemas["AutoApproveOffer"] }) {
  const control = useControl();
  const [dismissed, setDismissed] = useState(false);
  const best = offer.offers[0] as { tier?: number; approval_rate?: number; decisions?: number } | undefined;
  if (dismissed || !offer.eligible || !best?.tier || offer.current_tier) return null;
  return (
    <div role="note" className="flex flex-wrap items-center gap-2 border-b border-line bg-accent-row px-3 py-1.5">
      <Dot tone="accent" />
      <span className="flex-1">
        You approved {Math.round((best.approval_rate ?? 0) * 100)}% of the last {best.decisions ?? 0} clips scored {best.tier}+. Auto-approve clips scored{" "}
        {best.tier}+? Every posting rule still applies, and you can turn it off in Settings.
      </span>
      <Button size="sm" variant="primary" onClick={() => control.mutate({ key: "auto_approve_tier", value: best.tier })}>
        Turn on for {best.tier}+
      </Button>
      <Button size="sm" onClick={() => setDismissed(true)}>
        Not now
      </Button>
    </div>
  );
}

/**
 * Review: queue · 9:16 player · properties with per-platform captions. A approves and moves on,
 * R rejects with a reason, E edits, C re-cuts, Space plays, ←/→ (or ↑/↓) move (UI.md §3.5).
 * Decisions sync with Discord both ways. `popout` = portrait layout for the 1080×1920 monitor.
 */
export function ReviewScreen({ popout = false }: { popout?: boolean }) {
  const params = useParams({ strict: false }) as { batchId?: string };
  const batchId = Number(params.batchId);
  const data = useBatch(batchId).data;
  const manifest = useManifest().data;
  const switches = useSwitches().data;
  const offer = useAutoApprove().data;
  const editStatus = useLive((s) => s.editStatus);
  const navigate = useNavigate();
  const decide = useDecide();
  const approveAll = useApproveAll();
  const rejectRest = useRejectRest();
  const ship = useShip();
  const sel = useUi((s) => s.reviewClip[batchId]);
  const setSel = useUi((s) => s.setReviewClip);
  const player = useRef<PlayerHandle>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [recut, setRecut] = useState<{ start: number; end: number } | null>(null);

  const clips = useMemo(() => [...(data?.clips ?? [])].sort((a, b) => b.clip.score - a.clip.score), [data]);
  const current = clips.find((c) => c.clip.id === sel) ?? clips.find((c) => c.decision === "pending") ?? clips[0];
  const idx = current ? clips.indexOf(current) : -1;
  const enabled = new Set(Object.entries(switches?.socials ?? {}).filter(([, s]) => s.enabled).map(([k]) => k));
  const liveEditing = new Set(Object.entries(editStatus).filter(([, v]) => v).map(([k]) => Number(k)));

  const pick = (id: number | undefined) => {
    if (id === undefined) return;
    setSel(batchId, id);
    setRecut(null);
    setRejectOpen(false);
  };
  const nextOpen = (from: number, skip: number) => {
    for (let i = 1; i <= clips.length; i++) {
      const c = clips[(from + i) % clips.length]!;
      if (c.decision === "pending" && c.clip.id !== skip) return c.clip.id;
    }
    return clips[Math.min(clips.length - 1, from + 1)]?.clip.id;
  };
  const doDecide = (decision: "approved" | "rejected", reason?: string) => {
    if (!current) return;
    decide.mutate({ batchId, clipId: current.clip.id, decision, reason: reason ?? null, platforms: current.platforms });
    setRejectOpen(false);
    pick(nextOpen(idx, current.clip.id));
  };
  const threshold = data?.approve_all_threshold ?? 80;
  const approved = clips.filter((c) => c.decision === "approved").length;
  const rejected = clips.filter((c) => c.decision === "rejected").length;
  const shipped = data?.batch.status === "shipped";

  useHotkeys(
    {
      a: () => doDecide("approved"),
      r: () => setRejectOpen((o) => !o),
      e: () => current && void navigate({ to: "/edit/$clipId", params: { clipId: String(current.clip.id) } }),
      c: () => setRecut((r) => (r ? null : { start: 0, end: 0 })),
      space: () => player.current?.toggle(),
      arrowright: () => pick(clips[Math.min(clips.length - 1, idx + 1)]?.clip.id),
      arrowdown: () => pick(clips[Math.min(clips.length - 1, idx + 1)]?.clip.id),
      arrowleft: () => pick(clips[Math.max(0, idx - 1)]?.clip.id),
      arrowup: () => pick(clips[Math.max(0, idx - 1)]?.clip.id),
      "shift+a": () => approveAll.mutate({ batchId, threshold }),
      escape: () => {
        setRejectOpen(false);
        setRecut(null);
      },
      ...(rejectOpen ? Object.fromEntries(REJECT_REASONS.map((r, i) => [String(i + 1), () => doDecide("rejected", r.value)])) : {}),
    },
    Boolean(data) && !shipped,
  );

  if (!data) return <Empty>Loading batch…</Empty>;
  if (!current) return <Empty>This batch is empty.</Empty>;

  const b = data.batch;
  const playerEl = (
    <div className={cn("flex flex-col items-center gap-2.5 bg-bg p-4", popout ? "" : "min-w-0 flex-[1_1_340px]")}>
      <ClipPlayer
        ref={player}
        key={current.clip.id}
        label={`Clip ${current.clip.id}: ${current.clip.hook}`}
        src={current.clip.status === "recut" ? undefined : fileUrl(current.clip.preview_url, manifest)}
        poster={fileUrl(current.clip.thumb_url, manifest)}
        width={popout ? 520 : 252}
        trim={recut ? { ...recut, extra: 5, onChange: (start, end) => setRecut({ start, end }) } : null}
        overlay={
          current.clip.status === "recut" ? (
            <span className="absolute inset-0 flex items-center justify-center bg-black/60 text-white">Re-rendering…</span>
          ) : undefined
        }
      />
      {recut && <RecutPanel batchId={batchId} clip={current} trim={recut} onDone={() => setRecut(null)} />}
      {rejectOpen && (
        <div role="menu" aria-label="Reject reason" className="flex w-full max-w-[360px] flex-col rounded-[var(--radius)] border border-line bg-panel p-1">
          <div className="px-2 py-1 text-muted">Reject because…</div>
          {REJECT_REASONS.map((r, i) => (
            <button key={r.value} role="menuitem" type="button" onClick={() => doDecide("rejected", r.value)} className="flex h-7 items-center gap-2 rounded-[3px] px-2 text-left hover:bg-accent-soft">
              <Kbd>{i + 1}</Kbd>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", popout && "h-full bg-bg")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line bg-chrome px-3 py-1.5">
        <span className="font-semibold">{b.campaign_title}</span>
        <span className="text-muted">· {b.source_title ?? `Batch ${b.id}`}</span>
        <span className="num text-muted">
          · {approved + rejected}/{clips.length} reviewed · <span className="text-ok">✓{approved}</span> <span className="text-bad">✗{rejected}</span>
        </span>
        {shipped && <span className="text-ok">· shipped</span>}
        <span className="flex-1" />
        {!popout && (
          <Button size="sm" variant="ghost" icon={<WindowNew16Regular />} onClick={() => void popOut("review", batchId)} title="Open in its own window (portrait layout)">
            Pop out
          </Button>
        )}
      </div>
      {offer && <AutoApproveOffer offer={offer} />}
      <Toolbar label="Review actions">
        <Button variant="primary" icon={<Checkmark16Regular />} shortcut="A" disabled={shipped} onClick={() => doDecide("approved")}>
          Approve
        </Button>
        <DropdownMenu
          items={REJECT_REASONS.map((r) => ({ label: r.label, onSelect: () => doDecide("rejected", r.value) }))}
        >
          <Button icon={<Dismiss16Regular />} shortcut="R" disabled={shipped}>
            Reject ▾
          </Button>
        </DropdownMenu>
        <Button icon={<Edit16Regular />} shortcut="E" onClick={() => void navigate({ to: "/edit/$clipId", params: { clipId: String(current.clip.id) } })}>
          Edit
        </Button>
        <Button icon={<Cut16Regular />} shortcut="C" disabled={shipped} onClick={() => setRecut((r) => (r ? null : { start: 0, end: 0 }))}>
          Re-cut
        </Button>
        <ToolbarSep />
        <Button variant="ghost" shortcut="Shift+A" disabled={shipped} onClick={() => approveAll.mutate({ batchId, threshold })}>
          Approve all {threshold}+
        </Button>
        <Button variant="ghost" disabled={shipped || !clips.some((c) => c.decision === "pending")} onClick={() => rejectRest.mutate({ batchId, reason: "other" })}>
          Reject rest
        </Button>
        <Button variant="ghost" icon={<ArrowUpload16Regular />} disabled={shipped || approved === 0} onClick={() => ship.mutate(batchId)}>
          Ship approved ({approved})
        </Button>
      </Toolbar>
      {popout ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-auto">
          {playerEl}
          <div className="grid min-h-[480px] flex-1 grid-cols-2 border-t border-line">
            <div className="flex min-h-0 flex-col border-r border-line">
              <Queue clips={clips} current={current.clip.id} onPick={pick} liveEditing={liveEditing} />
            </div>
            <Properties batchId={batchId} clip={current} enabled={enabled} />
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-[300px] flex-[1_1_420px] flex-col border-r border-line">
            <Queue clips={clips} current={current.clip.id} onPick={pick} liveEditing={liveEditing} />
          </div>
          <div className="flex min-h-0 flex-[1_1_340px] flex-col overflow-auto">{playerEl}</div>
          <div className="flex min-h-0 min-w-[280px] flex-[1_1_320px] flex-col border-l border-line">
            <Properties batchId={batchId} clip={current} enabled={enabled} />
          </div>
        </div>
      )}
      <footer className="flex h-6 shrink-0 items-center overflow-hidden border-t border-line bg-chrome text-[11px] whitespace-nowrap text-muted">
        <span className="border-r border-line px-2.5">A approve · R reject · E edit · C re-cut · Space play · ←/→ previous/next · Shift+A approve all {threshold}+</span>
        <span className="border-r border-line px-2.5">Decisions sync with Discord</span>
        {b.timeout_at && <span className="px-2.5">Batch times out {relative(b.timeout_at)}</span>}
      </footer>
    </div>
  );
}
