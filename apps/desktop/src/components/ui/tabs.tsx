import * as T from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Underline tabs (output panel, drawers, clip detail). */
export function Tabs({
  value,
  onValueChange,
  tabs,
  className,
  listClassName,
  children,
}: {
  value: string;
  onValueChange: (v: string) => void;
  tabs: { value: string; label: ReactNode }[];
  className?: string;
  listClassName?: string;
  children?: ReactNode;
}) {
  return (
    <T.Root value={value} onValueChange={onValueChange} className={cn("flex min-h-0 flex-col", className)}>
      <T.List className={cn("flex h-[30px] shrink-0 items-end gap-0.5 border-b border-line px-2", listClassName)}>
        {tabs.map((t) => (
          <T.Trigger
            key={t.value}
            value={t.value}
            className="h-7 border-b-2 border-transparent px-3 text-muted data-[state=active]:border-accent data-[state=active]:text-fg hover:text-fg"
          >
            {t.label}
          </T.Trigger>
        ))}
      </T.List>
      {children}
    </T.Root>
  );
}

export const TabPanel = ({ value, children, className }: { value: string; children: ReactNode; className?: string }) => (
  <T.Content value={value} className={cn("min-h-0 flex-1 outline-none", className)}>
    {children}
  </T.Content>
);
