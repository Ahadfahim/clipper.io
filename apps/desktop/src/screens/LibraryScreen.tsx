import { useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useCampaigns, useClips, useManifest } from "@/api/queries";
import { fileUrl } from "@/api/client";
import { Select, TextField } from "@/components/ui/fields";
import { Empty, TitleRow, Toolbar, ToolbarSep } from "@/components/ui/misc";
import { ClipCard } from "@/components/domain/clip";
import { useHotkeys } from "@/lib/hotkeys";

const NONE: never[] = [];

const STATUSES = ["candidate", "rendering", "in_review", "approved", "rejected", "scheduled", "posted", "failed"];

/** Clip library: 9:16 cards with filters and sort; hover plays (UI.md §3.4). "/" focuses search. */
export function LibraryScreen() {
  const search = useSearch({ from: "/shell/library" });
  const navigate = useNavigate();
  const clips = useClips().data ?? NONE;
  const campaigns = useCampaigns().data ?? [];
  const manifest = useManifest().data;
  const [q, setQ] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [layout, setLayout] = useState("all");
  const [style, setStyle] = useState("all");
  const [posted, setPosted] = useState<"all" | "posted" | "not">("all");
  const [sort, setSort] = useState<"score" | "views" | "date">("score");
  const field = useRef<HTMLInputElement>(null);
  useHotkeys({ "/": () => field.current?.focus() });

  const set = (patch: Record<string, unknown>) => void navigate({ to: "/library", search: { ...search, ...patch } });
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return clips
      .filter(
        (c) =>
          (!search.campaign || c.campaign_id === search.campaign) &&
          (!search.status || c.status === search.status) &&
          c.score >= minScore &&
          (layout === "all" || c.layout === layout) &&
          (style === "all" || c.caption_style === style) &&
          (posted === "all" || (posted === "posted" ? c.platforms_posted.length > 0 : c.platforms_posted.length === 0)) &&
          (!s || c.hook.toLowerCase().includes(s) || String(c.id) === s),
      )
      .sort((a, b) => (sort === "score" ? b.score - a.score : sort === "views" ? b.views - a.views : b.id - a.id));
  }, [clips, search, minScore, layout, style, posted, sort, q]);

  const styles = [...new Set(clips.map((c) => c.caption_style))].sort();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-4 pt-3 pb-2">
        <TitleRow title="Library" sub={`${shown.length} of ${clips.length} clips`} />
      </div>
      <Toolbar label="Library filters" className="flex-nowrap overflow-x-auto border-t [&>*]:shrink-0">
        <label htmlFor="lib-q" className="sr-only">
          Search clips
        </label>
        <TextField id="lib-q" ref={field} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search hooks   /" className="h-6 w-40" />
        <ToolbarSep />
        <Select aria-label="Campaign" value={search.campaign ?? ""} onChange={(e) => set({ campaign: e.target.value ? Number(e.target.value) : undefined })} className="h-6 w-40">
          <option value="">All campaigns</option>
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </Select>
        <Select aria-label="Status" value={search.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined })} className="h-6 w-28">
          <option value="">Any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </Select>
        <Select aria-label="Minimum score" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="h-6 w-28">
          {[0, 60, 70, 80, 90].map((n) => (
            <option key={n} value={n}>
              {n ? `Score ${n}+` : "Any score"}
            </option>
          ))}
        </Select>
        <Select aria-label="Layout" value={layout} onChange={(e) => setLayout(e.target.value)} className="h-6 w-28">
          <option value="all">Any layout</option>
          <option value="crop">Crop</option>
          <option value="split">Split</option>
          <option value="fit">Fit</option>
        </Select>
        <Select aria-label="Caption style" value={style} onChange={(e) => setStyle(e.target.value)} className="h-6 w-28">
          <option value="all">Any captions</option>
          {styles.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
        <Select aria-label="Posted" value={posted} onChange={(e) => setPosted(e.target.value as typeof posted)} className="h-6 w-28">
          <option value="all">Posted or not</option>
          <option value="posted">Posted</option>
          <option value="not">Not posted</option>
        </Select>
        <span className="flex-1" />
        <label htmlFor="lib-sort" className="px-1 text-muted">
          Sort
        </label>
        <Select id="lib-sort" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="h-6 w-24">
          <option value="score">Score</option>
          <option value="views">Views</option>
          <option value="date">Newest</option>
        </Select>
      </Toolbar>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        {shown.length === 0 ? (
          <Empty>No clips match these filters.</Empty>
        ) : (
          <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(132px, 1fr))" }}>
            {shown.map((c) => (
              <ClipCard
                key={c.id}
                clip={c}
                thumb={fileUrl(c.thumb_url, manifest)}
                preview={fileUrl(c.preview_url, manifest)}
                onOpen={() => void navigate({ to: "/library/$clipId", params: { clipId: String(c.id) } })}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
