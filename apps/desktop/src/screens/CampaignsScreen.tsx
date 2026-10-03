import { Dismiss16Regular, LinkSquare16Regular } from "@fluentui/react-icons";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useManualCampaign, usePauseCampaign, useSaveSpec, useSkipCampaign, useTakeCampaign } from "@/api/actions";
import { useCampaign, useCampaigns, useClips, useManifest, useSwitches } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DataGrid, type ColumnDef } from "@/components/ui/data-grid";
import { Dialog } from "@/components/ui/dialog";
import { Check, Field, Fieldset, Radio, Select, TextArea, TextField } from "@/components/ui/fields";
import { Badge, Empty, PaneHeader, PropertyGrid, TitleRow, Toolbar, ToolbarSep } from "@/components/ui/misc";
import { StatusPill } from "@/components/ui/status";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { MarketBadge, PlatformTag, Score } from "@/components/domain/badges";
import { BudgetBurnBar, RunsOut } from "@/components/domain/meters";
import { ClipCard } from "@/components/domain/clip";
import { UntrustedBanner } from "@/components/domain/switches";
import { cn } from "@/lib/cn";
import { clock, compact, cpm, day, duration, money } from "@/lib/format";
import { MARKET_LABEL, PLATFORM_LABEL, PLATFORM_ORDER } from "@/lib/platforms";
import { openUrl } from "@/lib/tauri";
import { useUi } from "@/state/ui";

const NONE: never[] = [];

type Tab = "suggested" | "active" | "ended" | "skipped";
const TAB_STATUSES: Record<Tab, string[]> = {
  suggested: ["suggested", "needs_user"],
  active: ["active", "paused"],
  ended: ["ended"],
  skipped: ["skipped"],
};

function Heat({ values }: { values: number[] }) {
  if (!values.length) return <span className="text-muted">—</span>;
  const max = Math.max(...values, 0.01);
  return (
    <span className="inline-flex h-4 items-end gap-px" role="img" aria-label="Replay heatmap">
      {values.map((v, i) => (
        <span key={i} className="w-[3px] bg-series-1" style={{ height: `${Math.max(8, (v / max) * 100)}%`, opacity: 0.35 + 0.65 * (v / max) }} />
      ))}
    </span>
  );
}

function SpecForm({ id, spec }: { id: number; spec: Schemas["ClipSpec"] }) {
  const [draft, setDraft] = useState<Schemas["ClipSpec"]>(spec);
  const save = useSaveSpec();
  const set = <K extends keyof Schemas["ClipSpec"]>(k: K, v: Schemas["ClipSpec"][K]) => setDraft((d) => ({ ...d, [k]: v }));
  const list = (v: string) =>
    v
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  const dirty = JSON.stringify(draft) !== JSON.stringify(spec);
  return (
    <form
      className="flex flex-col gap-3 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate({ id, spec: draft });
      }}
    >
      <p className="m-0 text-muted">Saving resumes the Campaign agent with “spec updated”.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Minimum length (s)">{(fid) => <TextField id={fid} type="number" min={5} value={draft.duration_min_s ?? 15} onChange={(e) => set("duration_min_s", Number(e.target.value))} />}</Field>
        <Field label="Maximum length (s)">{(fid) => <TextField id={fid} type="number" min={5} value={draft.duration_max_s ?? 60} onChange={(e) => set("duration_max_s", Number(e.target.value))} />}</Field>
      </div>
      <Field label="Required text or tags" hint="Comma separated, e.g. @MrBeast">
        {(fid) => <TextField id={fid} value={[...(draft.required_tags ?? []), ...(draft.required_text ?? [])].join(", ")} onChange={(e) => set("required_tags", list(e.target.value))} />}
      </Field>
      <Field label="Banned" hint="Comma separated">
        {(fid) => <TextField id={fid} value={(draft.banned ?? []).join(", ")} onChange={(e) => set("banned", list(e.target.value))} />}
      </Field>
      <Fieldset legend="Platforms">
        <div className="flex flex-wrap gap-3">
          {PLATFORM_ORDER.map((p) => (
            <Check
              key={p}
              checked={(draft.platforms ?? []).includes(p)}
              onChange={(on) => set("platforms", on ? [...(draft.platforms ?? []), p] : (draft.platforms ?? []).filter((x) => x !== p))}
              label={PLATFORM_LABEL[p]}
            />
          ))}
        </div>
      </Fieldset>
      <Fieldset legend="Deliverable">
        <div className="flex gap-4">
          <Radio name="deliverable" checked={draft.deliverable === "link"} onChange={() => set("deliverable", "link")} label="Post link" />
          <Radio name="deliverable" checked={draft.deliverable === "upload"} onChange={() => set("deliverable", "upload")} label="Upload file" />
        </div>
      </Fieldset>
      <div className="flex flex-wrap gap-3">
        <Check checked={Boolean(draft.allow_music)} onChange={(v) => set("allow_music", v)} label="Music allowed" />
        <Check checked={Boolean(draft.profanity_mask)} onChange={(v) => set("profanity_mask", v)} label="Mask profanity" />
        <Check checked={Boolean(draft.allow_cross_submit)} onChange={(v) => set("allow_cross_submit", v)} label="Cross-submit allowed" />
      </div>
      <Field label="Notes">{(fid) => <TextArea id={fid} rows={3} value={draft.notes ?? ""} onChange={(e) => set("notes", e.target.value)} />}</Field>
      {(draft.unclear ?? []).length > 0 && (
        <div className="text-warn">
          Unclear in the brief: <span className="text-fg">{(draft.unclear ?? []).join("; ")}</span>
        </div>
      )}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!dirty}>
          Save spec
        </Button>
        <Button disabled={!dirty} onClick={() => setDraft(spec)}>
          Revert
        </Button>
      </div>
    </form>
  );
}

