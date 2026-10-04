import { Outlet, useNavigate } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { useSwitch } from "@/api/actions";
import { useLiveEvents } from "@/api/live";
import { useStatus } from "@/api/queries";
import { Pane, Panes, Splitter } from "@/components/ui/splitter";
import { SwitchOffDialog } from "@/components/domain/switches";
import { useHotkeys } from "@/lib/hotkeys";
import { money } from "@/lib/format";
import { IN_TAURI, onNativeMenu, syncTray } from "@/lib/tauri";
import { SettingsDialog } from "@/screens/settings/SettingsDialog";
import { useUi } from "@/state/ui";
import { CommandBox } from "./CommandBox";
import { useCommands } from "./commands";
import { DryRunBar, MainToolbar } from "./MainToolbar";
import { MenuBar } from "./MenuBar";
import { NavTree } from "./NavTree";
import { OutputPanel } from "./OutputPanel";
import { StatusBar } from "./StatusBar";
import { StopAllDialog } from "./StopAllDialog";

export type SwitchTarget = { level: "marketplace" | "social"; name: string; label: string };

/** Menu bar → toolbar → panes (tree | document) → docked output panel → status bar (UI.md §2). */
export function AppShell() {
  useLiveEvents();
  const [switchOff, setSwitchOff] = useState<SwitchTarget | null>(null);
  const onSwitchOff = useCallback((t: SwitchTarget) => setSwitchOff(t), []);
  const commands = useCommands(onSwitchOff);
  const outputOpen = useUi((s) => s.outputOpen);
  const sw = useSwitch();
  const status = useStatus().data;
  const navigate = useNavigate();

  const keys: Record<string, () => void> = {};
  for (const c of commands) if (c.keys) keys[c.keys] = c.run;
  useHotkeys(keys);

  // native Windows menu and tray send command ids
  useEffect(() => {
    let off: (() => void) | undefined;
    void onNativeMenu((id) => {
      if (id.startsWith("navigate:")) void navigate({ to: id.slice(9) });
      else commands.find((c) => c.id === id)?.run();
    }).then((fn) => (off = fn));
    return () => off?.();
  }, [commands, navigate]);

  useEffect(() => {
    if (status) void syncTray({ paused: status.control.paused, dryRun: status.control.dry_run, today: money(status.earned_today, { cents: true }) });
  }, [status]);

  return (
    <div className="flex h-full flex-col bg-bg">
      {!IN_TAURI && <MenuBar commands={commands} />}
      <MainToolbar onSwitchOff={onSwitchOff} />
      <DryRunBar />
      <Panes direction="vertical" autoSaveId="clipper.shell.v" className="flex-1">
        <Pane id="main" order={1} minSize={30}>
          <Panes direction="horizontal" autoSaveId="clipper.shell.h">
            <Pane id="tree" order={1} defaultSize={15} minSize={10} maxSize={30} className="bg-panel">
              <NavTree />
            </Pane>
            <Splitter />
            <Pane id="doc" order={2} defaultSize={85}>
              <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <Outlet />
              </main>
            </Pane>
          </Panes>
        </Pane>
        {outputOpen && (
          <>
            <Splitter direction="vertical" />
            <Pane id="output" order={2} defaultSize={18} minSize={8} maxSize={60}>
              <OutputPanel />
            </Pane>
          </>
        )}
      </Panes>
      <StatusBar />
      <CommandBox commands={commands} />
      <StopAllDialog />
      <SettingsDialog onSwitchOff={onSwitchOff} />
      <SwitchOffDialog target={switchOff} onClose={() => setSwitchOff(null)} onConfirm={(v) => sw.mutate(v)} />
    </div>
  );
}
