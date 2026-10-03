import * as D from "@radix-ui/react-dialog";
import { Dismiss16Regular } from "@fluentui/react-icons";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useDeleteLesson, useEditLesson, usePatchSettings, useSavePrompt, useSaveSecret, useSwitch } from "@/api/actions";
import { useCampaigns, useDoctor, useLessons, usePrompts, useSettings, useStatus, useSwitches, useTools } from "@/api/queries";
import { useLive } from "@/api/live";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Check, Field, Fieldset, Radio, Select, TextArea, TextField } from "@/components/ui/fields";
import { Badge, Kbd } from "@/components/ui/misc";
import { Dot, type StatusTone } from "@/components/ui/status";
import { ToggleCard } from "@/components/domain/switches";
import { LessonRow } from "@/components/domain/lessons";
import { accountTone } from "@/components/domain/badges";
import { cn } from "@/lib/cn";
import { clock, day } from "@/lib/format";
import { MARKET_LABEL, MARKET_ORDER, PLATFORM_LABEL, PLATFORM_ORDER, ROLE_LABEL } from "@/lib/platforms";
import { autostartGet, autostartSet, IN_TAURI, openProfile } from "@/lib/tauri";
import { useUi } from "@/state/ui";
import type { SwitchTarget } from "@/shell/AppShell";

export const SECTIONS = [
  { id: "general", label: "General" },
  { id: "markets", label: "Marketplaces and socials" },
  { id: "automation", label: "Automation" },
  { id: "usage", label: "Usage pacing" },
  { id: "agents", label: "Agents" },
  { id: "browser", label: "Accounts and browser" },
  { id: "discord", label: "Discord" },
  { id: "media", label: "Media and captions" },
  { id: "storage", label: "Storage" },
  { id: "tools", label: "Tools and MCP" },
  { id: "health", label: "Health" },
  { id: "keys", label: "Keyboard shortcuts" },
] as const;

type Draft = Record<string, unknown>;
type Ctx = { s: Record<string, unknown>; draft: Draft; set: (key: string, v: unknown) => void };

/** Reads a dotted key from the draft first, then the saved settings. */
function val<T>(ctx: Ctx, key: string): T {
  if (key in ctx.draft) return ctx.draft[key] as T;
  return key.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), ctx.s) as T;
}

function H({ children }: { children: ReactNode }) {
  return <h1 className="mb-1 text-[16px] font-semibold">{children}</h1>;
}

function NumField({ ctx, k, label, hint, min, max, step }: { ctx: Ctx; k: string; label: string; hint?: string; min?: number; max?: number; step?: number }) {
  return (
    <Field label={label} hint={hint}>
      {(id) => <TextField id={id} type="number" min={min} max={max} step={step} value={String(val<number | null>(ctx, k) ?? "")} onChange={(e) => ctx.set(k, e.target.value === "" ? null : Number(e.target.value))} className="w-32" />}
    </Field>
  );
}

function TextSetting({ ctx, k, label, hint, placeholder, width = "w-full" }: { ctx: Ctx; k: string; label: string; hint?: string; placeholder?: string; width?: string }) {
  return (
    <Field label={label} hint={hint}>
      {(id) => <TextField id={id} value={String(val<string | null>(ctx, k) ?? "")} placeholder={placeholder} onChange={(e) => ctx.set(k, e.target.value || null)} className={width} />}
    </Field>
  );
}

/* ---------------------------------------------------------------- sections */

