import { forwardRef } from "react";
import { Panel, PanelGroup, PanelResizeHandle, type ImperativePanelHandle, type PanelGroupProps, type PanelProps } from "react-resizable-panels";
import { cn } from "@/lib/cn";

/** Resizable panes; sizes persist per `autoSaveId` (UI.md: remembers pane sizes). */
export const Panes = ({ className, ...p }: PanelGroupProps) => <PanelGroup className={cn("min-h-0", className)} {...p} />;
/** A pane; pass a ref to resize it from code (collapse a chat to its input row). */
export const Pane = forwardRef<ImperativePanelHandle, PanelProps>(function Pane({ className, ...p }, ref) {
  return <Panel ref={ref} className={cn("flex min-h-0 min-w-0 flex-col", className)} {...p} />;
});
export function Splitter({ direction = "horizontal" }: { direction?: "horizontal" | "vertical" }) {
  return (
    <PanelResizeHandle
      className={cn(
        "relative shrink-0 bg-line outline-none data-[resize-handle-state=drag]:bg-accent data-[resize-handle-state=hover]:bg-accent",
        direction === "horizontal" ? "w-px" : "h-px",
        "after:absolute after:content-['']",
        direction === "horizontal" ? "after:inset-y-0 after:-left-1 after:w-2" : "after:inset-x-0 after:-top-1 after:h-2",
      )}
    />
  );
}
