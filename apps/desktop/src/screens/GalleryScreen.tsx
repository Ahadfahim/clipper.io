import { useMemo, useState, type ReactNode } from "react";
import { useBatch, useBoard, useCalendar, useCampaigns, useClip, useEditState, useLessons, useManifest, useOverview, useQuestions, useSession, useStatus } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { DataGrid, type ColumnDef } from "@/components/ui/data-grid";
import { Dialog } from "@/components/ui/dialog";
import { Check, Field, Fieldset, Radio, Select, TextArea, TextField } from "@/components/ui/fields";
import { ContextMenu, DropdownMenu } from "@/components/ui/menu";
import { Badge, Kbd, PaneHeader, Progress, PropertyGrid, Toolbar, ToolbarSep, Tooltip } from "@/components/ui/misc";
import { Dot, StatusPill, type StatusTone } from "@/components/ui/status";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { AgentEventRow, SlotBoard } from "@/components/domain/agents";
import { AskUserCard, NeedsYouList } from "@/components/domain/attention";
import { AccountChip, MarketBadge, PlatformTag, Score } from "@/components/domain/badges";
import { CalendarLanes } from "@/components/domain/calendar";
import { ClipCard, ClipPlayer, SignalTimeline, TranscriptView } from "@/components/domain/clip";
import { AgendaPanel, EdlPreview, EditHistory, Timeline } from "@/components/domain/edit";
import { LessonRow } from "@/components/domain/lessons";
import { BudgetBurnBar, KpiTile, Sparkline, StageStepper, UsageMeter } from "@/components/domain/meters";
import { HoldButton, SwitchChip, SwitchOffDialog, ToggleCard, UntrustedBanner } from "@/components/domain/switches";
import { asEdl } from "@/lib/edl";
import { groupTranscript } from "@/lib/transcript";
import { useAppearanceToggle } from "./galleryTheme";

function Spec({ name, note, children, wide }: { name: string; note?: string; children: ReactNode; wide?: boolean }) {
  return (
    <section aria-label={name} className={wide ? "col-span-full" : ""}>
      <div className="mb-1.5 flex items-baseline gap-2">
        <h2 className="num text-[12px] font-semibold">{name}</h2>
        {note && <span className="text-muted">{note}</span>}
      </div>
      <div className="flex flex-col gap-2 rounded-[var(--radius)] border border-line bg-panel p-3">{children}</div>
    </section>
  );
}

/**
 * /dev/gallery: every shared component with fixture data, in the current theme. Screens are
 * built from these; screenshots of this page are the visual reference (UI.md §5).
 */
