import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useHide, useRestore } from "@/api/actions";
import { useCampaigns, useClips, useHiddenClips, useManifest, useScrappedClips } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Select, TextField } from "@/components/ui/fields";
import { ContextMenu, type MenuItem } from "@/components/ui/menu";
import { Empty, TitleRow, Toolbar, ToolbarSep } from "@/components/ui/misc";
import { ClipCard } from "@/components/domain/clip";
import { CleanupDialog, DeleteFilesDialog, ScrapDialog } from "@/components/domain/scrap";
import { useHotkeys } from "@/lib/hotkeys";
import { clickSelect, EMPTY_SELECTION, LIBRARY_VIEWS, prune, selectAll, type Selection } from "@/lib/library";

const NONE: never[] = [];
const UNDO_MS = 15_000;

type Row = Schemas["ClipRow"];

/** Clip library: 9:16 cards with filters and sort; hover plays (UI.md §3.4). "/" focuses search.
 * Click selects (Ctrl and Shift extend), double-click or Enter opens, Delete scraps what is selected. */
export function LibraryScreen() {
  const search = useSearch({ from: "/shell/library" });
  const navigate = useNavigate();
  const all = useClips().data ?? NONE;
  const scrappedClips = useScrappedClips().data ?? NONE;
  const hiddenClips = useHiddenClips().data ?? NONE;
  const campaigns = useCampaigns().data ?? [];
  const manifest = useManifest().data;
  const view = search.status;
  const scrappedView = view === "scrapped";
  const hiddenView = view === "hidden";
  const clips = scrappedView ? scrappedClips : hiddenView ? hiddenClips : all;

  const [q, setQ] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [layout, setLayout] = useState("all");
  const [style, setStyle] = useState("all");
  const [posted, setPosted] = useState<"all" | "posted" | "not">("all");
  const [sort, setSort] = useState<"score" | "views" | "date">("score");
  const [sel, setSel] = useState<Selection>(EMPTY_SELECTION);
  const [scrapOpen, setScrapOpen] = useState(false);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [undo, setUndo] = useState<{ ids: number[]; at: number } | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const restore = useRestore();
  const hide = useHide();
  useHotkeys({ "/": () => field.current?.focus() });

  const set = (patch: Record<string, unknown>) => void navigate({ to: "/library", search: { ...search, ...patch } });
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return clips
      .filter(
        (c) =>
          (!search.campaign || c.campaign_id === search.campaign) &&
          (!view || scrappedView || hiddenView || c.status === view) &&
          c.score >= minScore &&
          (layout === "all" || c.layout === layout) &&
          (style === "all" || c.caption_style === style) &&
          (posted === "all" || (posted === "posted" ? c.platforms_posted.length > 0 : c.platforms_posted.length === 0)) &&
          (!s || c.hook.toLowerCase().includes(s) || String(c.id) === s),
      )
      .sort((a, b) => (sort === "score" ? b.score - a.score : sort === "views" ? b.views - a.views : b.id - a.id));
  }, [clips, search.campaign, view, scrappedView, hiddenView, minScore, layout, style, posted, sort, q]);
  const order = useMemo(() => shown.map((c) => c.id), [shown]);

  // a filter changed or clips were scrapped: forget selected cards that aren't on screen any more
  useEffect(() => {
    setSel((s) => prune(s, order));
  }, [order]);
  // the undo bar goes away by itself
  useEffect(() => {
    if (!undo) return;
    const t = setTimeout(() => setUndo(null), Math.max(0, undo.at + UNDO_MS - Date.now()));
    return () => clearTimeout(t);
  }, [undo]);

  const styles = [...new Set(all.map((c) => c.caption_style))].sort();
  const selected = shown.filter((c) => sel.ids.has(c.id));
  const open = (c: Row) => void navigate({ to: "/library/$clipId", params: { clipId: String(c.id) } });
  const startScrap = (rows: Row[]) => {
    if (!rows.length) return;
    setSel({ ids: new Set(rows.map((r) => r.id)), anchor: rows[0]!.id });
    setScrapOpen(true);
  };
  const undoScrap = () => {
    if (!undo) return;
    restore.mutate(undo.ids);
    setUndo(null);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).matches("input, textarea, select")) return;
    if (e.key === "Delete" && selected.length && !scrappedView && !hiddenView) {
      e.preventDefault();
      setScrapOpen(true);
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      setSel(selectAll(order));
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && undo) {
      e.preventDefault();
      undoScrap();
    } else if (e.key === "Escape" && sel.ids.size) {
      setSel(EMPTY_SELECTION);
    }
  };

  const menuFor = (c: Row): MenuItem[] => {
    const target = sel.ids.has(c.id) ? selected : [c];
    const many = target.length > 1;
    const posted_ = target.some((t) => t.platforms_posted.length > 0 || t.status === "posted");
    if (scrappedView) {
      return [
        { label: many ? `Restore ${target.length} clips` : "Restore", onSelect: () => restore.mutate(target.map((t) => t.id)), disabled: target.every((t) => t.files_purged) },
        { label: "Delete files now…", onSelect: () => { setSel({ ids: new Set(target.map((t) => t.id)), anchor: c.id }); setDeleteOpen(true); }, danger: true, disabled: target.every((t) => t.files_purged) },
      ];
    }
    if (hiddenView) return [{ label: many ? `Show ${target.length} clips again` : "Show in the Library", onSelect: () => hide.mutate({ ids: target.map((t) => t.id), hidden: false }) }];
    const items: MenuItem[] = [
      { label: "Open", shortcut: "Enter", onSelect: () => open(c), disabled: many },
      { label: "Edit", onSelect: () => void navigate({ to: "/edit/$clipId", params: { clipId: String(c.id) } }), disabled: many },
      { label: "Copy hook", onSelect: () => void navigator.clipboard?.writeText(c.hook), disabled: many || !c.hook },
      { kind: "separator" },
    ];
    if (posted_) items.push({ label: many ? `Hide ${target.length} clips from the Library` : "Hide from the Library", onSelect: () => hide.mutate({ ids: target.map((t) => t.id), hidden: true }) });
    items.push({ label: many ? `Scrap ${target.length} clips…` : "Scrap…", shortcut: "Del", danger: true, onSelect: () => startScrap(target) });
    return items;
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col outline-none" tabIndex={-1} onKeyDown={onKeyDown}>
      <div className="px-4 pt-3 pb-2">
        <TitleRow
          title="Library"
          sub={`${shown.length} of ${clips.length} clips${sel.ids.size ? ` · ${sel.ids.size} selected` : ""}`}
          actions={
            <>
              {selected.length > 0 && !scrappedView && !hiddenView && (
                <Button variant="danger" shortcut="Del" onClick={() => setScrapOpen(true)}>
                  {`Scrap (${selected.length})`}
                </Button>
              )}
              {selected.length > 0 && scrappedView && (
                <>
                  <Button onClick={() => restore.mutate(selected.map((c) => c.id))} disabled={selected.every((c) => c.files_purged)}>
                    {`Restore (${selected.length})`}
                  </Button>
                </>
              )}
              {scrappedView && shown.length > 0 && (
                <Button variant="danger" onClick={() => setDeleteOpen(true)} disabled={shown.every((c) => c.files_purged)}>
                  {selected.length ? `Delete files now (${selected.length})` : "Delete files now"}
                </Button>
              )}
              {selected.length > 0 && hiddenView && <Button onClick={() => hide.mutate({ ids: selected.map((c) => c.id), hidden: false })}>{`Show again (${selected.length})`}</Button>}
              <Button onClick={() => setCleanupOpen(true)}>Clean up…</Button>
            </>
          }
        />
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
          {LIBRARY_VIEWS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
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
      {undo && (
        <div role="status" className="flex items-center gap-3 border-b border-line bg-accent-soft px-4 py-1">
          <span>{`${undo.ids.length} clip${undo.ids.length === 1 ? "" : "s"} scrapped.`}</span>
          <Button size="sm" shortcut="Ctrl+Z" onClick={undoScrap}>
            Undo
          </Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto p-3" onClick={(e) => e.target === e.currentTarget && setSel(EMPTY_SELECTION)}>
        {shown.length === 0 ? (
          <Empty>{scrappedView ? "Nothing scrapped." : hiddenView ? "Nothing hidden." : "No clips match these filters."}</Empty>
        ) : (
          <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(132px, 1fr))" }} role="group" aria-label="Clips">
            {shown.map((c) => (
              <ContextMenu key={c.id} items={menuFor(c)}>
                <div onContextMenu={() => !sel.ids.has(c.id) && setSel({ ids: new Set([c.id]), anchor: c.id })}>
                  <ClipCard
                    clip={c}
                    thumb={fileUrl(c.thumb_url, manifest)}
                    preview={fileUrl(c.preview_url, manifest)}
                    selected={sel.ids.has(c.id)}
                    onSelect={(mods) => setSel((s) => clickSelect(s, order, c.id, mods))}
                    onOpen={() => open(c)}
                  />
                </div>
              </ContextMenu>
            ))}
          </div>
        )}
      </div>
      <ScrapDialog clips={selected} open={scrapOpen} onClose={() => setScrapOpen(false)} onScrapped={(res) => res.scrapped.length && setUndo({ ids: res.scrapped, at: Date.now() })} />
      <CleanupDialog open={cleanupOpen} onClose={() => setCleanupOpen(false)} onScrapped={(ids) => ids.length && setUndo({ ids, at: Date.now() })} />
      <DeleteFilesDialog clips={selected.length ? selected : shown} open={deleteOpen} onClose={() => setDeleteOpen(false)} />
    </div>
  );
}
