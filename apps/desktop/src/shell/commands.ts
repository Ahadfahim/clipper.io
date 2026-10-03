// One command registry feeds the menu bar, the native Tauri menu, the Ctrl+K box and shortcuts
// (UI.md §2, §6), so every action is reachable the same way from everywhere.
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useControl, useSwitch, useTrigger } from "@/api/actions";
import { useBatches, useJobs, useSettings, useStatus, useSwitches } from "@/api/queries";
import { IN_TAURI, openPath, popOut, quitApp } from "@/lib/tauri";
import { MARKET_LABEL, PLATFORM_LABEL } from "@/lib/platforms";
import { useUi } from "@/state/ui";

export type Command = {
  id: string;
  label: string;
  group: "File" | "Edit" | "View" | "Agents" | "Campaigns" | "Tools" | "Help" | "Go" | "Switches";
  shortcut?: string;
  keys?: string; // hotkey combo for useHotkeys
  checked?: boolean;
  disabled?: boolean;
  run: () => void;
};

export const PAGES = [
  { id: "go.overview", label: "Overview", to: "/", keys: "ctrl+1" },
  { id: "go.agents", label: "Agents", to: "/agents", keys: "ctrl+2" },
  { id: "go.campaigns", label: "Campaigns", to: "/campaigns", keys: "ctrl+3" },
  { id: "go.library", label: "Library", to: "/library", keys: "ctrl+4" },
  { id: "go.review", label: "Review", to: "/review", keys: "ctrl+5" },
  { id: "go.publishing", label: "Publishing", to: "/publishing", keys: "ctrl+6" },
  { id: "go.earnings", label: "Earnings", to: "/earnings", keys: "ctrl+7" },
] as const;

