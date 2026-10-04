import { ArrowUpload16Regular, Checkmark16Regular, Globe16Regular, Pause16Filled, Play16Filled, Search16Regular } from "@fluentui/react-icons";
import { useNavigate } from "@tanstack/react-router";
import { useBrowserWindow, useControl, useShip, useSwitch, useTrigger } from "@/api/actions";
import { useBatches, useStatus, useSwitches } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Check } from "@/components/ui/fields";
import { Toolbar, ToolbarSep } from "@/components/ui/misc";
import { SwitchChip } from "@/components/domain/switches";
import { accountTone } from "@/components/domain/badges";
import { MARKET_LABEL, MARKET_ORDER, PLATFORM_LABEL, PLATFORM_ORDER } from "@/lib/platforms";
import { useUi } from "@/state/ui";

/**
 * Pause all · Dry run · Scout now · Review queue · Ship approved · marketplace and social
 * on/off checkboxes (PLAN §15) · search/command box.
 */
export function MainToolbar({ onSwitchOff }: { onSwitchOff: (t: { level: "marketplace" | "social"; name: string; label: string }) => void }) {
  const status = useStatus().data;
  const switches = useSwitches().data;
  const batches = useBatches().data;
  const control = useControl();
  const sw = useSwitch();
  const ship = useShip();
  const trigger = useTrigger();
  const navigate = useNavigate();
  const openCommand = useUi((s) => s.openCommand);
  const c = status?.control;
  const batch = batches?.find((b) => b.pending > 0) ?? batches?.find((b) => b.status === "in_review");
  const shippable = batches?.find((b) => b.status !== "shipped" && b.approved > 0);
  const browser = useBrowserWindow();
  const mainBrowser = status?.browser.find((b) => b.name === "main");

  return (
    <Toolbar label="Main toolbar" className="flex-nowrap overflow-hidden [&>*]:shrink-0">
      <Button icon={c?.paused ? <Play16Filled /> : <Pause16Filled />} onClick={() => control.mutate({ key: "paused", value: !c?.paused })} title="Ctrl+Shift+P">
        {c?.paused ? "Resume all" : "Pause all"}
      </Button>
      <Check checked={Boolean(c?.dry_run)} onChange={(v) => control.mutate({ key: "dry_run", value: v })} label="Dry run" title="Ctrl+Shift+D" />
      <ToolbarSep />
      <Button variant="ghost" icon={<Search16Regular />} onClick={() => trigger.mutate("scout")}>
        Scout now
      </Button>
      <Button
        variant="ghost"
        icon={<Checkmark16Regular />}
        onClick={() => (batch ? void navigate({ to: "/review/$batchId", params: { batchId: String(batch.id) } }) : void navigate({ to: "/review" }))}
      >
        Review queue ({status?.review_pending ?? 0})
      </Button>
      <Button variant="ghost" icon={<ArrowUpload16Regular />} disabled={!shippable} onClick={() => shippable && ship.mutate(shippable.id)}>
        Ship approved
      </Button>
      <Button
        variant="ghost"
        icon={<Globe16Regular />}
        aria-pressed={Boolean(mainBrowser?.visible)}
        onClick={() => browser.mutate({ profile: "main", action: "toggle" })}
        title={`Clipper's own Chrome runs hidden; show it to watch the agents or fix a login (Ctrl+Shift+B)${mainBrowser && !mainBrowser.extension_connected ? " · extension not connected" : ""}`}
      >
        {mainBrowser?.visible ? "Hide browser" : "Show browser"}
      </Button>
      <ToolbarSep />
      <span className="px-1 text-muted max-[1365px]:hidden">Sources</span>
      {MARKET_ORDER.map((m) => {
        const s = switches?.marketplaces[m];
        if (!s) return null;
        return (
          <SwitchChip
            key={m}
            label={MARKET_LABEL[m] ?? m}
            on={s.enabled}
            health={s.session_ok ? undefined : "warn"}
            title={s.session_ok ? `${s.name}: logged in` : `${s.name}: needs login`}
            onToggle={(on) => (on ? sw.mutate({ level: "marketplace", name: m, enabled: true }) : onSwitchOff({ level: "marketplace", name: m, label: MARKET_LABEL[m] ?? m }))}
          />
        );
      })}
      <span className="pr-1 pl-2.5 text-muted max-[1365px]:hidden">Post to</span>
      <span aria-hidden="true" className="mx-1 hidden h-5 w-px bg-line max-[1365px]:inline-block" />
      {PLATFORM_ORDER.map((p) => {
        const s = switches?.socials[p];
        if (!s) return null;
        const accs = switches?.accounts.filter((a) => a.platform === p) ?? [];
        const bad = accs.some((a) => accountTone(a.status, a.enabled) === "warn");
        return (
          <SwitchChip
            key={p}
            label={PLATFORM_LABEL[p] ?? p}
            on={s.enabled}
            health={bad ? "warn" : undefined}
            title={bad ? `${PLATFORM_LABEL[p]}: an account needs you` : `${s.accounts} account(s)`}
            onToggle={(on) => (on ? sw.mutate({ level: "social", name: p, enabled: true }) : onSwitchOff({ level: "social", name: p, label: PLATFORM_LABEL[p] ?? p }))}
          />
        );
      })}
      <span className="min-w-2 flex-1" />
      <button
        type="button"
        onClick={() => openCommand("")}
        aria-label="Search campaigns, clips and commands"
        className="flex h-[var(--control)] w-[280px] items-center gap-2 rounded-[var(--radius)] border border-line border-b-muted bg-panel px-2.5 text-left text-muted max-[1439px]:w-auto"
      >
        <Search16Regular />
        <span className="flex-1 truncate-1 max-[1439px]:hidden">Search campaigns, clips, commands</span>
        <span className="num text-[11px]">Ctrl+K</span>
      </button>
    </Toolbar>
  );
}

/** Thin yellow bar under the toolbar while dry run is on. */
export function DryRunBar() {
  const dry = useStatus().data?.control.dry_run;
  if (!dry) return null;
  return (
    <div role="status" className="flex h-[22px] shrink-0 items-center gap-2 border-b border-warn-strong/50 bg-warn-soft px-3 text-[11px]">
      <span className="inline-block size-2 rounded-full bg-warn-strong" aria-hidden="true" />
      Dry run is on: uploads and submissions are simulated. Nothing is posted.
    </div>
  );
}
