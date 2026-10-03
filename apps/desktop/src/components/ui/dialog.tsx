import * as D from "@radix-ui/react-dialog";
import { Dismiss16Regular } from "@fluentui/react-icons";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Windows-style modal dialog: title row, body, right-aligned button row (OK / Cancel / Apply). */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = 520,
  className,
  bodyClassName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <D.Content
          style={{ width: `min(${width}px, calc(100vw - 32px))` }}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] -translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-[var(--radius)] border border-line bg-chrome shadow-[0_16px_48px_rgba(0,0,0,0.35)] outline-none",
            className,
          )}
        >
          <div className="flex h-8 shrink-0 items-center pl-3">
            <D.Title className="text-[12px] font-normal">{title}</D.Title>
            <span className="flex-1" />
            <D.Close aria-label="Close" className="flex h-8 w-[46px] items-center justify-center hover:bg-bad hover:text-white">
              <Dismiss16Regular />
            </D.Close>
          </div>
          {description ? (
            <D.Description className="px-4 pb-2 text-muted">{description}</D.Description>
          ) : (
            <D.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</D.Description>
          )}
          <div className={cn("min-h-0 flex-1 overflow-auto px-4 pb-3", bodyClassName)}>{children}</div>
          {footer && <div className="flex shrink-0 justify-end gap-2 border-t border-line bg-bg px-4 py-3">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