function Drawer({ id, onClose }: { id: number; onClose: () => void }) {
  const d = useCampaign(id).data;
  const clips = useClips().data ?? [];
  const manifest = useManifest().data;
  const take = useTakeCampaign();
  const skip = useSkipCampaign();
  const pause = usePauseCampaign();
  const search = useSearch({ from: "/shell/campaigns" });
  const navigate = useNavigate();
  const tab = search.detail ?? "overview";
  const setTab = (t: string) => void navigate({ to: "/campaigns", search: { ...search, detail: t }, replace: true });
  if (!d) return <aside className="w-[560px] max-w-[60%] shrink-0 border-l border-line bg-panel" aria-label="Campaign detail" />;
  const c = d.campaign;
  const payout = d.payout as Record<string, unknown>;
  const mine = clips.filter((x) => x.campaign_id === c.id);
  return (
    <aside aria-label="Campaign detail" className="flex w-[560px] max-w-[60%] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line px-3">
        <MarketBadge market={c.marketplace} />
        <span className="truncate-1 flex-1 font-semibold">{c.title}</span>
        <StatusPill status={c.status} />
        <button type="button" aria-label="Close detail" onClick={onClose} className="flex size-7 items-center justify-center rounded-[3px] hover:bg-panel-2">
          <Dismiss16Regular />
        </button>
      </div>
      <Tabs
        value={tab}
        onValueChange={setTab}
        className="min-h-0 flex-1"
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "brief", label: "Brief" },
          { value: "spec", label: "Spec" },
          { value: "sources", label: `Sources (${d.sources.length})` },
          { value: "clips", label: `Clips (${mine.length})` },
          { value: "timeline", label: "Timeline" },
          { value: "money", label: "Money" },
        ]}
      >
        <TabPanel value="overview" className="overflow-auto">
          <div className="flex flex-wrap gap-1.5 p-3">
            {(c.status === "suggested" || c.status === "needs_user") && (
              <>
                <Button variant="primary" onClick={() => take.mutate(c.id)}>
                  Take
                </Button>
                <Button onClick={() => skip.mutate(c.id)}>Skip</Button>
              </>
            )}
            {c.status === "active" && <Button onClick={() => pause.mutate(c.id)}>Pause</Button>}
            {c.status === "paused" && (
              <Button variant="primary" onClick={() => take.mutate(c.id)}>
                Resume
              </Button>
            )}
            {d.url && (
              <Button icon={<LinkSquare16Regular />} onClick={() => void openUrl(d.url ?? "")}>
                Open in browser
              </Button>
            )}
          </div>
          <PaneHeader className="border-t">Why this score</PaneHeader>
          <div className="selectable flex items-start gap-3 p-3">
            <span className="text-[16px]">
              <Score value={c.score} />
            </span>
            <span>{d.score_reason ?? "Not scored yet."}</span>
          </div>
          <PaneHeader className="border-t">Payout terms</PaneHeader>
          <PropertyGrid
            labelWidth={140}
            rows={[
              ["CPM", <span key="c" className="num">{cpm(c.cpm)}</span>],
              ["Cap per post", <span key="cap" className="num">{money(payout["cap_per_post"] as number | null)}</span>],
              ["Minimum views", <span key="m" className="num">{payout["min_views_to_pay"] ? compact(payout["min_views_to_pay"] as number) : "none"}</span>],
              ["Tracking window", `${String(payout["tracking_window_days"] ?? "—")} days`],
              ["Deliverable", String(payout["deliverable"] ?? "link") === "upload" ? "Upload the file" : "Submit the post link"],
              ["Budget", <BudgetBurnBar key="b" left={c.budget_left} total={c.budget_total} runsOut={c.runs_out_at} deadline={c.deadline} />],
              ["Runs out", <RunsOut key="r" at={c.runs_out_at} deadline={c.deadline} />],
              ["Deadline", day(c.deadline)],
              ["Matching accounts", c.matching_accounts.join(", ") || "none"],
            ]}
          />
          <PaneHeader className="border-t">Socials for this campaign</PaneHeader>
          <div className="flex flex-wrap gap-3 p-3">
            {PLATFORM_ORDER.map((p) => (
              <Check key={p} checked={c.platforms.includes(p)} disabled label={PLATFORM_LABEL[p]} title="Change on the Spec tab" />
            ))}
          </div>
        </TabPanel>
        <TabPanel value="brief" className="flex flex-col gap-2 overflow-auto p-3">
          <UntrustedBanner />
          {d.rules_raw ? (
            <pre className="selectable m-0 rounded-[var(--radius)] border border-line bg-bg p-2.5 font-ui whitespace-pre-wrap">{d.rules_raw}</pre>
          ) : (
            <Empty>The brief hasn't been fetched yet.</Empty>
          )}
        </TabPanel>
        <TabPanel value="spec" className="overflow-auto">
          {d.spec ? <SpecForm key={c.id} id={c.id} spec={d.spec} /> : <Empty>No spec yet: the brief reader runs after you take the campaign.</Empty>}
        </TabPanel>
        <TabPanel value="sources" className="overflow-auto">
          {d.sources.length === 0 && <Empty>No sources yet.</Empty>}
          {d.sources.map((s) => (
            <div key={s.id} className="flex flex-col gap-1 border-b border-line-soft px-3 py-2">
              <span className="flex items-center gap-2">
                <span className="truncate-1 flex-1">{s.title ?? s.url}</span>
                <StatusPill status={s.status} />
              </span>
              <span className="flex items-center gap-3 text-muted">
                <span className="num">{duration(s.duration)}</span>
                <Heat values={s.heatmap} />
                <span className="truncate-1 num text-[11px]">{s.url}</span>
              </span>
            </div>
          ))}
        </TabPanel>
        <TabPanel value="clips" className="overflow-auto p-3">
          {mine.length === 0 ? (
            <Empty>No clips yet.</Empty>
          ) : (
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))" }}>
              {mine.map((x) => (
                <ClipCard key={x.id} clip={x} thumb={fileUrl(x.thumb_url, manifest)} onOpen={() => void navigate({ to: "/library/$clipId", params: { clipId: String(x.id) } })} />
              ))}
            </div>
          )}
        </TabPanel>
        <TabPanel value="timeline" className="overflow-auto">
          {d.timeline.length === 0 && <Empty>No events yet.</Empty>}
          {d.timeline.map((t, i) => (
            <div key={i} className="flex gap-3 border-b border-line-soft px-3 py-1">
              <span className="num text-muted">{clock(t.ts, false)}</span>
              <span className="w-32 text-muted">{t.type}</span>
              <span className="selectable flex-1">{t.text}</span>
            </div>
          ))}
        </TabPanel>
        <TabPanel value="money" className="overflow-auto">
          <PropertyGrid
            rows={[
              ["Earned", <span key="e" className="num">{money(d.money.earnings, { cents: true })}</span>],
              ["Views", <span key="v" className="num">{compact(d.money.views)}</span>],
              ["Posts", <span key="p" className="num">{d.money.posts}</span>],
              ...Object.entries(d.money.submissions).map(([k, v]): [string, React.ReactNode] => [`Submissions ${k}`, <span key={k} className="num">{v}</span>]),
            ]}
          />
        </TabPanel>
      </Tabs>
    </aside>
  );
}

function PasteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [url, setUrl] = useState("");
  const [market, setMarket] = useState<"vyro" | "whop">("vyro");
  const add = useManualCampaign();
  const guess = url.includes("whop.com") ? "whop" : url.includes("vyro") ? "vyro" : market;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Paste campaign URL"
      width={480}
      footer={
        <>
          <Button
            variant="primary"
            disabled={!/^https?:\/\//.test(url)}
            onClick={() => {
              add.mutate({ url, marketplace: guess, title: null });
              setUrl("");
              onClose();
            }}
          >
            Add campaign
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Campaign URL" hint="Scout reads the page in your Chrome profile and scores it. The page is treated as untrusted.">
          {(fid) => <TextField id={fid} autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://whop.com/…" />}
        </Field>
        <Field label="Marketplace">
          {(fid) => (
            <Select id={fid} value={guess} onChange={(e) => setMarket(e.target.value as "vyro" | "whop")}>
              <option value="vyro">Vyro</option>
              <option value="whop">Whop</option>
            </Select>
          )}
        </Field>
      </div>
    </Dialog>
  );
}

/** Campaigns grid with Suggested/Active/Ended/Skipped tabs, marketplace and type filters, detail drawer (UI.md §3.3). */
export function CampaignsScreen() {
  const search = useSearch({ from: "/shell/campaigns" });
  const navigate = useNavigate();
  const rows = useCampaigns().data ?? NONE;
  const switches = useSwitches().data;
  const ui = useUi();
  const take = useTakeCampaign();
  const skip = useSkipCampaign();
  const pause = usePauseCampaign();
  const [type, setType] = useState<"all" | "clipping" | "ugc">("all");
  const tab: Tab = search.tab ?? (search.open ? (Object.entries(TAB_STATUSES).find(([, s]) => s.includes(rows.find((r) => r.id === search.open)?.status ?? ""))?.[0] as Tab | undefined) ?? ui.campaignTab : ui.campaignTab);
  const market = search.market ?? ui.campaignMarket;

  const counts = useMemo(() => {
    const out: Record<Tab, number> = { suggested: 0, active: 0, ended: 0, skipped: 0 };
    for (const r of rows) for (const [t, s] of Object.entries(TAB_STATUSES)) if (s.includes(r.status)) out[t as Tab] += 1;
    return out;
  }, [rows]);

  const shown = rows.filter(
    (r) => TAB_STATUSES[tab].includes(r.status) && (market === "all" || r.marketplace === market) && (type === "all" || r.content_type === type),
  );
  const enabledSocials = new Set(Object.entries(switches?.socials ?? {}).filter(([, s]) => s.enabled).map(([k]) => k));
  const offReason = (r: Schemas["CampaignRow"]) =>
    r.disabled_reason ??
    (switches?.marketplaces[r.marketplace]?.enabled === false
      ? `${MARKET_LABEL[r.marketplace]} is off`
      : switches && !r.platforms.some((p) => enabledSocials.has(p))
        ? "No enabled socials"
        : null);

  const setSearch = (patch: Record<string, unknown>) => void navigate({ to: "/campaigns", search: { ...search, ...patch } });

  const columns: ColumnDef<Schemas["CampaignRow"], unknown>[] = [
    { id: "market", header: "Source", accessorKey: "marketplace", size: 76, cell: (c) => <MarketBadge market={c.row.original.marketplace} /> },
    { id: "score", header: "Score", accessorKey: "score", size: 56, meta: { align: "right" }, cell: (c) => <Score value={c.row.original.score} /> },
    {
      id: "title",
      header: "Campaign",
      accessorKey: "title",
      size: 200,
      meta: { flex: 2 },
      cell: (c) => {
        const r = c.row.original;
        const off = offReason(r);
        return (
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="truncate-1">{r.title}</span>
            {r.content_type === "ugc" && <Badge>UGC</Badge>}
            {off && <span className="truncate-1 text-[11px] text-muted">· {off}</span>}
          </span>
        );
      },
    },
    { id: "cpm", header: "CPM", accessorKey: "cpm", size: 64, meta: { align: "right", mono: true }, cell: (c) => cpm(c.row.original.cpm) },
    {
      id: "budget",
      header: "Budget left",
      accessorKey: "budget_left",
      size: 150,
      cell: (c) => <BudgetBurnBar left={c.row.original.budget_left} total={c.row.original.budget_total} runsOut={c.row.original.runs_out_at} deadline={c.row.original.deadline} />,
    },
    { id: "runs", header: "Runs out", accessorKey: "runs_out_at", size: 80, cell: (c) => <RunsOut at={c.row.original.runs_out_at} deadline={c.row.original.deadline} /> },
    { id: "deadline", header: "Deadline", accessorKey: "deadline", size: 72, cell: (c) => day(c.row.original.deadline) },
    {
      id: "accounts",
      header: "Accounts",
      accessorFn: (r) => r.matching_accounts.join(", "),
      size: 150,
      meta: { flex: 1 },
      cell: (c) => <span className="text-muted">{c.row.original.matching_accounts.join(", ") || "none match"}</span>,
    },
    {
      id: "platforms",
      header: "Socials",
      accessorFn: (r) => r.platforms.join(","),
      size: 96,
      cell: (c) => (
        <span className="flex gap-0.5">
          {c.row.original.platforms.map((p) => (
            <PlatformTag key={p} platform={p} on={enabledSocials.size === 0 || enabledSocials.has(p)} />
          ))}
        </span>
      ),
    },
    { id: "status", header: "Status", accessorKey: "status", size: 96, cell: (c) => <StatusPill status={c.row.original.status} /> },
    { id: "clips", header: "Clips", accessorKey: "clips_posted", size: 52, meta: { align: "right", mono: true } },
    { id: "earned", header: "Earned", accessorKey: "earned", size: 76, meta: { align: "right", mono: true }, cell: (c) => money(c.row.original.earned, { cents: true }) },
  ];

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="px-4 pt-3 pb-2">
          <TitleRow
            title="Campaigns"
            sub={`${counts.active} active · ${counts.suggested} suggested`}
            actions={
              <Button icon={<LinkSquare16Regular />} onClick={() => setSearch({ paste: 1 })}>
                Paste campaign URL
              </Button>
            }
          />
        </div>
        <Toolbar label="Campaign filters" className="border-t">
          <div role="tablist" aria-label="Campaign status" className="flex gap-0.5">
            {(Object.keys(TAB_STATUSES) as Tab[]).map((t) => (
              <button
                key={t}
                role="tab"
                type="button"
                aria-selected={tab === t}
                onClick={() => {
                  ui.setCampaignTab(t);
                  setSearch({ tab: t });
                }}
                className={cn("h-6 rounded-[var(--radius)] px-2.5", tab === t ? "bg-accent-soft text-fg" : "text-muted hover:bg-panel-2 hover:text-fg")}
              >
                {t[0]!.toUpperCase() + t.slice(1)} <span className="num">({counts[t]})</span>
              </button>
            ))}
          </div>
          <ToolbarSep />
          <div role="radiogroup" aria-label="Marketplace" className="flex gap-0.5">
            {(["all", "vyro", "whop"] as const).map((m) => (
              <button
                key={m}
                role="radio"
                type="button"
                aria-checked={market === m}
                onClick={() => {
                  ui.setCampaignMarket(m);
                  setSearch({ market: m === "all" ? undefined : m });
                }}
                className={cn("h-6 rounded-[var(--radius)] border px-2.5", market === m ? "border-accent bg-accent-soft" : "border-line hover:bg-panel-2")}
              >
                {m === "all" ? "All" : <MarketBadge market={m} />}
              </button>
            ))}
          </div>
          <ToolbarSep />
          <label htmlFor="ctype" className="px-1 text-muted">
            Type
          </label>
          <Select id="ctype" value={type} onChange={(e) => setType(e.target.value as typeof type)} className="h-6 w-28">
            <option value="all">All types</option>
            <option value="clipping">Clipping</option>
            <option value="ugc">UGC</option>
          </Select>
        </Toolbar>
        <div className="flex min-h-0 flex-1 flex-col p-3">
          <DataGrid
            label="Campaigns"
            data={shown}
            columns={columns}
            getRowId={(r) => String(r.id)}
            selected={search.open ? [String(search.open)] : []}
            onSelect={(ids) => setSearch({ open: ids[0] ? Number(ids[0]) : undefined })}
            onActivate={(r) => setSearch({ open: r.id })}
            rowClassName={(r) => (offReason(r) ? "text-muted" : undefined)}
            initialSort={[{ id: "score", desc: true }]}
            empty={tab === "suggested" ? "No suggestions. Scout runs every few minutes, or paste a campaign URL." : "Nothing here."}
            contextMenu={(r) => [
              { label: "Open", onSelect: () => setSearch({ open: r.id }) },
              { label: "Open brief", onSelect: () => setSearch({ open: r.id, detail: "brief" }) },
              { label: "Take", onSelect: () => take.mutate(r.id), disabled: r.status === "active" },
              { label: "Pause", onSelect: () => pause.mutate(r.id), disabled: r.status !== "active" },
              { label: "Skip", onSelect: () => skip.mutate(r.id), disabled: r.status === "skipped" || r.status === "ended" },
              { kind: "separator" },
              { label: "Copy title", onSelect: () => void navigator.clipboard?.writeText(r.title) },
            ]}
            className="flex-1"
          />
          <div className="pt-1.5 text-[11px] text-muted">Double-click or Enter opens the detail · right-click for actions · Ctrl+C copies rows</div>
        </div>
      </div>
      {search.open !== undefined && <Drawer id={search.open} onClose={() => setSearch({ open: undefined, detail: undefined })} />}
      <PasteDialog open={Boolean(search.paste)} onClose={() => setSearch({ paste: undefined })} />
    </div>
  );
}
