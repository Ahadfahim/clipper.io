import { useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { money, span } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { useBrowserWindow } from "@/api/actions";
import { useLive } from "@/api/live";
import { useStatus } from "@/api/queries";
import { Popover } from "@/components/ui/popover";
import { Dot, type StatusTone } from "@/components/ui/status";
import { UsageMeter } from "@/components/domain/meters";
import { useUi } from "@/state/ui";

function Seg({ tone, children, onClick, title }: { tone: StatusTone; children: ReactNode; onClick?: () => void; title?: string }) {
  const body = (
    <>
      <Dot tone={tone} className="size-[7px]" />
      {children}
    </>
  );
  const cls = "inline-flex h-full items-center gap-1.5 border-r border-line px-2.5";
  return onClick ? (
    <button type="button" onClick={onClick} title={title} className={cn(cls, "hover:bg-panel-2")}>
      {body}
    </button>
  ) : (
    <span className={cls} title={title}>
      {body}
    </span>
  );
}

/** Live health at a glance; each segment opens the related view (UI.md §2). */
export function StatusBar() {
  const s = useStatus().data;
  const conn = useLive((x) => x.conn);
  const ui = useUi();
  const navigate = useNavigate();
  const browser = useBrowserWindow();
  if (!s) return <footer className="h-6 shrink-0 border-t border-line bg-chrome" />;
  const mainBrowser = s.browser.find((b) => b.name === "main");
  const c = s.control;
  const run: { tone: StatusTone; text: string } = c.kill_switch
    ? { tone: "bad", text: "Stopped" }
    : c.paused
      ? { tone: "warn", text: "Paused" }
      : s.usage.rate_limited
        ? { tone: "warn", text: "Waiting for usage reset" }
        : { tone: "ok", text: "Running" };
  const resets = s.usage.resets_at ? span(Date.parse(s.usage.resets_at) - nowMs()) : null;
  return (
    <footer className="flex h-6 shrink-0 items-stretch overflow-hidden border-t border-line bg-chrome text-[11px] text-muted [&>*]:shrink-0">
      <Seg tone={run.tone}>{run.text}</Seg>
      {c.dry_run && <Seg tone="warn">Dry run</Seg>}
      <Seg tone="agent" onClick={() => void navigate({ to: "/agents" })} title="Agent slots">
        Agents {s.agents_running}/{s.agents_capacity || "∞"}
      </Seg>
      <Seg tone={s.jobs_running ? "ok" : "muted"} onClick={() => ui.setOutputTab("jobs")} title="Jobs">
        {s.gpu_util !== null && s.gpu_util !== undefined ? `GPU ${Math.round(s.gpu_util * 100)}% · ` : ""}
        {s.jobs_running + s.jobs_queued} jobs
      </Seg>
      <Popover
        trigger={
          <button type="button" className="inline-flex h-full items-center gap-1.5 border-r border-line px-2.5 hover:bg-panel-2">
            <Dot tone={s.usage.utilization >= 0.8 || s.usage.rate_limited ? "warn" : "accent"} className="size-[7px]" />
            Claude usage {Math.round(s.usage.utilization * 100)}%{resets ? ` · resets ${resets}` : ""}
          </button>
        }
      >
        <div className="flex w-[300px] flex-col gap-2">
          <div className="font-semibold">Claude plan usage</div>
          <UsageMeter usage={s.usage} />
          <div className="text-muted">
            Pace: <span className="text-fg">{s.usage.pace}</span>.{" "}
            {s.usage.rate_limited ? (
              <>Every agent waits for the usage window to reset.</>
            ) : s.usage.max_slots === 0 ? (
              <>No slot limit: the pool grows with the campaigns.</>
            ) : (
              <>
                Up to <span className="num text-fg">{s.usage.max_slots}</span> agent slots right now; a fixed pool shrinks as usage rises.
              </>
            )}{" "}
            Only P0–P1 work runs near the limit. Runs on your Claude plan login, no API billing.
          </div>
        </div>
      </Popover>
      {mainBrowser && (
        <Seg
          tone={!mainBrowser.running ? "warn" : mainBrowser.visible ? "accent" : "muted"}
          onClick={() => browser.mutate({ profile: "main", action: "toggle" })}
          title="Clipper's own Chrome · click to show or hide it (Ctrl+Shift+B)"
        >
          Browser {!mainBrowser.running ? "not running" : mainBrowser.visible ? "shown" : "hidden"}
        </Seg>
      )}
      <Seg tone={s.extension_profiles.length ? "ok" : "warn"} onClick={() => ui.openSettings("browser")} title="Chrome profiles with the Companion extension">
        Extension {s.extension_profiles.length}
      </Seg>
      <Seg tone={s.discord_online ? "ok" : "warn"} onClick={() => ui.openSettings("discord")}>
        Discord
      </Seg>
      {conn !== "fixture" && conn !== "open" && <Seg tone="bad">Core {conn === "connecting" ? "connecting…" : "offline"}</Seg>}
      {s.fixture_mode || conn === "fixture" ? <Seg tone="muted">Fixture data</Seg> : null}
      <span className="flex-1 border-r-0" />
      <Seg tone="ok" title="Earned today">
        Today <span className="num text-fg">{money(s.earned_today, { cents: true })}</span>
      </Seg>
    </footer>
  );
}
