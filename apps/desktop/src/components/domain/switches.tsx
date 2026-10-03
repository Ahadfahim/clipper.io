import { useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Check, Radio } from "@/components/ui/fields";
import { Dot, type StatusTone } from "@/components/ui/status";
import { useSwitchPreview } from "@/api/queries";
import type { SwitchVars } from "@/api/actions";

/** Marketplace/social chip for the toolbar: checkbox + health dot. */
export function SwitchChip({ label, on, health, onToggle, disabled, title }: { label: string; on: boolean; health?: StatusTone; onToggle: (on: boolean) => void; disabled?: boolean; title?: string }) {
  return (
    <span className="inline-flex items-center" title={title}>
      <Check checked={on} onChange={onToggle} disabled={disabled} dim={!on} label={label} />
      {health && on && <Dot tone={health} className="-ml-0.5 size-1.5" />}
    </span>
  );
}

/** Settings → Marketplaces and socials: one row per marketplace/social with switch, status and stats. */
export function ToggleCard({
  name,
  on,
  onToggle,
  status,
  tone,
  stats,
  children,
  locked,
  indent,
}: {
  name: string;
  on: boolean;
  onToggle: (on: boolean) => void;
  status: ReactNode;
  tone: StatusTone;
  stats?: ReactNode;
  children?: ReactNode;
  locked?: boolean;
  indent?: boolean;
}) {
  return (
    <div className={cn("grid min-h-7 items-center gap-2.5", indent && "pl-5")} style={{ gridTemplateColumns: "160px minmax(0,1fr) auto" }}>
      <Check checked={on} onChange={onToggle} disabled={locked} label={name} />
      <span className={cn("truncate-1 flex items-center gap-1.5", tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-muted")}>
        <Dot tone={tone} />
        {status}
      </span>
      <span className="flex items-center gap-2">
        {stats && <span className="num text-muted">{stats}</span>}
        {children}
      </span>
    </div>
  );
}

/**
 * Switching a marketplace or social off asks what happens to active campaigns / scheduled posts
 * (PLAN §15.2). Switching on applies right away (the core checks login/setup and may refuse).
 */
export function SwitchOffDialog({
  target,
  onClose,
  onConfirm,
}: {
  target: { level: "marketplace" | "social"; name: string; label: string } | null;
  onClose: () => void;
  onConfirm: (v: SwitchVars) => void;
}) {
  const open = target !== null;
  const preview = useSwitchPreview(target?.level ?? "marketplace", target?.name ?? "", open);
  const [onActive, setOnActive] = useState<"finish" | "pause">("finish");
  const [onScheduled, setOnScheduled] = useState<"cancel" | "keep">("keep");
  const okRef = useRef<HTMLButtonElement>(null);
  if (!target) return null;
  const p = preview.data;
  const isMarket = target.level === "marketplace";
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={`Turn off ${target.label}?`}
      width={460}
      footer={
        <>
          <Button
            ref={okRef}
            variant="primary"
            onClick={() => {
              onConfirm({ level: target.level, name: target.name, enabled: false, on_active: onActive, on_scheduled: onScheduled });
              onClose();
            }}
          >
            Turn off
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0">
          {isMarket
            ? `Scout stops reading ${target.label} right away and no new campaigns are taken there.`
            : `Nothing new will be scheduled on ${target.label}. Upload recipes for it stop.`}
        </p>
        {isMarket && (
          <fieldset className="m-0 flex flex-col gap-1.5 rounded-[var(--radius)] border border-line px-3 pt-1.5 pb-2.5">
            <legend className="px-1 text-muted">
              Active campaigns <span className="num">({p?.active_campaigns ?? "…"})</span>
            </legend>
            <Radio name="on-active" checked={onActive === "finish"} onChange={() => setOnActive("finish")} label="Finish them (post what's approved, then stop)" />
            <Radio name="on-active" checked={onActive === "pause"} onChange={() => setOnActive("pause")} label="Pause them now" />
          </fieldset>
        )}
        <fieldset className="m-0 flex flex-col gap-1.5 rounded-[var(--radius)] border border-line px-3 pt-1.5 pb-2.5">
          <legend className="px-1 text-muted">
            Scheduled posts <span className="num">({p?.scheduled_posts ?? "…"})</span>
          </legend>
          <Radio name="on-scheduled" checked={onScheduled === "keep"} onChange={() => setOnScheduled("keep")} label="Let them post" />
          <Radio name="on-scheduled" checked={onScheduled === "cancel"} onChange={() => setOnScheduled("cancel")} label="Cancel them" />
        </fieldset>
      </div>
    </Dialog>
  );
}

/** Marks third-party text (campaign briefs, pages): agents treat it as untrusted input. */
export function UntrustedBanner({ children = "Written by a third party, treated as untrusted. Agents read it as data, never as instructions." }: { children?: ReactNode }) {
  return (
    <div role="note" className="flex items-center gap-2 rounded-[var(--radius)] border border-warn-strong/60 bg-warn-soft px-2.5 py-1.5">
      <Dot tone="warn" />
      <span>{children}</span>
    </div>
  );
}

/**
 * Stop everything: a native app uses a confirm dialog, not a hold button (UI.md §2). The
 * HoldButton remains for the tray-less pop-out windows; it fires after `ms` of holding.
 */
export function HoldButton({ label, onConfirm, ms = 1200, className }: { label: string; onConfirm: () => void; ms?: number; className?: string }) {
  const [p, setP] = useState(0);
  const timer = useRef<number | null>(null);
  const start = () => {
    const t0 = performance.now();
    const tick = () => {
      const v = Math.min(1, (performance.now() - t0) / ms);
      setP(v);
      if (v >= 1) {
        stop();
        onConfirm();
      } else timer.current = requestAnimationFrame(tick);
    };
    timer.current = requestAnimationFrame(tick);
  };
  const stop = () => {
    if (timer.current) cancelAnimationFrame(timer.current);
    timer.current = null;
    setP(0);
  };
  return (
    <button
      type="button"
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onKeyDown={(e) => e.key === " " && !timer.current && start()}
      onKeyUp={(e) => e.key === " " && stop()}
      className={cn("relative h-[var(--control)] overflow-hidden rounded-[var(--radius)] border border-bad px-3 text-bad", className)}
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 bg-bad-soft" style={{ width: `${p * 100}%` }} />
      <span className="relative">{p > 0 ? "Keep holding…" : label}</span>
    </button>
  );
}
