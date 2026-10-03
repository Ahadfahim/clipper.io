import { useNavigate, useSearch } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useControl, usePatchSettings, useSaveSecret, useSwitch, useTestRecipe } from "@/api/actions";
import { useDoctor, useSettings, useStatus, useSwitches, qk } from "@/api/queries";
import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Check, Field, Fieldset, Select, TextField } from "@/components/ui/fields";
import { Dot, type StatusTone } from "@/components/ui/status";
import { cn } from "@/lib/cn";
import { MARKET_LABEL, MARKET_ORDER, PLATFORM_LABEL, PLATFORM_ORDER } from "@/lib/platforms";
import { openProfile } from "@/lib/tauri";

const STEPS = [
  "Welcome and data folder",
  "Claude login",
  "GPU and media tools",
  "Chrome and the Companion extension",
  "First account",
  "Discord",
  "Marketplaces and socials",
  "Done",
];

const TONE: Record<string, StatusTone> = { ok: "ok", warn: "warn", fail: "bad", skip: "off" };

function Checks({ names }: { names: string[] }) {
  const doctor = useDoctor();
  const qc = useQueryClient();
  const items = (doctor.data ?? []).filter((d) => names.includes(d.name));
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((d) => (
        <div key={d.name} className="grid items-start gap-2" style={{ gridTemplateColumns: "14px 150px minmax(0,1fr)" }}>
          <Dot tone={TONE[d.status] ?? "muted"} className="mt-1" />
          <span>{d.name}</span>
          <span>
            {d.detail}
            {d.fix && <span className="block text-muted">Fix: {d.fix}</span>}
          </span>
        </div>
      ))}
      {items.length === 0 && <span className="text-muted">Checking…</span>}
      <div>
        <Button size="sm" onClick={() => void qc.invalidateQueries({ queryKey: qk.doctor })}>
          Check again
        </Button>
      </div>
    </div>
  );
}

function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <h1 className="text-[16px] font-semibold">{title}</h1>
      {children}
    </div>
  );
}