export function GalleryScreen() {
  const toggle = useAppearanceToggle();
  const overview = useOverview().data;
  const status = useStatus().data;
  const board = useBoard().data;
  const session = useSession(1).data;
  const clip = useClip(1).data;
  const edit = useEditState(3).data;
  const batch = useBatch(1).data;
  const cal = useCalendar().data;
  const lessons = useLessons().data ?? [];
  const questions = useQuestions().data ?? [];
  const campaigns = useCampaigns().data ?? [];
  const manifest = useManifest().data;
  const [dialog, setDialog] = useState(false);
  const [off, setOff] = useState<{ level: "marketplace" | "social"; name: string; label: string } | null>(null);
  const [chk, setChk] = useState(true);
  const [tab, setTab] = useState("one");
  const transcript = useMemo(() => groupTranscript(session?.events ?? []), [session]);
  const edl = useMemo(() => (edit ? asEdl(edit.edl) : null), [edit]);

  const cols: ColumnDef<Schemas["CampaignRow"], unknown>[] = [
    { id: "m", header: "Source", accessorKey: "marketplace", size: 70, cell: (c) => <MarketBadge market={c.row.original.marketplace} /> },
    { id: "s", header: "Score", accessorKey: "score", size: 56, meta: { align: "right" }, cell: (c) => <Score value={c.row.original.score} /> },
    { id: "t", header: "Campaign", accessorKey: "title", size: 160, meta: { flex: 1 } },
    { id: "st", header: "Status", accessorKey: "status", size: 100, cell: (c) => <StatusPill status={c.row.original.status} /> },
  ];
  const tones: StatusTone[] = ["ok", "warn", "bad", "agent", "accent", "muted", "off"];

  return (
    <div className="h-full overflow-auto bg-bg">
      <Toolbar label="Gallery">
        <span className="font-semibold">Component gallery</span>
        <span className="text-muted">· fixture data · {status?.fixture_mode ? "fixture core" : "live core"}</span>
        <span className="flex-1" />
        {toggle}
      </Toolbar>
      <div className="grid gap-4 p-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))" }}>
        <Spec name="Button" note="28px, 4px corners, verb-first">
          <div className="flex flex-wrap gap-2">
            <Button variant="primary">Approve</Button>
            <Button>Reject</Button>
            <Button variant="ghost">Scout now</Button>
            <Button variant="danger">Stop all</Button>
            <Button disabled>Disabled</Button>
            <Button size="sm" shortcut="A">
              Small
            </Button>
          </div>
        </Spec>
        <Spec name="Fields" note="underline text fields, checkboxes for on/off">
          <Field label="Text">{(id) => <TextField id={id} defaultValue="Night Shift Podcast" />}</Field>
          <Field label="Select">
            {(id) => (
              <Select id={id}>
                <option>Suggest</option>
                <option>Auto</option>
              </Select>
            )}
          </Field>
          <TextArea aria-label="Notes" rows={2} defaultValue="Make the hook shorter" />
          <div className="flex gap-4">
            <Check checked={chk} onChange={setChk} label="Dry run" />
            <Radio name="g" checked onChange={() => undefined} label="Crop" />
            <Radio name="g" checked={false} onChange={() => undefined} label="Split" />
          </div>
          <Fieldset legend="Fieldset">
            <span>Grouped controls with a legend.</span>
          </Fieldset>
        </Spec>
        <Spec name="StatusPill · Dot" note="dot + word, never color alone">
          <div className="flex flex-wrap gap-3">
            {["running", "dry run", "paused", "blocked", "approved", "rejected", "editing", "ended"].map((s) => (
              <StatusPill key={s} status={s} />
            ))}
          </div>
          <div className="flex gap-3">
            {tones.map((t) => (
              <span key={t} className="flex items-center gap-1">
                <Dot tone={t} />
                {t}
              </span>
            ))}
          </div>
        </Spec>
        <Spec name="MarketBadge · PlatformTag · AccountChip · Score">
          <div className="flex flex-wrap items-center gap-3">
            <MarketBadge market="vyro" />
            <MarketBadge market="whop" />
            <PlatformTag platform="youtube" />
            <PlatformTag platform="x" on={false} />
            <AccountChip platform="tiktok" handle="@clipsdaily" status="paused" />
            <AccountChip platform="youtube" handle="@beastmoments" />
            <Score value={92} />
            <Score value={71} />
            <Score value={48} />
          </div>
        </Spec>
        {overview && (
          <Spec name="KpiTile · Sparkline" note="stat strip; split by marketplace on hover" wide>
            <div className="grid overflow-hidden rounded-[var(--radius)] border border-line" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
              {overview.kpis.map((k) => (
                <KpiTile key={k.key} kpi={k} />
              ))}
            </div>
            <Sparkline values={[3, 5, 4, 8, 7, 9, 12]} label="Sample sparkline" width={120} />
          </Spec>
        )}
        <Spec name="UsageMeter" note="amber from 80%, red at the limit">
          <UsageMeter usage={{ utilization: 0.38, max_slots: 4, pace: "normal", rate_limited: false, resets_at: "2026-10-02T20:14:00Z" }} />
          <UsageMeter usage={{ utilization: 0.86, max_slots: 2, pace: "slow", rate_limited: false, resets_at: "2026-10-02T19:10:00Z" }} />
          <UsageMeter usage={{ utilization: 1, max_slots: 0, pace: "paused", rate_limited: true, resets_at: "2026-10-02T18:40:00Z" }} />
        </Spec>
        <Spec name="BudgetBurnBar · StageStepper" note="marker = predicted run-out vs deadline">
          {overview?.active_campaigns.map((c) => (
            <div key={c.id} className="grid items-center gap-3" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <StageStepper stages={c.stages} />
              <BudgetBurnBar left={c.budget_left} total={c.budget_total} runsOut={c.runs_out_at} deadline={c.deadline} />
            </div>
          ))}
        </Spec>
        <Spec name="Progress · Kbd · Badge · Tooltip">
          <Progress value={0.62} label="Render" />
          <Progress value={0.3} tone="agent" label="Agent" />
          <div className="flex items-center gap-2">
            <Kbd>Ctrl+K</Kbd>
            <Badge>UGC</Badge>
            <Tooltip content="Tooltips use the panel surface">
              <Button size="sm">Hover me</Button>
            </Tooltip>
          </div>
        </Spec>
        {overview && (
          <Spec name="NeedsYouItem" note="urgency order, actions inline" wide>
            <NeedsYouList items={overview.needs_you.slice(0, 4)} onAction={() => undefined} empty="You're all caught up." />
            <NeedsYouList items={[]} onAction={() => undefined} empty="You're all caught up. Next scout run in 6m." />
          </Spec>
        )}
        {questions[0] && (
          <Spec name="AskUserCard">
            <AskUserCard q={questions[0]} onAnswer={() => undefined} />
          </Spec>
        )}
        {board && (
          <Spec name="SlotBoard" note="slots, P0–P3 queue with bump/cancel" wide>
            <SlotBoard board={{ ...board, slots: board.slots.map((s, i) => (i === 3 ? { ...s, dimmed: true } : s)) }} onBump={() => undefined} onCancel={() => undefined} />
          </Spec>
        )}
        <Spec name="AgentEventRow" note="message · tool · subagent · blocked · thinking" wide>
          <div className="max-h-[320px] overflow-auto rounded-[var(--radius)] border border-line">
            {transcript.map((i) => (
              <AgentEventRow key={`${i.kind}-${i.id}`} item={i} onReplay={() => undefined} />
            ))}
          </div>
        </Spec>
        {campaigns.length > 0 && (
          <Spec name="DataGrid" note="sort, resize, Ctrl/Shift select, right-click, Ctrl+C" wide>
            <DataGrid
              label="Sample grid"
              data={campaigns}
              columns={cols}
              getRowId={(r) => String(r.id)}
              contextMenu={(r) => [{ label: `Open ${r.title}`, onSelect: () => undefined }, { kind: "separator" }, { label: "Skip", onSelect: () => undefined }]}
              className="h-[220px]"
            />
          </Spec>
        )}
        <Spec name="PropertyGrid · PaneHeader · Tabs">
          <div className="overflow-hidden rounded-[var(--radius)] border border-line">
            <PaneHeader>Properties</PaneHeader>
            <PropertyGrid rows={[["Score", <Score key="s" value={87} />], ["Length", "0:42"], ["Why", "Payoff at 0:31 matches the replay peak"]]} />
          </div>
          <Tabs value={tab} onValueChange={setTab} tabs={[{ value: "one", label: "Activity" }, { value: "two", label: "Jobs (2)" }]}>
            <TabPanel value="one" className="p-2">
              Activity tab
            </TabPanel>
            <TabPanel value="two" className="p-2">
              Jobs tab
            </TabPanel>
          </Tabs>
        </Spec>
        <Spec name="Menus · Dialog · Toolbar">
          <Toolbar label="Sample toolbar" className="rounded-[var(--radius)] border">
            <Button size="sm">Pause all</Button>
            <ToolbarSep />
            <SwitchChip label="Vyro" on onToggle={() => undefined} />
            <SwitchChip label="Whop" on health="warn" onToggle={() => undefined} />
            <SwitchChip label="X" on={false} onToggle={() => undefined} />
          </Toolbar>
          <div className="flex gap-2">
            <DropdownMenu items={[{ label: "Bad hook", onSelect: () => undefined }, { label: "Boring", onSelect: () => undefined }, { kind: "check", label: "Dry run", checked: true, onSelect: () => undefined }]}>
              <Button>Reject ▾</Button>
            </DropdownMenu>
            <ContextMenu items={[{ label: "Approve", shortcut: "A", onSelect: () => undefined }, { label: "Copy link", onSelect: () => undefined }]}>
              <span className="flex h-7 items-center rounded-[var(--radius)] border border-dashed border-line px-2 text-muted">Right-click here</span>
            </ContextMenu>
            <Button onClick={() => setDialog(true)}>Open dialog</Button>
            <Button onClick={() => setOff({ level: "marketplace", name: "whop", label: "Whop" })}>Switch-off dialog</Button>
          </div>
          <Dialog open={dialog} onOpenChange={setDialog} title="Dialog" footer={<Button variant="primary" onClick={() => setDialog(false)}>OK</Button>}>
            Windows-style dialog with a button row.
          </Dialog>
          <SwitchOffDialog target={off} onClose={() => setOff(null)} onConfirm={() => undefined} />
        </Spec>
        <Spec name="ToggleCard · UntrustedBanner · HoldButton">
          <ToggleCard name="Vyro" on tone="ok" status="Logged in · 2 active campaigns" onToggle={() => undefined} />
          <ToggleCard name="@clipsdaily" indent on tone="warn" status="Paused: verification needed" onToggle={() => undefined} />
          <ToggleCard name="X" on={false} locked tone="off" status="Upload script arrives later" onToggle={() => undefined} />
          <UntrustedBanner />
          <HoldButton label="Hold to stop" onConfirm={() => undefined} />
        </Spec>
        {batch && (
          <Spec name="ClipCard" note="9:16, plays on hover">
            <div className="grid grid-cols-3 gap-2">
              {batch.clips.slice(0, 3).map((c, i) => (
                <ClipCard key={c.clip.id} clip={c.clip} thumb={fileUrl(c.clip.thumb_url, manifest)} preview={fileUrl(c.clip.preview_url, manifest)} selected={i === 0} />
              ))}
            </div>
          </Spec>
        )}
        {clip && (
          <Spec name="ClipPlayer · TranscriptView" note="frame step, trim handles in re-cut mode">
            <div className="flex gap-3">
              <ClipPlayer label="Sample clip" src={fileUrl(clip.clip.preview_url, manifest)} poster={fileUrl(clip.clip.thumb_url, manifest)} width={160} autoPlay={false} trim={{ start: -1.2, end: 0.8, extra: 5, onChange: () => undefined }} />
              <TranscriptView words={clip.transcript} time={1.1} className="flex-1" />
            </div>
          </Spec>
        )}
        {clip && (
          <Spec name="SignalTimeline" note="heatmap · scene cuts · energy · this clip" wide>
            <SignalTimeline signals={clip.signals} range={clip.source_range} moments={[{ start: 600, end: 640 }]} />
          </Spec>
        )}
        {edit && edl && (
          <Spec name="EdlPreview · Timeline · EditHistory · AgendaPanel" note="violet = Claude working" wide>
            <div className="flex gap-3">
              <EdlPreview edl={edl} src={fileUrl(edit.proxy_url, manifest)} poster={fileUrl(edit.clip.thumb_url, manifest)} width={150} />
              <div className="flex min-w-0 flex-1 flex-col justify-end">
                <Timeline edl={edl} t={1.2} onSeek={() => undefined} agentRange={edit.live_range} agentLabel={edit.live_status} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex h-[260px] flex-col overflow-hidden rounded-[var(--radius)] border border-line">
                <EditHistory history={edit.history} liveText={edit.live_status} onUndo={() => undefined} />
              </div>
              <div className="flex h-[260px] flex-col overflow-hidden rounded-[var(--radius)] border border-line">
                <AgendaPanel plan={edit.plan} notes={edit.notes} onSend={() => undefined} />
              </div>
            </div>
          </Spec>
        )}
        {cal && (
          <Spec name="CalendarLane" note="drag with cap and min-gap checks" wide>
            <CalendarLanes data={cal} thumbFor={(p) => fileUrl(p.thumb_url, manifest)} onReschedule={() => undefined} onToggleAccount={() => undefined} />
          </Spec>
        )}
        {lessons[0] && (
          <Spec name="LessonRow">
            {lessons.slice(0, 3).map((l) => (
              <LessonRow key={l.id} lesson={l} onSave={() => undefined} onDelete={() => undefined} />
            ))}
          </Spec>
        )}
      </div>
    </div>
  );
}
