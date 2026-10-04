import * as MB from "@radix-ui/react-menubar";
import { cn } from "@/lib/cn";
import { menuItem, menuSurface } from "@/components/ui/menu";
import type { Command } from "./commands";

const MENUS: { label: string; groups: Command["group"][] }[] = [
  { label: "File", groups: ["File"] },
  { label: "Edit", groups: ["Edit"] },
  { label: "View", groups: ["View", "Go"] },
  { label: "Agents", groups: ["Agents"] },
  { label: "Campaigns", groups: ["Campaigns", "Switches"] },
  { label: "Tools", groups: ["Tools"] },
  { label: "Help", groups: ["Help"] },
];

/**
 * In-window menu bar. The desktop app uses the native Windows menu (src-tauri/src/menu.rs) with
 * the same command ids; this one renders in the browser build, fixtures and screenshots.
 */
export function MenuBar({ commands }: { commands: Command[] }) {
  return (
    <MB.Root className="flex h-7 shrink-0 items-center gap-0.5 bg-chrome px-1.5" aria-label="Menu">
      {MENUS.map((m) => {
        const items = commands.filter((c) => m.groups.includes(c.group));
        return (
          <MB.Menu key={m.label}>
            <MB.Trigger className="h-6 rounded-[var(--radius)] px-2.5 outline-none data-[highlighted]:bg-panel-2 data-[state=open]:bg-panel-2 hover:bg-panel-2">
              {m.label}
            </MB.Trigger>
            <MB.Portal>
              <MB.Content className={cn(menuSurface, "min-w-[240px]")} align="start" sideOffset={2}>
                {items.map((c, i) => {
                  const prev = items[i - 1];
                  const sep = prev && prev.group !== c.group;
                  const body =
                    c.checked !== undefined ? (
                      <MB.CheckboxItem className={menuItem} checked={c.checked} disabled={c.disabled} onSelect={c.run}>
                        <MB.ItemIndicator className="absolute left-2">✓</MB.ItemIndicator>
                        <span className="flex-1">{c.label}</span>
                        {c.shortcut && <span className="num text-[11px] text-muted">{c.shortcut}</span>}
                      </MB.CheckboxItem>
                    ) : (
                      <MB.Item className={menuItem} disabled={c.disabled} onSelect={c.run}>
                        <span className="flex-1">{c.label}</span>
                        {c.shortcut && <span className="num text-[11px] text-muted">{c.shortcut}</span>}
                      </MB.Item>
                    );
                  return (
                    <div key={c.id}>
                      {sep && <MB.Separator className="my-1 h-px bg-line" />}
                      {body}
                    </div>
                  );
                })}
              </MB.Content>
            </MB.Portal>
          </MB.Menu>
        );
      })}
    </MB.Root>
  );
}