/** First-run setup (UI.md §4). Finishes on Home with dry run on. */
export function SetupWizard() {
  const search = useSearch({ from: "/setup" });
  const navigate = useNavigate();
  const step = Math.max(0, Math.min(STEPS.length - 1, (search.step ?? 1) - 1));
  const go = (n: number) => void navigate({ to: "/setup", search: { step: n + 1 }, replace: true });
  const settings = useSettings().data;
  const status = useStatus().data;
  const switches = useSwitches().data;
  const patch = usePatchSettings();
  const saveSecret = useSaveSecret();
  const sw = useSwitch();
  const control = useControl();
  const test = useTestRecipe();
  const qc = useQueryClient();
  const [dataDir, setDataDir] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [acct, setAcct] = useState({ platform: "youtube" as "youtube" | "tiktok" | "instagram" | "x", handle: "", profile: "main", tags: "" });
  const [acctAdded, setAcctAdded] = useState(false);
  const [bot, setBot] = useState("");
  const [guild, setGuild] = useState("");
  const paths = (settings?.settings["paths"] ?? {}) as Record<string, unknown>;

  const body = [
    <Step key="0" title="Welcome to Clipper">
      <p className="m-0">
        Clipper finds clipping campaigns on Vyro and Whop, cuts and captions clips with Claude, asks you to approve them, posts them through your own Chrome
        profiles and submits the links. Nothing is posted without your approval.
      </p>
      <Field label="Data folder" hint="Videos, renders, the database and backups live here. Pick a drive with room (100 GB+).">
        {(id) => <TextField id={id} value={dataDir ?? String(paths["data_dir"] ?? "D:\\Clipper.io\\data")} onChange={(e) => setDataDir(e.target.value)} className="w-[420px]" />}
      </Field>
    </Step>,
    <Step key="1" title="Claude login">
      <p className="m-0">
        Agents run on your Claude plan through the <span className="num">claude</span> command-line login. No API key is used, and Clipper removes API keys from
        agent processes.
      </p>
      <Checks names={["claude-login", "claude-billing-env"]} />
      <p className="m-0 text-muted">
        Not logged in? Open a terminal, run <span className="num">claude</span>, and sign in with your Claude account. Then press Check again.
      </p>
    </Step>,
    <Step key="2" title="GPU and media tools">
      <Checks names={["gpu-env", "ffmpeg", "yt-dlp"]} />
      <p className="m-0 text-muted">
        The RTX 5080 needs PyTorch cu128 wheels; <span className="num">just gpu-setup</span> builds that environment.
      </p>
    </Step>,
    <Step key="3" title="Chrome and the Companion extension">
      <ol className="m-0 flex flex-col gap-1 pl-5">
        <li>Install the Companion extension in the Chrome profile you'll post from (Load unpacked: apps/extension/dist).</li>
        <li>Create a pairing token below and paste it into the extension's options.</li>
      </ol>
      <div className="flex items-center gap-2">
        <TextField readOnly aria-label="Pairing token" value={token ?? "not created yet"} className="num w-80" />
        <Button
          onClick={() => {
            const t = Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, "0")).join("");
            saveSecret.mutate({ name: "extension_pairing_token", value: t });
            setToken(t);
          }}
        >
          Create token
        </Button>
        <Button disabled={!token} onClick={() => token && void navigator.clipboard?.writeText(token)}>
          Copy
        </Button>
      </div>
      <span className="flex items-center gap-1.5">
        <Dot tone={status?.extension_profiles.length ? "ok" : "warn"} />
        {status?.extension_profiles.length ? `Connected ✓ (${status.extension_profiles.join(", ")})` : "Waiting for the extension to connect…"}
      </span>
    </Step>,
    <Step key="4" title="First account">
      <p className="m-0">Log in to the account inside the Chrome profile first. New accounts start a warm-up: 1 post a day in week 1, 2 in week 2.</p>
      <div className="flex flex-wrap gap-3">
        <Field label="Platform">
          {(id) => (
            <Select id={id} value={acct.platform} onChange={(e) => setAcct({ ...acct, platform: e.target.value as typeof acct.platform })}>
              {PLATFORM_ORDER.filter((p) => p !== "x").map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABEL[p]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Handle">{(id) => <TextField id={id} value={acct.handle} onChange={(e) => setAcct({ ...acct, handle: e.target.value })} placeholder="@yourhandle" />}</Field>
        <Field label="Chrome profile">{(id) => <TextField id={id} value={acct.profile} onChange={(e) => setAcct({ ...acct, profile: e.target.value })} className="w-28" />}</Field>
        <Field label="Niche tags">{(id) => <TextField id={id} value={acct.tags} onChange={(e) => setAcct({ ...acct, tags: e.target.value })} placeholder="podcast, gaming" />}</Field>
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={() => void openProfile(acct.profile)}>Open Chrome window</Button>
        <Button
          variant="primary"
          disabled={!acct.handle.startsWith("@") || acctAdded}
          onClick={() =>
            void unwrap(
              api.POST("/api/publishing/accounts", {
                body: { platform: acct.platform, handle: acct.handle, chrome_profile: acct.profile, niche_tags: acct.tags.split(",").map((t) => t.trim()).filter(Boolean), new_account: true, daily_cap: null },
              }),
            ).then(() => {
              setAcctAdded(true);
              void qc.invalidateQueries({ queryKey: qk.accounts });
            })
          }
        >
          {acctAdded ? "Added ✓" : "Add account"}
        </Button>
      </div>
    </Step>,
    <Step key="5" title="Discord">
      <p className="m-0">Clipper posts campaign cards and review batches to your server. On first start the bot creates #campaigns, #clip-review, #published, #alerts and #control.</p>
      <Field label="Bot token" hint="Stored in Windows Credential Manager.">
        {(id) => <TextField id={id} type="password" value={bot} onChange={(e) => setBot(e.target.value)} className="w-96" />}
      </Field>
      <Field label="Server id">{(id) => <TextField id={id} value={guild} onChange={(e) => setGuild(e.target.value)} className="w-64" />}</Field>
      <div>
        <Button
          variant="primary"
          disabled={!bot && !guild}
          onClick={() => {
            if (bot) saveSecret.mutate({ name: "discord_bot_token", value: bot });
            if (guild) patch.mutate({ "discord.guild_id": guild, "discord.enabled": true });
            setBot("");
          }}
        >
          Save
        </Button>
      </div>
    </Step>,
    <Step key="6" title="Marketplaces and socials">
      <Fieldset legend="Where should Clipper find campaigns?">
        {MARKET_ORDER.map((m) => {
          const s = switches?.marketplaces[m];
          return (
            <div key={m} className="flex items-center gap-3">
              <Check checked={Boolean(s?.enabled)} onChange={(on) => sw.mutate({ level: "marketplace", name: m, enabled: on, on_active: "pause", on_scheduled: "keep" })} label={MARKET_LABEL[m] ?? m} className="w-24" />
              <span className={cn("flex items-center gap-1.5", s?.session_ok ? "text-ok" : "text-muted")}>
                <Dot tone={s?.session_ok ? "ok" : "warn"} /> {s?.session_ok ? "Logged in" : "Log in inside the Chrome profile"}
              </span>
              <Button size="sm" onClick={() => void openProfile("main")}>
                Log in
              </Button>
              <Button size="sm" onClick={() => test.mutate(`${m}.list_campaigns`)}>
                Test reading campaigns
              </Button>
            </div>
          );
        })}
      </Fieldset>
      <Fieldset legend="Where should clips be posted?">
        <div className="flex flex-wrap gap-4">
          {PLATFORM_ORDER.map((p) => (
            <Check key={p} checked={Boolean(switches?.socials[p]?.enabled)} disabled={p === "x"} onChange={(on) => sw.mutate({ level: "social", name: p, enabled: on, on_scheduled: "keep" })} label={`${PLATFORM_LABEL[p]}${p === "x" ? " (later)" : ""}`} />
          ))}
        </div>
      </Fieldset>
    </Step>,
    <Step key="7" title="You're set">
      <p className="m-0">
        Clipper starts in <strong>dry run</strong>: it finds campaigns, makes clips and asks for reviews, but uploads and submissions are simulated until you untick
        Dry run in the toolbar.
      </p>
    </Step>,
  ];

  const finish = () => {
    if (dataDir) patch.mutate({ "paths.data_dir": dataDir });
    control.mutate({ key: "dry_run", value: true });
    void navigate({ to: "/" });
  };

  return (
    <div className="flex h-full items-center justify-center bg-bg p-4">
      <div className="flex h-[min(600px,100%)] w-[min(880px,100%)] flex-col rounded-[var(--radius)] border border-line bg-chrome shadow-[0_16px_48px_rgba(0,0,0,0.25)]">
        <div className="flex h-8 shrink-0 items-center px-3">Clipper setup</div>
        <div className="flex min-h-0 flex-1">
          <ol className="m-0 flex w-[240px] shrink-0 list-none flex-col gap-0.5 p-1.5" aria-label="Steps">
            {STEPS.map((s, i) => (
              <li key={s}>
                <button
                  type="button"
                  aria-current={i === step ? "step" : undefined}
                  onClick={() => go(i)}
                  className={cn("flex h-[30px] w-full items-center gap-2 rounded-[var(--radius)] px-2 text-left", i === step ? "bg-panel-2" : "hover:bg-[color-mix(in_srgb,var(--fg)_6%,transparent)]", i > step && "text-muted")}
                >
                  <span className={cn("num flex size-5 items-center justify-center rounded-full border text-[11px]", i < step ? "border-ok text-ok" : i === step ? "border-accent text-accent" : "border-line")}>
                    {i < step ? "✓" : i + 1}
                  </span>
                  {s}
                </button>
              </li>
            ))}
          </ol>
          <div className="min-w-0 flex-1 overflow-auto bg-panel px-5 py-4">{body[step]}</div>
        </div>
        <div className="flex shrink-0 justify-end gap-2 border-t border-line bg-bg px-4 py-3">
          <span className="mr-auto self-center text-muted">
            Step {step + 1} of {STEPS.length}
          </span>
          <Button className="min-w-[90px]" disabled={step === 0} onClick={() => go(step - 1)}>
            Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button variant="primary" className="min-w-[90px]" onClick={() => go(step + 1)}>
              Next
            </Button>
          ) : (
            <Button variant="primary" className="min-w-[90px]" onClick={finish}>
              Open Clipper
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