function General({ ctx }: { ctx: Ctx }) {
  const ui = useUi();
  return (
    <>
      <H>General</H>
      <Fieldset legend="Theme">
        <div className="flex gap-4">
          {(["system", "light", "dark"] as const).map((t) => (
            <Radio key={t} name="theme" checked={ui.theme === t} onChange={() => (ui.setTheme(t), ctx.set("ui.theme", t))} label={t === "system" ? "Follow Windows" : t[0]!.toUpperCase() + t.slice(1)} />
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Accent color">
        <div className="flex items-center gap-4">
          <Radio name="accent" checked={ui.accent === null} onChange={() => (ui.setAccent(null), ctx.set("ui.accent", null))} label="Windows accent" />
          <Radio name="accent" checked={ui.accent !== null} onChange={() => (ui.setAccent(ui.systemAccent ?? "#005fb8"), ctx.set("ui.accent", ui.systemAccent ?? "#005fb8"))} label="Custom" />
          <label className="flex items-center gap-1.5">
            <span className="sr-only">Custom accent</span>
            <input type="color" value={ui.accent ?? ui.systemAccent ?? "#005fb8"} disabled={ui.accent === null} onChange={(e) => (ui.setAccent(e.target.value), ctx.set("ui.accent", e.target.value))} className="h-6 w-10 border border-line bg-transparent" />
          </label>
        </div>
      </Fieldset>
      <Fieldset legend="Density">
        <div className="flex gap-4">
          <Radio name="density" checked={ui.density === "compact"} onChange={() => (ui.setDensity("compact"), ctx.set("ui.density", "compact"))} label="Compact" />
          <Radio name="density" checked={ui.density === "comfortable"} onChange={() => (ui.setDensity("comfortable"), ctx.set("ui.density", "comfortable"))} label="Comfortable" />
        </div>
      </Fieldset>
      <StartWithWindows />
      <Fieldset legend="Safety">
        <Check checked={Boolean(val<boolean>(ctx, "dry_run_default"))} onChange={(v) => ctx.set("dry_run_default", v)} label="Start in dry run (uploads and submissions are simulated)" />
      </Fieldset>
    </>
  );
}

function StartWithWindows() {
  const [on, setOn] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    void autostartGet().then(setOn);
  }, []);
  if (!IN_TAURI) return null;
  return (
    <Fieldset legend="Startup">
      <Check
        checked={Boolean(on)}
        onChange={(v) => {
          setOn(v);
          void autostartSet(v);
        }}
        label="Start with Windows (minimized to the tray)"
      />
    </Fieldset>
  );
}

function Markets({ ctx, onSwitchOff }: { ctx: Ctx; onSwitchOff: (t: SwitchTarget) => void }) {
  const sw = useSwitch();
  const switches = useSwitches().data;
  const campaigns = useCampaigns().data ?? [];
  const events = useLive((s) => s.events);
  const changes = events.filter((e) => e.type === "toggles.changed").slice(-8).reverse();
  if (!switches) return <H>Marketplaces and socials</H>;
  return (
    <>
      <H>Marketplaces and socials</H>
      <Fieldset legend="Marketplaces">
        {MARKET_ORDER.map((m) => {
          const s = switches.marketplaces[m];
          if (!s) return null;
          const active = campaigns.filter((c) => c.marketplace === m && c.status === "active").length;
          const tone: StatusTone = !s.enabled ? "off" : s.session_ok ? "ok" : "warn";
          return (
            <div key={m} className="flex flex-col gap-1.5 border-b border-line-soft pb-2 last:border-b-0">
              <ToggleCard
                name={MARKET_LABEL[m] ?? m}
                on={s.enabled}
                tone={tone}
                status={!s.enabled ? "Off · scout skips it" : s.session_ok ? `Logged in · ${active} active campaign${active === 1 ? "" : "s"}` : "Needs login in the Chrome profile"}
                onToggle={(on) => (on ? sw.mutate({ level: "marketplace", name: m, enabled: true }) : onSwitchOff({ level: "marketplace", name: m, label: MARKET_LABEL[m] ?? m }))}
              >
                <Button size="sm" onClick={() => void openProfile("main")}>
                  {s.session_ok ? "Open" : "Log in"}
                </Button>
              </ToggleCard>
              <div className="flex flex-wrap items-end gap-4 pl-6">
                <NumField ctx={ctx} k={`marketplaces.${m}.min_cpm`} label="Minimum CPM ($)" step={0.1} min={0} />
                {m === "whop" && (
                  <div className="flex flex-col gap-1 pb-1">
                    <Check checked={Boolean(val<boolean>(ctx, "marketplaces.whop.include_ugc"))} onChange={(v) => ctx.set("marketplaces.whop.include_ugc", v)} label="Include UGC campaigns" />
                    <Check checked={Boolean(val<boolean>(ctx, "marketplaces.whop.auto_join_free"))} onChange={(v) => ctx.set("marketplaces.whop.auto_join_free", v)} label="Join free Whops automatically (paid joins always ask)" />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </Fieldset>
      <Fieldset legend="Socials and accounts">
        {PLATFORM_ORDER.map((p) => {
          const s = switches.socials[p];
          if (!s) return null;
          const accs = switches.accounts.filter((a) => a.platform === p);
          return (
            <div key={p} className="flex flex-col">
              <ToggleCard
                name={PLATFORM_LABEL[p] ?? p}
                on={s.enabled}
                tone={s.enabled ? "ok" : "off"}
                locked={p === "x" && !s.enabled && s.accounts === 0}
                status={p === "x" && s.accounts === 0 ? "Upload script arrives later" : s.enabled ? `On · ${s.accounts} account${s.accounts === 1 ? "" : "s"}` : "Off"}
                onToggle={(on) => (on ? sw.mutate({ level: "social", name: p, enabled: true }) : onSwitchOff({ level: "social", name: p, label: PLATFORM_LABEL[p] ?? p }))}
              />
              {accs.map((a) => (
                <ToggleCard
                  key={a.id}
                  indent
                  name={a.handle}
                  on={a.enabled && s.enabled}
                  locked={!s.enabled}
                  tone={accountTone(a.status, a.enabled && s.enabled)}
                  status={a.paused_reason ? `Paused: ${a.paused_reason}` : a.enabled ? "Connected" : "Off"}
                  onToggle={(on) => sw.mutate({ level: "account", name: String(a.id), enabled: on })}
                />
              ))}
            </div>
          );
        })}
      </Fieldset>
      <Fieldset legend="Change log">
        {changes.length === 0 && <span className="text-muted">No switch changes yet.</span>}
        {changes.map((e) => {
          const p = e.payload as { name: string; enabled: boolean; by: string; via: string };
          return (
            <div key={e.id} className="flex gap-3">
              <span className="num text-muted">
                {day(e.ts)} {clock(e.ts, false)}
              </span>
              <span>
                {MARKET_LABEL[p.name] ?? PLATFORM_LABEL[p.name] ?? p.name} turned {p.enabled ? "on" : "off"}
              </span>
              <span className="text-muted">
                by {p.by} from {p.via === "app" ? "the app" : p.via}
              </span>
            </div>
          );
        })}
      </Fieldset>
    </>
  );
}

function Automation({ ctx }: { ctx: Ctx }) {
  const status = useStatus().data;
  const tier = status?.control.auto_approve_tier;
  return (
    <>
      <H>Automation</H>
      <Fieldset legend="Scout">
        <div className="flex gap-4">
          <Radio name="scout-mode" checked={val(ctx, "scout.mode") === "suggest"} onChange={() => ctx.set("scout.mode", "suggest")} label="Suggest (you press Take)" />
          <Radio name="scout-mode" checked={val(ctx, "scout.mode") === "auto"} onChange={() => ctx.set("scout.mode", "auto")} label="Auto-take high scores" />
        </div>
        <div className="flex flex-wrap gap-4">
          <NumField ctx={ctx} k="scout.auto_take_min_score" label="Auto-take at score" min={50} max={100} />
          <NumField ctx={ctx} k="scout.min_score_to_post_card" label="Post a card from score" min={0} max={100} />
          <NumField ctx={ctx} k="triggers.scout_every_min" label="Scout every (min)" min={5} />
        </div>
        <Check checked={Boolean(val<boolean>(ctx, "scout.prefetch_sources"))} onChange={(v) => ctx.set("scout.prefetch_sources", v)} label="Pre-download sources for suggested campaigns" />
      </Fieldset>
      <Fieldset legend="Review">
        <div className="flex flex-wrap items-end gap-4">
          <NumField ctx={ctx} k="review.approve_all_threshold" label="Approve all at score" min={0} max={100} />
          <NumField ctx={ctx} k="review.timeout_hours" label="Batch timeout (hours, 0 = never)" min={0} step={0.5} />
          <Field label="When a batch times out">
            {(id) => (
              <Select id={id} value={String(val(ctx, "review.timeout_action"))} onChange={(e) => ctx.set("review.timeout_action", e.target.value)}>
                <option value="ship_approved">Ship what's approved</option>
                <option value="reject_rest">Reject the rest</option>
              </Select>
            )}
          </Field>
        </div>
      </Fieldset>
      <Fieldset legend="Auto-approve">
        <span className={tier ? "" : "text-muted"}>
          {tier ? `On for clips scored ${tier}+.` : "Off. It's offered on the Review screen once your approval history qualifies (100+ decisions, 95%+ approved at that score)."}
        </span>
      </Fieldset>
    </>
  );
}

function Usage({ ctx }: { ctx: Ctx }) {
  const slowFirst = val<string[]>(ctx, "usage.slow_first") ?? [];
  return (
    <>
      <H>Usage pacing</H>
      <p className="m-0 text-muted">Agents run on your Claude plan login. These limits keep a day's work inside your plan's usage windows; nothing is billed per token.</p>
      <Fieldset legend="Limits">
        <div className="flex flex-wrap gap-4">
          <NumField ctx={ctx} k="usage.daily_agent_run_cap" label="Agent runs per day" min={10} />
          <NumField ctx={ctx} k="agents.slots" label="Agent slots" min={1} max={8} />
          <NumField ctx={ctx} k="usage.p01_only_at" label="Only P0–P1 work from usage" min={0.5} max={1} step={0.05} hint="0.9 = 90% of the window" />
        </div>
      </Fieldset>
      <Fieldset legend="Slow down first under high usage">
        <div className="flex gap-4">
          {(["scout", "analyst", "director", "campaign"] as const).map((r) => (
            <Check key={r} checked={slowFirst.includes(r)} onChange={(on) => ctx.set("usage.slow_first", on ? [...slowFirst, r] : slowFirst.filter((x) => x !== r))} label={ROLE_LABEL[r] ?? r} />
          ))}
        </div>
      </Fieldset>
      <Check checked={Boolean(val<boolean>(ctx, "usage.auto_resume_after_reset"))} onChange={(v) => ctx.set("usage.auto_resume_after_reset", v)} label="Resume automatically when the usage window resets" />
      <Check checked={Boolean(val<boolean>(ctx, "agents.reserve_p0_slot"))} onChange={(v) => ctx.set("agents.reserve_p0_slot", v)} label="Keep one slot free for your requests (P0)" />
    </>
  );
}

/** Line diff (LCS) for the prompt editor. */
export function lineDiff(a: string, b: string): { kind: " " | "+" | "-"; text: string }[] {
  const x = a.split("\n");
  const y = b.split("\n");
  const n = x.length;
  const m = y.length;
  const L: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i]![j] = x[i] === y[j] ? L[i + 1]![j + 1]! + 1 : Math.max(L[i + 1]![j]!, L[i]![j + 1]!);
  const out: { kind: " " | "+" | "-"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      out.push({ kind: " ", text: x[i]! });
      i++;
      j++;
    } else if (L[i + 1]![j]! >= L[i]![j + 1]!) out.push({ kind: "-", text: x[i++]! });
    else out.push({ kind: "+", text: y[j++]! });
  }
  while (i < n) out.push({ kind: "-", text: x[i++]! });
  while (j < m) out.push({ kind: "+", text: y[j++]! });
  return out;
}

function Agents({ ctx }: { ctx: Ctx }) {
  const prompts = usePrompts().data ?? [];
  const save = useSavePrompt();
  const [name, setName] = useState("campaign");
  const current = prompts.find((p) => p.name === name);
  const [text, setText] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [result, setResult] = useState<Schemas["PromptSaveOut"] | null>(null);
  useEffect(() => {
    setText(current?.text ?? "");
    setResult(null);
  }, [current?.text, name]);
  const roles = Object.keys((val<Record<string, unknown>>(ctx, "agents.roles") ?? {}) as Record<string, unknown>);
  const subs = Object.keys((val<Record<string, unknown>>(ctx, "agents.subagents") ?? {}) as Record<string, unknown>);
  const diff = useMemo(() => (showDiff ? lineDiff(current?.text ?? "", text) : []), [showDiff, current?.text, text]);
  return (
    <>
      <H>Agents</H>
      <div className="flex items-center gap-2">
        <span className="text-muted">Model</span>
        <span className="num">{String(val(ctx, "agents.model"))}</span>
        <Badge>Claude plan login</Badge>
      </div>
      <Fieldset legend="Effort and turn limits">
        <div className="grid items-center gap-x-3 gap-y-1" style={{ gridTemplateColumns: "140px 120px 110px" }}>
          <span className="text-muted">Agent</span>
          <span className="text-muted">Effort</span>
          <span className="text-muted">Max turns</span>
          {[...roles.map((r) => ["roles", r] as const), ...subs.map((r) => ["subagents", r] as const)].map(([kind, r]) => (
            <div key={r} className="contents">
              <span className={kind === "subagents" ? "pl-3 text-muted" : ""}>{ROLE_LABEL[r] ?? r}</span>
              <Select aria-label={`${r} effort`} value={String(val(ctx, `agents.${kind}.${r}.effort`))} onChange={(e) => ctx.set(`agents.${kind}.${r}.effort`, e.target.value)} className="h-6">
                {["low", "medium", "high", "max"].map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </Select>
              <TextField aria-label={`${r} max turns`} type="number" min={1} value={String(val(ctx, `agents.${kind}.${r}.max_turns`) ?? "")} onChange={(e) => ctx.set(`agents.${kind}.${r}.max_turns`, Number(e.target.value))} className="h-6 w-24" />
            </div>
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Prompts">
        <div className="flex items-center gap-2">
          <Select aria-label="Prompt" value={name} onChange={(e) => setName(e.target.value)} className="w-56">
            {prompts.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
                {p.overridden ? " (edited)" : ""}
              </option>
            ))}
          </Select>
          <Check checked={showDiff} onChange={setShowDiff} label="Show diff" />
          <span className="flex-1" />
          <Button
            variant="primary"
            disabled={!current || text === current.text}
            onClick={() => save.mutate({ name, text }, { onSuccess: (r) => setResult(r as Schemas["PromptSaveOut"]) })}
          >
            Test and save
          </Button>
        </div>
        {showDiff ? (
          <pre className="num selectable m-0 max-h-[260px] overflow-auto rounded-[var(--radius)] border border-line bg-bg p-2 text-[11px] whitespace-pre-wrap">
            {diff.map((l, i) => (
              <div key={i} className={l.kind === "+" ? "bg-[color-mix(in_srgb,var(--ok)_16%,transparent)]" : l.kind === "-" ? "bg-bad-soft line-through" : "text-muted"}>
                {l.kind} {l.text}
              </div>
            ))}
          </pre>
        ) : (
          <TextArea aria-label="Prompt text" rows={12} value={text} onChange={(e) => setText(e.target.value)} className="num text-[11px]" />
        )}
        <span className="text-muted">Saving runs the quality test set (PLAN §14) first; the prompt only changes when it passes.</span>
        {result && (
          <span className={result.saved ? "text-ok" : "text-bad"}>
            {result.saved ? "Saved." : "Not saved."} Quality test: {result.eval_status ?? "fixture mode"}
          </span>
        )}
      </Fieldset>
    </>
  );
}

function Browser({ ctx, secrets, pairing }: { ctx: Ctx; secrets: Record<string, boolean>; pairing: string | null }) {
  const saveSecret = useSaveSecret();
  const status = useStatus().data;
  const [shown, setShown] = useState<string | null>(null);
  const allow = (val<Record<string, string[]>>(ctx, "browser.domain_allowlist") ?? {}) as Record<string, string[]>;
  return (
    <>
      <H>Accounts and browser</H>
      <Fieldset legend="Chrome">
        <TextSetting ctx={ctx} k="paths.chrome_exe" label="Chrome" />
        <TextSetting ctx={ctx} k="paths.chrome_profiles_dir" label="Profiles folder" />
        <span className="flex items-center gap-1.5">
          <Dot tone={status?.extension_profiles.length ? "ok" : "warn"} />
          Companion extension connected in: {status?.extension_profiles.join(", ") || "no profiles"}
        </span>
      </Fieldset>
      <Fieldset legend="Extension pairing">
        <span className="text-muted">Paste this token into the Companion extension's options in each Chrome profile. It only works on this PC (127.0.0.1).</span>
        <div className="flex items-center gap-2">
          <TextField readOnly aria-label="Pairing token" value={shown ?? (secrets["extension_pairing_token"] || pairing ? "••••••••••••••••" : "not set")} className="num w-72" />
          <Button
            onClick={() => {
              const token = Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, "0")).join("");
              saveSecret.mutate({ name: "extension_pairing_token", value: token });
              setShown(token);
            }}
          >
            {secrets["extension_pairing_token"] ? "New token" : "Create token"}
          </Button>
          <Button disabled={!shown} onClick={() => shown && void navigator.clipboard?.writeText(shown)}>
            Copy
          </Button>
        </div>
      </Fieldset>
      <Fieldset legend="Posting defaults">
        <div className="flex flex-wrap gap-4">
          <NumField ctx={ctx} k="posting.default_daily_cap" label="Posts per account per day" min={1} max={10} />
          <NumField ctx={ctx} k="posting.min_gap_min" label="Minimum gap (min)" min={30} />
          <NumField ctx={ctx} k="posting.warmup.week1_daily_cap" label="Warm-up week 1 cap" min={1} />
          <NumField ctx={ctx} k="posting.warmup.week2_daily_cap" label="Warm-up week 2 cap" min={1} />
        </div>
      </Fieldset>
      <Fieldset legend="Allowed domains (enforced in code)">
        {Object.entries(allow).map(([k, v]) => (
          <div key={k} className="flex gap-3">
            <span className="w-24 text-muted">{MARKET_LABEL[k] ?? PLATFORM_LABEL[k] ?? k}</span>
            <span className="num">{v.join(", ")}</span>
          </div>
        ))}
      </Fieldset>
    </>
  );
}

function Discord({ ctx, secrets }: { ctx: Ctx; secrets: Record<string, boolean> }) {
  const saveSecret = useSaveSecret();
  const [token, setToken] = useState("");
  const status = useStatus().data;
  const channels = ["campaigns", "clip_review", "published", "alerts", "control"];
  return (
    <>
      <H>Discord</H>
      <span className="flex items-center gap-1.5">
        <Dot tone={status?.discord_online ? "ok" : "warn"} /> Bot {status?.discord_online ? "online" : "offline"}
      </span>
      <Check checked={Boolean(val<boolean>(ctx, "discord.enabled"))} onChange={(v) => ctx.set("discord.enabled", v)} label="Run the Discord bot" />
      <Fieldset legend="Bot token">
        <span className="text-muted">Stored in Windows Credential Manager, never in settings.toml. {secrets["discord_bot_token"] ? "A token is saved." : "No token saved."}</span>
        <div className="flex gap-2">
          <TextField type="password" aria-label="Bot token" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste a new token" className="w-80" />
          <Button disabled={!token} onClick={() => (saveSecret.mutate({ name: "discord_bot_token", value: token }), setToken(""))}>
            Save token
          </Button>
        </div>
      </Fieldset>
      <Fieldset legend="Server and channels">
        <TextSetting ctx={ctx} k="discord.guild_id" label="Server id" width="w-64" />
        <div className="grid grid-cols-2 gap-x-4 gap-y-2">
          {channels.map((c) => (
            <TextSetting key={c} ctx={ctx} k={`discord.channels.${c}`} label={`#${c.replace("_", "-")} channel id`} placeholder="created on first run" />
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Reviewers">
        <span className="text-muted">Only members with this role can press buttons or talk to the Director.</span>
        <div className="flex gap-4">
          <TextSetting ctx={ctx} k="discord.reviewer_role_name" label="Role name" width="w-48" />
          <TextSetting ctx={ctx} k="discord.reviewer_role_id" label="Role id" width="w-56" />
        </div>
      </Fieldset>
    </>
  );
}

const STYLE_PREVIEW: Record<string, string> = {
  "bold-pop": "font-extrabold uppercase text-white [text-shadow:0_2px_0_#000,0_0_6px_#000]",
  clean: "font-semibold text-white [text-shadow:0_1px_3px_#000]",
  boxed: "bg-black/85 px-1 font-bold text-white",
  karaoke: "font-extrabold text-white [text-shadow:0_2px_0_#000]",
};

function Media({ ctx }: { ctx: Ctx }) {
  const current = String(val(ctx, "media.default_caption_style"));
  return (
    <>
      <H>Media and captions</H>
      <Fieldset legend="Default caption style">
        <div role="radiogroup" aria-label="Caption style" className="grid grid-cols-4 gap-2">
          {Object.keys(STYLE_PREVIEW).map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={current === s}
              onClick={() => ctx.set("media.default_caption_style", s)}
              className={cn("flex flex-col items-center gap-1 rounded-[var(--radius)] border p-1.5", current === s ? "border-accent bg-accent-soft" : "border-line")}
            >
              <span className="relative flex aspect-[9/16] w-full items-end justify-center bg-[#2a2a2a] pb-[28%]">
                <span className={cn("text-[11px]", STYLE_PREVIEW[s])}>
                  he gave away <span className={s === "karaoke" || s === "bold-pop" ? "text-[#fce100]" : ""}>$1M</span>
                </span>
              </span>
              {s}
            </button>
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Encoding">
        <div className="flex flex-wrap gap-4">
          <Field label="Encoder">
            {(id) => (
              <Select id={id} value={String(val(ctx, "media.encoder"))} onChange={(e) => ctx.set("media.encoder", e.target.value)}>
                <option value="nvenc">NVENC (GPU)</option>
                <option value="x264">x264 (CPU)</option>
              </Select>
            )}
          </Field>
          <TextSetting ctx={ctx} k="media.nvenc_preset" label="NVENC preset" width="w-24" />
          <TextSetting ctx={ctx} k="media.final_bitrate" label="Final bitrate" width="w-24" />
          <NumField ctx={ctx} k="media.loudness_lufs" label="Loudness (LUFS)" min={-24} max={-9} />
        </div>
      </Fieldset>
    </>
  );
}

function Storage({ ctx }: { ctx: Ctx }) {
  const doctor = useDoctor().data ?? [];
  const disk = doctor.find((d) => d.name.toLowerCase().includes("disk"));
  return (
    <>
      <H>Storage</H>
      <Fieldset legend="Data folder">
        <TextSetting ctx={ctx} k="paths.data_dir" label="Folder" hint="Moving it takes effect after a restart; move the files yourself first." />
        {disk && (
          <span className="flex items-center gap-1.5">
            <Dot tone={disk.status === "ok" ? "ok" : "warn"} /> {disk.detail}
          </span>
        )}
      </Fieldset>
      <Fieldset legend="Retention">
        <div className="flex flex-wrap gap-4">
          <NumField ctx={ctx} k="retention.sources_days_after_end" label="Keep sources after a campaign ends (days)" min={0} />
          <NumField ctx={ctx} k="retention.failure_screenshots_days" label="Failure screenshots (days)" min={1} />
          <NumField ctx={ctx} k="retention.logs_days" label="Logs (days)" min={1} />
        </div>
      </Fieldset>
      <Fieldset legend="Backups">
        <div className="flex flex-wrap gap-4">
          <TextSetting ctx={ctx} k="retention.nightly_backup_at" label="Nightly backup at" width="w-24" />
          <NumField ctx={ctx} k="retention.backups_keep" label="Backups to keep" min={1} />
        </div>
      </Fieldset>
    </>
  );
}

function Tools() {
  const tools = useTools().data;
  const [q, setQ] = useState("");
  const lessons = useLessons().data ?? [];
  const del = useDeleteLesson();
  const edit = useEditLesson();
  const shown = lessons.filter((l) => !q || l.note.toLowerCase().includes(q.toLowerCase()) || l.scope.includes(q));
  const servers = tools?.servers ?? [];
  const agents = Object.keys(tools?.access ?? {});
  return (
    <>
      <H>Tools and MCP</H>
      <Fieldset legend="MCP servers (last 7 days)">
        <div className="grid gap-x-3" style={{ gridTemplateColumns: "120px repeat(5, 70px)" }}>
          {["Server", "Tools", "Read-only", "Calls", "Errors", "Blocked"].map((h) => (
            <span key={h} className={cn("text-muted", h !== "Server" && "text-right")}>
              {h}
            </span>
          ))}
          {servers.map((s) => (
            <div key={s.server} className="contents">
              <span className="num">{s.server}</span>
              <span className="num text-right">{s.tools}</span>
              <span className="num text-right">{s.read_only}</span>
              <span className="num text-right">{s.calls_7d}</span>
              <span className={cn("num text-right", s.errors_7d ? "text-bad" : "")}>{s.errors_7d}</span>
              <span className={cn("num text-right", s.blocked_7d ? "text-warn" : "")}>{s.blocked_7d}</span>
            </div>
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Access matrix: tools per agent (max 25)">
        <span className="text-muted">Which agent may call which tools is part of the safety rules, so it lives in code (core/clipper/agents/access.py) and changes go through review. The guard enforces it on every call.</span>
        <div className="overflow-auto">
          <table className="border-collapse">
            <thead>
              <tr>
                <th className="px-1.5 text-left font-normal text-muted">Agent</th>
                {[...new Set((tools?.servers ?? []).map((s) => s.server))].map((s) => (
                  <th key={s} className="num px-1 font-normal text-muted [writing-mode:vertical-rl]">
                    {s}
                  </th>
                ))}
                <th className="px-1.5 text-right font-normal text-muted">Total</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => {
                const list = tools?.access[a] ?? [];
                return (
                  <tr key={a} className="border-t border-line-soft">
                    <td className="px-1.5">{ROLE_LABEL[a] ?? a}</td>
                    {servers.map((s) => {
                      const n = list.filter((t) => t.startsWith(`mcp__${s.server}__`)).length;
                      return (
                        <td key={s.server} className={cn("num px-1 text-center", n ? "" : "text-faint")}>
                          {n || "·"}
                        </td>
                      );
                    })}
                    <td className={cn("num px-1.5 text-right", list.length > 25 ? "text-bad" : "")}>{list.length}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Fieldset>
      <Fieldset legend="Memory">
        <TextField aria-label="Search lessons" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search lessons" className="w-64" />
        {shown.map((l) => (
          <LessonRow key={l.id} lesson={l} onSave={(note) => edit.mutate({ id: l.id, note })} onDelete={() => del.mutate(l.id)} />
        ))}
      </Fieldset>
    </>
  );
}

const HEALTH_TONE: Record<string, StatusTone> = { ok: "ok", warn: "warn", fail: "bad", skip: "off" };

function Health() {
  const doctor = useDoctor().data ?? [];
  const report = doctor.map((d) => `[${d.status}] ${d.name}: ${d.detail}${d.fix ? ` (fix: ${d.fix})` : ""}`).join("\n");
  return (
    <>
      <H>Health</H>
      <div className="flex justify-end">
        <Button onClick={() => void navigator.clipboard?.writeText(report)}>Copy report</Button>
      </div>
      <div className="flex flex-col">
        {doctor.map((d) => (
          <div key={d.name} className="grid items-start gap-2 border-b border-line-soft py-1" style={{ gridTemplateColumns: "14px 170px minmax(0,1fr)" }}>
            <Dot tone={HEALTH_TONE[d.status] ?? "muted"} className="mt-1" />
            <span>{d.name}</span>
            <span className="selectable">
              {d.detail}
              {d.fix && <span className="block text-muted">Fix: {d.fix}</span>}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

export const SHORTCUTS: [string, string][] = [
  ["Ctrl+K", "Command box (> messages the Director)"],
  ["Ctrl+1…7", "Go to page"],
  ["Ctrl+J", "Show or hide the output panel"],
  ["Ctrl+.", "Show the activity feed"],
  ["Ctrl+Shift+P", "Pause / resume all"],
  ["Ctrl+Shift+D", "Toggle dry run"],
  ["Ctrl+,", "Settings"],
  ["Review: A R E C", "Approve, reject, edit, re-cut"],
  ["Review: Space ←/→", "Play, previous / next clip"],
  ["Review: Shift+A", "Approve all at or above the threshold"],
  ["Edit: Space I O S Del", "Play, mark in, mark out, split, delete range"],
  ["Edit: Ctrl+Z N T", "Undo, new note, take over / hand back"],
  ["Library: /", "Search"],
];

function Keys() {
  return (
    <>
      <H>Keyboard shortcuts</H>
      <div className="grid gap-x-4 gap-y-1.5" style={{ gridTemplateColumns: "180px minmax(0,1fr)" }}>
        {SHORTCUTS.map(([k, v]) => (
          <div key={k} className="contents">
            <span>
              <Kbd>{k}</Kbd>
            </span>
            <span>{v}</span>
          </div>
        ))}
      </div>
    </>
  );
}

/** A real Settings dialog: section list on the left; OK / Cancel / Apply (UI.md §3.8). */
export function SettingsDialog({ onSwitchOff }: { onSwitchOff: (t: SwitchTarget) => void }) {
  const open = useUi((s) => s.settingsOpen);
  const section = useUi((s) => s.settingsSection);
  const openSettings = useUi((s) => s.openSettings);
  const close = useUi((s) => s.closeSettings);
  const data = useSettings();
  const patch = usePatchSettings();
  const [draft, setDraft] = useState<Draft>({});
  const s = data.data?.settings ?? {};
  const ctx: Ctx = { s, draft, set: (k, v) => setDraft((d) => ({ ...d, [k]: v })) };
  const dirty = Object.keys(draft).length > 0;
  const apply = () => {
    if (dirty) patch.mutate(draft);
    setDraft({});
  };
  const sec = SECTIONS.find((x) => x.id === section) ? section : "markets";

  return (
    <D.Root open={open} onOpenChange={(o) => (o ? openSettings() : (close(), setDraft({})))}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <D.Content onOpenAutoFocus={(e) => e.preventDefault()} className="fixed top-1/2 left-1/2 z-50 flex h-[min(640px,calc(100vh-48px))] w-[min(880px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius)] border border-line bg-chrome shadow-[0_16px_48px_rgba(0,0,0,0.35)] outline-none">
          <div className="flex h-8 shrink-0 items-center pl-3">
            <D.Title className="text-[12px] font-normal">Settings</D.Title>
            <D.Description className="sr-only">Clipper settings</D.Description>
            <span className="flex-1" />
            <D.Close aria-label="Close" className="flex h-8 w-[46px] items-center justify-center hover:bg-bad hover:text-white">
              <Dismiss16Regular />
            </D.Close>
          </div>
          <div className="flex min-h-0 flex-1">
            <nav aria-label="Settings sections" className="flex w-[200px] shrink-0 flex-col gap-0.5 overflow-auto px-1.5 py-1">
              {SECTIONS.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  aria-current={sec === x.id ? "page" : undefined}
                  onClick={() => openSettings(x.id)}
                  className={cn("h-[30px] rounded-[var(--radius)] px-2.5 text-left", sec === x.id ? "bg-panel-2" : "hover:bg-[color-mix(in_srgb,var(--fg)_6%,transparent)]")}
                >
                  {x.label}
                </button>
              ))}
            </nav>
            <div className="flex min-w-0 flex-1 flex-col gap-3 overflow-auto py-1 pr-4 pl-3 [&>*]:shrink-0">
              {sec === "general" && <General ctx={ctx} />}
              {sec === "markets" && <Markets ctx={ctx} onSwitchOff={onSwitchOff} />}
              {sec === "automation" && <Automation ctx={ctx} />}
              {sec === "usage" && <Usage ctx={ctx} />}
              {sec === "agents" && <Agents ctx={ctx} />}
              {sec === "browser" && <Browser ctx={ctx} secrets={data.data?.secrets_present ?? {}} pairing={data.data?.pairing_token ?? null} />}
              {sec === "discord" && <Discord ctx={ctx} secrets={data.data?.secrets_present ?? {}} />}
              {sec === "media" && <Media ctx={ctx} />}
              {sec === "storage" && <Storage ctx={ctx} />}
              {sec === "tools" && <Tools />}
              {sec === "health" && <Health />}
              {sec === "keys" && <Keys />}
            </div>
          </div>
          <div className="flex shrink-0 items-center justify-end gap-2 border-t border-line bg-bg px-4 py-3">
            {dirty && <span className="mr-auto text-muted">{Object.keys(draft).length} unsaved change{Object.keys(draft).length === 1 ? "" : "s"}</span>}
            <Button
              variant="primary"
              className="min-w-[90px]"
              onClick={() => {
                apply();
                close();
              }}
            >
              OK
            </Button>
            <Button className="min-w-[90px]" onClick={() => (setDraft({}), close())}>
              Cancel
            </Button>
            <Button className="min-w-[90px]" disabled={!dirty} onClick={apply}>
              Apply
            </Button>
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
