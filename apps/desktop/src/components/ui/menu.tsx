import * as CM from "@radix-ui/react-context-menu";
import * as DM from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type MenuItem =
  | { kind?: "item"; label: string; shortcut?: string; onSelect: () => void; disabled?: boolean; danger?: boolean; icon?: ReactNode }
  | { kind: "check"; label: string; checked: boolean; onSelect: () => void; disabled?: boolean; shortcut?: string }
  | { kind: "separator" }
  | { kind: "sub"; label: string; items: MenuItem[] };

export const menuSurface =
  "z-50 min-w-[200px] rounded-[var(--radius)] border border-line bg-panel p-1 shadow-[0_8px_24px_rgba(0,0,0,0.28)] outline-none";
export const menuItem =
  "relative flex h-[28px] cursor-default select-none items-center gap-2 rounded-[3px] pr-3 pl-7 outline-none data-[disabled]:text-faint data-[highlighted]:bg-accent-soft";

function Items({ items, P }: { items: MenuItem[]; P: typeof CM | typeof DM }) {
  return (
    <>
      {items.map((it, i) => {
        if (it.kind === "separator") return <P.Separator key={i} className="my-1 h-px bg-line" />;
        if (it.kind === "sub")
          return (
            <P.Sub key={i}>
              <P.SubTrigger className={menuItem}>
                <span className="flex-1">{it.label}</span>
                <span aria-hidden="true">›</span>
              </P.SubTrigger>
              <P.Portal>
                <P.SubContent className={menuSurface} sideOffset={2}>
                  <Items items={it.items} P={P} />
                </P.SubContent>
              </P.Portal>
            </P.Sub>
          );
        if (it.kind === "check")
          return (
            <P.CheckboxItem key={i} className={menuItem} checked={it.checked} disabled={it.disabled} onSelect={it.onSelect}>
              <P.ItemIndicator className="absolute left-2">✓</P.ItemIndicator>
              <span className="flex-1">{it.label}</span>
              {it.shortcut && <span className="num text-[11px] text-muted">{it.shortcut}</span>}
            </P.CheckboxItem>
          );
        return (
          <P.Item key={i} className={cn(menuItem, it.danger && "text-bad")} disabled={it.disabled} onSelect={it.onSelect}>
            {it.icon && <span className="absolute left-1.5 inline-flex size-4 items-center [&_svg]:size-4">{it.icon}</span>}
            <span className="flex-1">{it.label}</span>
            {it.shortcut && <span className="num text-[11px] text-muted">{it.shortcut}</span>}
          </P.Item>
        );
      })}
    </>
  );
}

/** Right-click menu (UI.md: context menus everywhere). */
export function ContextMenu({ items, children }: { items: MenuItem[]; children: ReactNode }) {
  return (
    <CM.Root>
      <CM.Trigger asChild>{children}</CM.Trigger>
      <CM.Portal>
        <CM.Content className={menuSurface}>
          <Items items={items} P={CM} />
        </CM.Content>
      </CM.Portal>
    </CM.Root>
  );
}

export function DropdownMenu({ items, children, align = "start" }: { items: MenuItem[]; children: ReactNode; align?: "start" | "end" }) {
  return (
    <DM.Root>
      <DM.Trigger asChild>{children}</DM.Trigger>
      <DM.Portal>
        <DM.Content className={menuSurface} align={align} sideOffset={2}>
          <Items items={items} P={DM} />
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}
