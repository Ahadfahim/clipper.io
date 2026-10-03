import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useCancelPost, useReschedule, useResumeAccount, useSwitch, useTestRecipe } from "@/api/actions";
import { useAccounts, useCalendar, useManifest, useRecipes } from "@/api/queries";
import { api, fileUrl, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DataGrid, type ColumnDef } from "@/components/ui/data-grid";
import { Dialog } from "@/components/ui/dialog";
import { Check, Field, Select, TextField } from "@/components/ui/fields";
import { Badge, TitleRow } from "@/components/ui/misc";
import { Dot, StatusPill } from "@/components/ui/status";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { AccountChip, PlatformTag } from "@/components/domain/badges";
import { CalendarLanes } from "@/components/domain/calendar";
import { cn } from "@/lib/cn";
import { dayTime, relative } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { PLATFORM_LABEL, PLATFORM_ORDER } from "@/lib/platforms";
import { useQueryClient } from "@tanstack/react-query";
import { qk, useStatus } from "@/api/queries";
import { useBrowserWindow } from "@/api/actions";

/** Show or hide Clipper's own Chrome for one profile (it runs hidden by default). */
function BrowserButton({ profile }: { profile: string }) {
  const state = useStatus().data?.browser.find((b) => b.name === profile);
  const browser = useBrowserWindow();
  const shown = Boolean(state?.visible);
  return (
    <Button size="sm" aria-pressed={shown} onClick={(e) => (e.stopPropagation(), browser.mutate({ profile, action: shown ? "hide" : "show" }))}>
      {shown ? "Hide browser" : "Show browser"}
    </Button>
  );
}

function Warmup({ week }: { week: number | null }) {
  const steps = ["Week 1", "Week 2", "Normal"];
  const at = week === null ? 2 : Math.min(2, Math.max(0, week - 1));
  return (
    <span className="flex items-center gap-0.5" aria-label={`Warm-up: ${steps[at]}`}>
      {steps.map((s, i) => (
        <span key={s} title={s} className={cn("h-1.5 w-5", i <= at ? (at === 2 ? "bg-ok" : "bg-warn-strong") : "bg-line")} />
      ))}
      <span className="ml-1.5 text-muted">{steps[at]}</span>
    </span>
  );
}

function AddAccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [platform, setPlatform] = useState<"youtube" | "tiktok" | "instagram" | "x">("youtube");
  const [handle, setHandle] = useState("");
  const [profile, setProfile] = useState("main");
  const [tags, setTags] = useState("");
  const [fresh, setFresh] = useState(true);
  const qc = useQueryClient();
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Add account"
      width={440}
      footer={
        <>
          <Button
            variant="primary"
            disabled={!handle.startsWith("@")}
            onClick={() => {
              void unwrap(
                api.POST("/api/publishing/accounts", {
                  body: { platform, handle, chrome_profile: profile, niche_tags: tags.split(",").map((t) => t.trim()).filter(Boolean), new_account: fresh, daily_cap: null },
                }),
              ).then(() => qc.invalidateQueries({ queryKey: qk.accounts }));
              onClose();
            }}
          >
            Add account
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Field label="Platform">
          {(id) => (
            <Select id={id} value={platform} onChange={(e) => setPlatform(e.target.value as typeof platform)}>
              {PLATFORM_ORDER.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABEL[p]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Handle">{(id) => <TextField id={id} value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@yourhandle" />}</Field>
        <Field label="Chrome profile" hint="Log in to the account inside this profile first.">
          {(id) => <TextField id={id} value={profile} onChange={(e) => setProfile(e.target.value)} />}
        </Field>
        <Field label="Niche tags" hint="Comma separated; used to match campaigns.">
          {(id) => <TextField id={id} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="podcast, gaming" />}
        </Field>
        <Check checked={fresh} onChange={setFresh} label="New account: start the warm-up schedule (1 post/day, then 2)" />
      </div>
    </Dialog>
  );
}

function Accounts({ accounts, focus }: { accounts: Schemas["AccountOut"][]; focus?: number }) {
  const sw = useSwitch();
  const resume = useResumeAccount();
  const [adding, setAdding] = useState(false);
  const columns: ColumnDef<Schemas["AccountOut"], unknown>[] = [
    { id: "account", header: "Account", accessorKey: "handle", size: 190, cell: (c) => <AccountChip platform={c.row.original.platform} handle={c.row.original.handle} status={c.row.original.status} enabled={c.row.original.enabled} /> },
    {
      id: "on",
      header: "On",
      accessorKey: "enabled",
      size: 46,
      meta: { align: "center" },
      cell: (c) => (
        <input
          type="checkbox"
          aria-label={`${c.row.original.handle} on`}
          checked={c.row.original.enabled}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => sw.mutate({ level: "account", name: String(c.row.original.id), enabled: e.target.checked })}
        />
      ),
    },
    {
      id: "status",
      header: "Status",
      accessorKey: "status",
      size: 200,
      meta: { flex: 1 },
      cell: (c) => (
        <span className="flex min-w-0 items-center gap-1.5">
          <StatusPill status={c.row.original.status} />
          {c.row.original.paused_reason && <span className="truncate-1 text-warn">· {c.row.original.paused_reason}</span>}
        </span>
      ),
    },
    { id: "today", header: "Today", accessorFn: (r) => r.posts_today / Math.max(1, r.cap_today), size: 70, meta: { align: "right", mono: true }, cell: (c) => `${c.row.original.posts_today}/${c.row.original.cap_today}` },
    { id: "gap", header: "Min gap", accessorKey: "min_gap_min", size: 66, meta: { align: "right", mono: true }, cell: (c) => `${c.row.original.min_gap_min}m` },
    { id: "warmup", header: "Warm-up", accessorKey: "warmup_week", size: 150, cell: (c) => <Warmup week={c.row.original.warmup_week} /> },
    { id: "tags", header: "Niche", accessorFn: (r) => r.niche_tags.join(", "), size: 140, cell: (c) => <span className="flex gap-1">{c.row.original.niche_tags.map((t) => <Badge key={t}>{t}</Badge>)}</span> },
    {
      id: "profile",
      header: "Chrome profile",
      accessorKey: "chrome_profile",
      size: 150,
      cell: (c) => (
        <span className="flex items-center gap-1.5">
          <Dot tone={c.row.original.extension_connected ? "ok" : "warn"} />
          {c.row.original.chrome_profile}
          <span className="text-muted">{c.row.original.extension_connected ? "connected" : "no extension"}</span>
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      size: 190,
      enableSorting: false,
      cell: (c) => (
        <span className="flex gap-1">
          <BrowserButton profile={c.row.original.chrome_profile} />
          {c.row.original.status.startsWith("paused") && (
            <Button size="sm" variant="primary" onClick={(e) => (e.stopPropagation(), resume.mutate(c.row.original.id))}>
              Resume
            </Button>
          )}
        </span>
      ),
    },
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <div className="flex items-center gap-2">
        <span className="text-muted">A paused account stays paused until you fix the challenge in its Chrome window and press Resume. Clipper never solves challenges.</span>
        <span className="flex-1" />
        <Button onClick={() => setAdding(true)}>Add account</Button>
      </div>
      <DataGrid label="Accounts" data={accounts} columns={columns} getRowId={(r) => String(r.id)} selected={focus ? [String(focus)] : undefined} rowHeight={34} className="flex-1" />
      <AddAccountDialog open={adding} onClose={() => setAdding(false)} />
    </div>
  );
}

function Recipes({ recipes }: { recipes: Schemas["RecipeHealth"][] }) {
  const test = useTestRecipe();
  const manifest = useManifest().data;
  const columns: ColumnDef<Schemas["RecipeHealth"], unknown>[] = [
    { id: "recipe", header: "Recipe", accessorKey: "recipe", size: 190, meta: { mono: true } },
    {
      id: "health",
      header: "Health",
      accessorFn: (r) => (r.failures_7d ? 0 : r.last_success ? 2 : 1),
      size: 110,
      cell: (c) => {
        const r = c.row.original;
        return <StatusPill status={r.failures_7d && (!r.last_success || (r.last_failure ?? "") > r.last_success) ? "failing" : r.last_success ? "ok" : "untested"} />;
      },
    },
    { id: "ok", header: "Last success", accessorKey: "last_success", size: 110, cell: (c) => relative(c.row.original.last_success) },
    { id: "fail", header: "Last failure", accessorKey: "last_failure", size: 110, cell: (c) => relative(c.row.original.last_failure) },
    { id: "err", header: "Last error", accessorKey: "last_error", size: 220, meta: { flex: 1 }, cell: (c) => <span className="text-muted">{c.row.original.last_error ?? ""}</span> },
    { id: "runs", header: "Runs 7d", accessorKey: "runs_7d", size: 64, meta: { align: "right", mono: true } },
    { id: "fails", header: "Fails 7d", accessorKey: "failures_7d", size: 64, meta: { align: "right", mono: true } },
    {
      id: "shot",
      header: "Screenshot",
      size: 96,
      cell: (c) => {
        const url = fileUrl(c.row.original.screenshot_url, manifest);
        return url ? (
          <a href={url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
            View
          </a>
        ) : (
          <span className="text-muted">—</span>
        );
      },
    },
    {
      id: "test",
      header: "",
      size: 120,
      enableSorting: false,
      cell: (c) => (
        <Button size="sm" onClick={() => test.mutate(c.row.original.recipe)}>
          Test in dry-run
        </Button>
      ),
    },
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <span className="text-muted">Upload and marketplace scripts run in your Chrome profiles through the Companion extension. A dry-run test stops before the final click.</span>
      <DataGrid label="Recipes" data={recipes} columns={columns} getRowId={(r) => r.recipe} className="flex-1" />
    </div>
  );
}

function Queue({ posts, onCancel, onNow }: { posts: Schemas["PostOut"][]; onCancel: (id: number) => void; onNow: (id: number) => void }) {
  const manifest = useManifest().data;
  const columns: ColumnDef<Schemas["PostOut"], unknown>[] = [
    { id: "when", header: "When", accessorKey: "scheduled_at", size: 120, meta: { mono: true }, cell: (c) => dayTime(c.row.original.scheduled_at) },
    { id: "in", header: "In", accessorKey: "scheduled_at", size: 90, cell: (c) => relative(c.row.original.scheduled_at) },
    {
      id: "clip",
      header: "Clip",
      accessorKey: "clip_id",
      size: 90,
      cell: (c) => (
        <span className="flex items-center gap-1.5">
          {c.row.original.thumb_url && <img src={fileUrl(c.row.original.thumb_url, manifest)} alt="" className="h-6 w-[14px] object-cover" />}#{c.row.original.clip_id}
        </span>
      ),
    },
    { id: "acc", header: "Account", accessorKey: "handle", size: 170, meta: { flex: 1 }, cell: (c) => <span className="flex items-center gap-1.5"><PlatformTag platform={c.row.original.platform} />{c.row.original.handle}</span> },
    { id: "status", header: "Status", accessorKey: "status", size: 110, cell: (c) => <StatusPill status={c.row.original.status} /> },
    { id: "dry", header: "Mode", accessorKey: "dry_run", size: 80, cell: (c) => (c.row.original.dry_run ? <span className="text-warn">dry run</span> : "live") },
    {
      id: "actions",
      header: "",
      size: 150,
      enableSorting: false,
      cell: (c) => (
        <span className="flex gap-1">
          <Button size="sm" onClick={() => onNow(c.row.original.id)}>
            Post now
          </Button>
          <Button size="sm" variant="danger" onClick={() => onCancel(c.row.original.id)}>
            Cancel
          </Button>
        </span>
      ),
    },
  ];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <span className="text-muted">Post now still checks the posting cap, the minimum gap and approval.</span>
      <DataGrid label="Scheduled posts" data={posts} columns={columns} getRowId={(r) => String(r.id)} initialSort={[{ id: "when", desc: false }]} empty="Nothing scheduled." className="flex-1" />
    </div>
  );
}

/** Publishing: week calendar per account, accounts, upload recipes, queue (UI.md §3.6). */
export function PublishingScreen() {
  const search = useSearch({ from: "/shell/publishing" });
  const navigate = useNavigate();
  const cal = useCalendar().data;
  const accounts = useAccounts().data ?? [];
  const recipes = useRecipes().data ?? [];
  const manifest = useManifest().data;
  const reschedule = useReschedule();
  const cancel = useCancelPost();
  const sw = useSwitch();
  const tab = search.tab ?? (search.account ? "accounts" : "calendar");
  const queue = useMemo(() => (cal?.posts ?? []).filter((p) => p.status === "scheduled"), [cal]);
  const paused = accounts.filter((a) => a.enabled && a.status !== "active").length;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-4 pt-3 pb-2">
        <TitleRow title="Publishing" sub={`${accounts.length} accounts${paused ? ` · ${paused} need you` : ""} · ${queue.length} scheduled`} />
      </div>
      <Tabs
        value={tab}
        onValueChange={(v) => void navigate({ to: "/publishing", search: { tab: v as typeof search.tab } })}
        className="min-h-0 flex-1"
        tabs={[
          { value: "calendar", label: "Calendar" },
          { value: "accounts", label: `Accounts (${accounts.length})` },
          { value: "recipes", label: "Recipes" },
          { value: "queue", label: `Queue (${queue.length})` },
        ]}
      >
        <TabPanel value="calendar" className="overflow-auto p-3">
          {cal && (
            <CalendarLanes
              data={cal}
              thumbFor={(p) => fileUrl(p.thumb_url, manifest)}
              onReschedule={(postId, iso) => reschedule.mutate({ postId, at: iso })}
              onToggleAccount={(id, on) => sw.mutate({ level: "account", name: String(id), enabled: on })}
            />
          )}
          <p className="mt-2 text-muted">Drag a scheduled post to another day. Red outline: the daily cap or the minimum gap would be broken.</p>
        </TabPanel>
        <TabPanel value="accounts" className="flex flex-col">
          <Accounts accounts={accounts} focus={search.account} />
        </TabPanel>
        <TabPanel value="recipes" className="flex flex-col">
          <Recipes recipes={recipes} />
        </TabPanel>
        <TabPanel value="queue" className="flex flex-col">
          <Queue posts={queue} onCancel={(id) => cancel.mutate(id)} onNow={(id) => reschedule.mutate({ postId: id, at: new Date(nowMs() + 60_000).toISOString() })} />
        </TabPanel>
      </Tabs>
    </div>
  );
}
