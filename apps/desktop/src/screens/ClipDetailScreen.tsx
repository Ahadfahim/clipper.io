import { ArrowLeft16Regular, Edit16Regular, LinkSquare16Regular } from "@fluentui/react-icons";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { useClip, useManifest } from "@/api/queries";
import { fileUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Empty, PaneHeader, PropertyGrid } from "@/components/ui/misc";
import { Dot, StatusPill } from "@/components/ui/status";
import { TabPanel, Tabs } from "@/components/ui/tabs";
import { ClipCard, ClipPlayer, SignalTimeline, TranscriptView, type PlayerHandle } from "@/components/domain/clip";
import { PlatformTag, Score } from "@/components/domain/badges";
import { compact, dayTime, duration, money } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { openUrl } from "@/lib/tauri";

/** Clip detail: player with frame stepping; transcript, why this moment, versions, posts (UI.md §3.4). */
export function ClipDetailScreen() {
  const { clipId } = useParams({ from: "/shell/library/$clipId" });
  const search = useSearch({ from: "/shell/library/$clipId" });
  const navigate = useNavigate();
  const id = Number(clipId);
  const d = useClip(id).data;
  const manifest = useManifest().data;
  const player = useRef<PlayerHandle>(null);
  const [t, setT] = useState(0);
  useHotkeys({
    space: () => player.current?.toggle(),
    ",": () => player.current?.step(-1),
    ".": () => player.current?.step(1),
    e: () => void navigate({ to: "/edit/$clipId", params: { clipId } }),
  });
  if (!d) return <Empty>Loading clip…</Empty>;
  const c = d.clip;
  const tab = search.tab ?? "transcript";
  const scores = d.scores as Record<string, number>;
  const qa = d.qa as { ok?: boolean; checks?: { name: string; ok: boolean; detail: string }[] };
  const sourceUrl = (d.signals["url"] as string | undefined) ?? null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-chrome px-3 py-1.5">
        <Link to="/library" className="flex items-center gap-1 text-muted hover:text-fg">
          <ArrowLeft16Regular /> Library
        </Link>
        <span className="text-muted">/</span>
        <span className="font-semibold">Clip {c.id}</span>
        <span className="truncate-1 text-muted">· {c.campaign_title}</span>
        <StatusPill status={c.status} />
        <span className="flex-1" />
        <Button icon={<Edit16Regular />} shortcut="E" onClick={() => void navigate({ to: "/edit/$clipId", params: { clipId } })}>
          Edit
        </Button>
        {sourceUrl && (
          <Button icon={<LinkSquare16Regular />} onClick={() => void openUrl(`${sourceUrl}&t=${Math.floor(d.source_range[0] ?? 0)}`)}>
            Open source at {duration(d.source_range[0])}
          </Button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-wrap overflow-auto">
        <div className="flex flex-[1_1_320px] flex-col items-center gap-3 bg-bg p-4">
          <ClipPlayer ref={player} label={`Clip ${c.id} preview`} src={fileUrl(c.preview_url, manifest)} poster={fileUrl(c.thumb_url, manifest)} width={270} onTime={setT} autoPlay={false} />
          <PropertyGrid
            className="w-full max-w-[360px] rounded-[var(--radius)] border border-line"
            rows={[
              ["Score", <Score key="s" value={c.score} />],
              ["Length", <span key="l" className="num">{duration(c.duration)}</span>],
              ["Source", <span key="r" className="num">{`${d.source_title ?? "source"} · ${duration(d.source_range[0])}–${duration(d.source_range[1])}`}</span>],
              ["Layout", c.layout],
              ["Captions", c.caption_style],
              ["Version", <span key="v" className="num">v{c.version}</span>],
              ["Views", <span key="w" className="num">{compact(c.views)}</span>],
            ]}
          />
        </div>
        <div className="flex min-h-[420px] min-w-0 flex-[2_1_480px] flex-col border-l border-line bg-panel">
          <Tabs
            value={tab}
            onValueChange={(v) => void navigate({ to: "/library/$clipId", params: { clipId }, search: { tab: v }, replace: true })}
            className="min-h-0 flex-1"
            tabs={[
              { value: "transcript", label: "Transcript" },
              { value: "why", label: "Why this moment" },
              { value: "versions", label: `Versions (${d.variants.length + 1})` },
              { value: "posts", label: `Posts (${d.posts.length})` },
            ]}
          >
            <TabPanel value="transcript" className="overflow-auto">
              {d.transcript.length ? <TranscriptView words={d.transcript} time={t} onSeek={(x) => player.current?.seek(x)} /> : <Empty>No transcript.</Empty>}
            </TabPanel>
            <TabPanel value="why" className="flex flex-col gap-3 overflow-auto p-3">
              <div className="selectable">{d.reason}</div>
              {d.payoff && <div className="text-muted">Payoff: <span className="text-fg">{d.payoff}</span></div>}
              <div>
                <div className="mb-1 text-muted">Signal timeline · whole source</div>
                <SignalTimeline signals={d.signals} range={d.source_range} />
                <div className="mt-1 flex gap-4 text-[11px] text-muted">
                  <span className="flex items-center gap-1"><span className="inline-block size-2 bg-series-1" /> replay heatmap</span>
                  <span className="flex items-center gap-1"><span className="inline-block h-2 w-px bg-muted" /> scene cut</span>
                  <span className="flex items-center gap-1"><Dot tone="agent" /> energy spike</span>
                  <span className="flex items-center gap-1"><span className="inline-block size-2 border border-accent bg-accent-soft" /> this clip</span>
                </div>
              </div>
              <div>
                <PaneHeader className="rounded-t-[var(--radius)] border border-b-0">Scores</PaneHeader>
                <PropertyGrid className="border border-line" rows={Object.entries(scores).map(([k, v]) => [k, <Score key={k} value={v} />])} />
              </div>
              {qa.checks && (
                <div>
                  <PaneHeader className="rounded-t-[var(--radius)] border border-b-0">Quality checks · {qa.ok ? "passed" : "failed"}</PaneHeader>
                  <div className="border border-line">
                    {qa.checks.map((q) => (
                      <div key={q.name} className="flex items-center gap-2 border-b border-line-soft px-2.5 py-1 last:border-b-0">
                        <Dot tone={q.ok ? "ok" : "bad"} />
                        <span className="w-40">{q.name.replace(/_/g, " ")}</span>
                        <span className="text-muted">{q.detail}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </TabPanel>
            <TabPanel value="versions" className="overflow-auto p-3">
              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
                <div>
                  <div className="mb-1 text-muted">Current · v{c.version}</div>
                  <ClipCard clip={c} thumb={fileUrl(c.thumb_url, manifest)} preview={fileUrl(c.preview_url, manifest)} selected />
                </div>
                {d.variants.map((v) => (
                  <div key={v.id}>
                    <div className="mb-1 text-muted">{v.variant_label ?? `v${v.version}`}</div>
                    <ClipCard clip={v} thumb={fileUrl(v.thumb_url, manifest)} preview={fileUrl(v.preview_url, manifest)} onOpen={() => void navigate({ to: "/library/$clipId", params: { clipId: String(v.id) } })} />
                  </div>
                ))}
              </div>
              {d.variants.length === 0 && <p className="mt-3 text-muted">No re-cuts or hook variants yet.</p>}
            </TabPanel>
            <TabPanel value="posts" className="overflow-auto">
              {d.posts.length === 0 && <Empty>Not posted yet.</Empty>}
              {d.posts.map((p) => (
                <div key={p.id} className="grid items-center gap-2 border-b border-line-soft px-3 py-1.5" style={{ gridTemplateColumns: "28px 160px 100px 110px 80px 80px minmax(0,1fr)" }}>
                  <PlatformTag platform={p.platform} />
                  <span className="truncate-1">{p.handle}</span>
                  <StatusPill status={p.status} />
                  <span className="num text-muted">{dayTime(p.posted_at ?? p.scheduled_at)}</span>
                  <span className="num text-right">{compact(p.views)}</span>
                  <span className="num text-right">{money(p.earnings, { cents: true })}</span>
                  {p.url ? (
                    <button type="button" className="truncate-1 text-left text-accent hover:underline" onClick={() => void openUrl(p.url ?? "")}>
                      {p.url}
                    </button>
                  ) : (
                    <span />
                  )}
                </div>
              ))}
            </TabPanel>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
