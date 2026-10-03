import * as Tip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Gray header bar on top of a pane ("Properties", "History"). */
export function PaneHeader({ children, actions, className }: { children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex h-[26px] shrink-0 items-center gap-2 border-b border-line bg-panel-2 px-2.5 text-muted", className)}>
      <span className="flex-1 truncate-1">{children}</span>
      {actions}
    </div>
  );
}

/** Page or section title row: 16px title, muted subtitle, actions on the right. */
export function TitleRow({ title, sub, actions, className }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-baseline gap-x-2.5 gap-y-1", className)}>
      <h1 className="text-[16px] font-semibold">{title}</h1>
      {sub && <span className="text-muted">{sub}</span>}
      <span className="flex-1" />
      {actions && <div className="flex items-center gap-1 self-center">{actions}</div>}
    </div>
  );
}

export function SectionTitle({ children, count, actions }: { children: ReactNode; count?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-1.5 flex items-center gap-2">
      <h2 className="text-[12px] font-semibold">
        {children} {count !== undefined && <span className="font-normal text-muted">({count})</span>}
      </h2>
      <span className="flex-1" />
      {actions}
    </div>
  );
}

/** Label/value grid instead of decorated detail cards (UI.md §1). */
export function PropertyGrid({ rows, labelWidth = 110, className }: { rows: [ReactNode, ReactNode][]; labelWidth?: number; className?: string }) {
  return (
    <div className={cn("grid gap-y-px bg-line-soft", className)} style={{ gridTemplateColumns: `${labelWidth}px minmax(0,1fr)` }}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <span className="bg-panel px-2.5 py-1.5 text-muted">{k}</span>
          <span className="selectable min-w-0 bg-panel px-2.5 py-1.5 break-words">{v}</span>
        </div>
      ))}
    </div>
  );
}

export function Progress({ value, tone = "accent", className, label }: { value: number; tone?: "accent" | "agent" | "ok" | "warn"; className?: string; label?: string }) {
  const v = Math.max(0, Math.min(1, value));
  const fill = { accent: "bg-accent", agent: "bg-agent", ok: "bg-ok", warn: "bg-warn-strong" }[tone];
  return (
    <span
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v * 100)}
      className={cn("relative inline-block h-1 w-full overflow-hidden bg-line", className)}
    >
      <span className={cn("absolute inset-y-0 left-0", fill)} style={{ width: `${v * 100}%` }} />
    </span>
  );
}

export function Toolbar({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return (
    <div role="toolbar" aria-label={label} className={cn("flex flex-wrap items-center gap-1 border-b border-line bg-chrome px-2 py-1", className)}>
      {children}
    </div>
  );
}

export const ToolbarSep = () => <span aria-hidden="true" className="mx-1 h-5 w-px bg-line" />;

export function Tooltip({ content, children, side = "bottom" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  return (
    <Tip.Root delayDuration={500}>
      <Tip.Trigger asChild>{children}</Tip.Trigger>
      <Tip.Portal>
        <Tip.Content side={side} sideOffset={4} className="z-50 max-w-[320px] rounded-[var(--radius)] border border-line bg-panel px-2 py-1 shadow-md">
          {content}
        </Tip.Content>
      </Tip.Portal>
    </Tip.Root>
  );
}

export function Empty({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("px-3 py-6 text-center text-muted", className)}>{children}</div>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="num rounded-[3px] border border-line bg-panel-2 px-1 text-[11px] text-muted">{children}</kbd>;
}

export function Badge({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[18px] items-center rounded-[3px] border border-line px-1.5 text-[11px] leading-none text-muted", className)}>
      {children}
    </span>
  );
}

/** Vertical scroll region for pane bodies. */
export function Scroll({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("min-h-0 flex-1 overflow-auto", className)}>{children}</div>;
}