export function useCommands(onSwitchOff: (t: { level: "marketplace" | "social"; name: string; label: string }) => void): Command[] {
  const navigate = useNavigate();
  const status = useStatus().data;
  const switches = useSwitches().data;
  const batches = useBatches().data;
  const settings = useSettings().data;
  const jobs = useJobs().data;
  const control = useControl();
  const sw = useSwitch();
  const trigger = useTrigger();
  const ui = useUi();
  const c = status?.control;

  return useMemo(() => {
    const go = (to: string) => () => void navigate({ to });
    const openBatch = batches?.find((b) => b.status === "in_review" || b.pending > 0);
    const cmds: Command[] = [
      ...PAGES.map((p, i) => ({ id: p.id, label: `Go to ${p.label}`, group: "Go" as const, shortcut: `Ctrl+${i + 1}`, keys: p.keys, run: go(p.to) })),
      { id: "go.settings", label: "Settings…", group: "File", shortcut: "Ctrl+,", keys: "ctrl+,", run: () => ui.openSettings() },
      { id: "file.setup", label: "Run setup wizard…", group: "File", run: go("/setup") },
      {
        id: "file.data",
        label: "Open data folder",
        group: "File",
        disabled: !IN_TAURI,
        run: () => {
          const dir = (settings?.settings["paths"] as { data_dir?: string } | undefined)?.data_dir;
          if (dir) void openPath(dir);
        },
      },
      {
        id: "app.quit",
        label: "Exit",
        group: "File",
        disabled: !IN_TAURI,
        run: () => {
          // closing the window only hides it; Exit stops the agents too (warns while uploads run)
          const uploading = (jobs ?? []).some((j) => j.status === "running" && j.kind.includes("upload"));
          const msg = uploading ? "Uploads are in progress. Exit anyway? They will be retried on the next start." : "Exit Clipper? Agents stop until you start it again.";
          if (window.confirm(msg)) void quitApp();
        },
      },
      { id: "file.gallery", label: "Component gallery", group: "Help", run: go("/dev/gallery") },
      {
        id: "agents.pause",
        label: c?.paused ? "Resume all" : "Pause all",
        group: "Agents",
        shortcut: "Ctrl+Shift+P",
        keys: "ctrl+shift+p",
        run: () => control.mutate({ key: "paused", value: !c?.paused }),
      },
      {
        id: "agents.dryrun",
        label: "Dry run",
        group: "Agents",
        shortcut: "Ctrl+Shift+D",
        keys: "ctrl+shift+d",
        checked: Boolean(c?.dry_run),
        run: () => control.mutate({ key: "dry_run", value: !c?.dry_run }),
      },
      { id: "agents.stop", label: "Stop all…", group: "Agents", run: () => ui.setStopOpen(true) },
      ...[2, 3, 4, 5, 6].map((n) => ({
        id: `agents.slots.${n}`,
        label: `Slot count: ${n}`,
        group: "Agents" as const,
        checked: (c?.slots ?? 4) === n,
        run: () => control.mutate({ key: "slots", value: n }),
      })),
      { id: "agents.director", label: "Message the Director…", group: "Agents", shortcut: "Ctrl+K >", run: () => ui.openCommand(">") },
      { id: "campaigns.scout", label: "Scout now", group: "Campaigns", run: () => trigger.mutate("scout") },
      { id: "tools.analyst", label: "Run analyst now", group: "Tools", run: () => trigger.mutate("analyst") },
      { id: "campaigns.paste", label: "Paste campaign URL…", group: "Campaigns", run: () => void navigate({ to: "/campaigns", search: { paste: 1 } }) },
      {
        id: "review.open",
        label: openBatch ? `Review queue (${openBatch.pending})` : "Review queue",
        group: "Campaigns",
        run: () => (openBatch ? void navigate({ to: "/review/$batchId", params: { batchId: String(openBatch.id) } }) : void navigate({ to: "/review" })),
      },
      { id: "review.popout", label: "Pop out Review window", group: "View", disabled: !openBatch, run: () => openBatch && void popOut("review", openBatch.id) },
      { id: "view.output", label: "Output panel", group: "View", shortcut: "Ctrl+J", keys: "ctrl+j", checked: ui.outputOpen, run: () => ui.toggleOutput() },
      { id: "view.activity", label: "Activity", group: "View", shortcut: "Ctrl+.", keys: "ctrl+.", run: () => ui.setOutputTab("activity") },
      { id: "view.theme.system", label: "Theme: follow Windows", group: "View", checked: ui.theme === "system", run: () => ui.setTheme("system") },
      { id: "view.theme.light", label: "Theme: light", group: "View", checked: ui.theme === "light", run: () => ui.setTheme("light") },
      { id: "view.theme.dark", label: "Theme: dark", group: "View", checked: ui.theme === "dark", run: () => ui.setTheme("dark") },
      { id: "view.density", label: "Comfortable density", group: "View", checked: ui.density === "comfortable", run: () => ui.setDensity(ui.density === "compact" ? "comfortable" : "compact") },
      { id: "tools.doctor", label: "Clipper doctor", group: "Tools", run: () => ui.openSettings("health") },
      { id: "tools.memory", label: "Memory…", group: "Tools", run: () => ui.openSettings("tools") },
      { id: "help.keys", label: "Keyboard shortcuts", group: "Help", shortcut: "F1", keys: "f1", run: () => ui.openSettings("keys") },
      { id: "edit.find", label: "Find…", group: "Edit", shortcut: "Ctrl+K", keys: "ctrl+k", run: () => ui.openCommand("") },
    ];
    // "turn off whop" / "turn on tiktok" (UI.md §6)
    for (const [name, m] of Object.entries(switches?.marketplaces ?? {})) {
      const label = MARKET_LABEL[name] ?? m.name;
      cmds.push({
        id: `switch.market.${name}`,
        label: `Turn ${m.enabled ? "off" : "on"} ${label}`,
        group: "Switches",
        run: () => (m.enabled ? onSwitchOff({ level: "marketplace", name, label }) : sw.mutate({ level: "marketplace", name, enabled: true })),
      });
    }
    for (const [name, s] of Object.entries(switches?.socials ?? {})) {
      const label = PLATFORM_LABEL[name] ?? s.name;
      cmds.push({
        id: `switch.social.${name}`,
        label: `Turn ${s.enabled ? "off" : "on"} ${label}`,
        group: "Switches",
        run: () => (s.enabled ? onSwitchOff({ level: "social", name, label }) : sw.mutate({ level: "social", name, enabled: true })),
      });
    }
    return cmds;
  }, [navigate, batches, c, control, sw, trigger, ui, switches, onSwitchOff, settings, jobs]);
}
