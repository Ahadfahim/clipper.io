import { ArrowUndo16Regular, WindowNew16Regular } from "@fluentui/react-icons";
import { Link, useParams } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAddNote, useEditOp, useTakeOver, useUndo } from "@/api/actions";
import { useEditState, useManifest } from "@/api/queries";
import { fileUrl, FIXTURE_MODE, type Schemas } from "@/api/client";
import { qk } from "@/api/queries";
import { useLive } from "@/api/live";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Check, TextField } from "@/components/ui/fields";
import { DropdownMenu } from "@/components/ui/menu";
import { Empty, Toolbar, ToolbarSep } from "@/components/ui/misc";
import { Dot } from "@/components/ui/status";
import { AgendaPanel, EdlPreview, EditHistory, Timeline, actorIsAgent, type PreviewHandle } from "@/components/domain/edit";
import { cn } from "@/lib/cn";
import { asEdl, outputDuration, type IndexedWord } from "@/lib/edl";
import { duration, timecode } from "@/lib/format";
import { useHotkeys } from "@/lib/hotkeys";
import { popOut } from "@/lib/tauri";

const CAPTION_STYLES = ["bold-pop", "clean", "boxed", "karaoke"];

/**
 * Edit: watch Claude edit (violet range + status), steer it with notes, or take over and use
 * the manual tools; hand back and the agent continues from your version (UI.md §3.5b).
 */
export function EditScreen({ popout = false }: { popout?: boolean }) {
  const params = useParams({ strict: false }) as { clipId?: string };
  const clipId = Number(params.clipId);
  const st = useEditState(clipId).data;
  const manifest = useManifest().data;
  const live = useLive((s) => s.editStatus[clipId]);
  const op = useEditOp();
  const undo = useUndo();
  const takeOver = useTakeOver();
  const note = useAddNote();
  const qc = useQueryClient();
  const preview = useRef<PreviewHandle>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const [t, setT] = useState(0);
  const [mark, setMark] = useState<{ in: number | null; out: number | null }>({ in: null, out: null });
  const [selectedOp, setSelectedOp] = useState<number | null>(null);
  const [word, setWord] = useState<IndexedWord | null>(null);
  const [wordText, setWordText] = useState("");
  const [wordEmph, setWordEmph] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const [stageH, setStageH] = useState(420);
  useEffect(() => {
    const el = stage.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setStageH(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  });
  // the 9:16 preview fits the space above the timeline
  const previewWidth = Math.max(120, Math.min(popout ? 360 : 300, Math.floor(((stageH - 24) * 9) / 16)));

  const edl = useMemo(() => (st ? asEdl(st.edl) : null), [st]);
  const mine = st?.locked_by === "user";
  const agentText = mine ? null : (live?.text ?? st?.live_status ?? null);
  const agentRange = mine ? null : (live?.range ?? st?.live_range ?? null);
  const selection: [number, number] | null = mark.in !== null && mark.out !== null && mark.out > mark.in ? [mark.in, mark.out] : null;

  const run = (name: string, args: Record<string, unknown>, reason: string) => {
    op.mutate({ clipId, op: name, args, reason });
    if (FIXTURE_MODE) {
      // nothing is saved in fixture mode: show the step so the flow can be tried
      qc.setQueryData<Schemas["EditState"]>(qk.edit(clipId), (e) =>
        e
          ? { ...e, version: e.version + 1, history: [...e.history, { id: Date.now(), op: name, actor: "user", reason, ts: new Date().toISOString(), undone: false, version: e.version + 1 }] }
          : e,
      );
    }
  };
  const lastUndoable = [...(st?.history ?? [])].reverse().find((h) => !h.undone && h.op !== "init");

  useHotkeys(
    {
      space: () => preview.current?.toggle(),
      i: () => mine && setMark((m) => ({ ...m, in: t })),
      o: () => mine && setMark((m) => ({ ...m, out: t })),
      s: () => mine && run("split", { t }, `split at ${timecode(t)}`),
      delete: () => mine && selection && run("delete_range", { start: selection[0], end: selection[1] }, `delete ${timecode(selection[0])}–${timecode(selection[1])}`),
      "ctrl+z": () => lastUndoable && undo.mutate({ clipId, opId: lastUndoable.id }),
      n: () => noteRef.current?.focus(),
      t: () => takeOver.mutate({ clipId, take: !mine }),
    },
    Boolean(st),
  );

  if (!st || !edl) return <Empty>Loading the edit…</Empty>;
  const total = outputDuration(edl);
  const qa = st.clip.status;

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", popout && "h-full bg-bg")}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-chrome px-3 py-1.5">
        {!popout && (
          <Link to="/library/$clipId" params={{ clipId: String(clipId) }} className="text-muted hover:text-fg">
            Clip {clipId}
          </Link>
        )}
        <span className="font-semibold">{popout ? `Clip ${clipId}` : ""}</span>
        <span className="truncate-1 text-muted">
          · {st.clip.campaign_title} · v{st.version}
        </span>
        {agentText && (
          <span role="status" className="inline-flex h-6 items-center gap-1.5 rounded-[var(--radius)] bg-agent-soft px-2.5 text-agent">
            <Dot tone="agent" pulse />
            Claude is editing: {agentText.replace(/^Removing/, "removing")}
          </span>
        )}
        {mine && (
          <span role="status" className="inline-flex h-6 items-center gap-1.5 rounded-[var(--radius)] bg-accent-soft px-2.5">
            <Dot tone="accent" /> You have the clip. Claude waits until you hand it back.
          </span>
        )}
        <span className="flex-1" />
        {!popout && (
          <Button size="sm" variant="ghost" icon={<WindowNew16Regular />} onClick={() => void popOut("edit", clipId)}>
            Pop out
          </Button>
        )}
        <Button variant={mine ? "primary" : "default"} shortcut="T" onClick={() => takeOver.mutate({ clipId, take: !mine })}>
          {mine ? "Hand back to Claude" : "Take over"}
        </Button>
      </div>
      <Toolbar label="Edit tools">
        <Button variant="ghost" shortcut="S" disabled={!mine} onClick={() => run("split", { t }, `split at ${timecode(t)}`)}>
          Split
        </Button>
        <Button variant="ghost" shortcut="I" disabled={!mine} onClick={() => setMark((m) => ({ ...m, in: t }))}>
          Mark in
        </Button>
        <Button variant="ghost" shortcut="O" disabled={!mine} onClick={() => setMark((m) => ({ ...m, out: t }))}>
          Mark out
        </Button>
        <Button
          variant="ghost"
          shortcut="Del"
          disabled={!mine || !selection}
          onClick={() => selection && run("delete_range", { start: selection[0], end: selection[1] }, `delete ${timecode(selection[0])}–${timecode(selection[1])}`)}
        >
          Delete range
        </Button>
        <DropdownMenu
          items={(["crop", "split", "fit"] as const).map((l) => ({
            label: `${l[0]!.toUpperCase()}${l.slice(1)}${selection ? " (marked range)" : " (whole clip)"}`,
            onSelect: () => run("set_layout", { start: selection?.[0] ?? 0, end: selection?.[1] ?? total, layout: l }, `${l} layout ${selection ? `${timecode(selection[0])}–${timecode(selection[1])}` : "whole clip"}`),
          }))}
        >
          <Button variant="ghost" disabled={!mine}>
            Layout ▾
          </Button>
        </DropdownMenu>
        <DropdownMenu
          items={CAPTION_STYLES.map((s) => ({ kind: "check" as const, label: s, checked: edl.captions.style === s, onSelect: () => run("set_caption_style", { style: s }, `caption style ${s}`) }))}
        >
          <Button variant="ghost" disabled={!mine}>
            Captions ▾
          </Button>
        </DropdownMenu>
        <DropdownMenu
          items={[
            { label: "Text hook (first 2s)", onSelect: () => run("set_hook", { type: "text", text: st.clip.hook, seconds: 2 }, "text hook") },
            { label: "No hook", onSelect: () => run("set_hook", { type: "none" }, "remove hook") },
          ]}
        >
          <Button variant="ghost" disabled={!mine}>
            Hook ▾
          </Button>
        </DropdownMenu>
        <ToolbarSep />
        <Button variant="ghost" icon={<ArrowUndo16Regular />} shortcut="Ctrl+Z" disabled={!lastUndoable} onClick={() => lastUndoable && undo.mutate({ clipId, opId: lastUndoable.id })}>
          Undo
        </Button>
        {selection && (
          <span className="num text-muted">
            marked {timecode(selection[0])}–{timecode(selection[1])}
            <button type="button" className="ml-1.5 text-accent hover:underline" onClick={() => setMark({ in: null, out: null })}>
              clear
            </button>
          </span>
        )}
      </Toolbar>
      <div className={cn("flex min-h-0 flex-1", popout && "flex-col")}>
        {!popout && (
          <aside aria-label="History" className="flex min-h-0 w-[250px] shrink-0 flex-col border-r border-line bg-panel">
            <EditHistory history={st.history} liveText={agentText} selected={selectedOp} onSelect={setSelectedOp} onUndo={(opId) => undo.mutate({ clipId, opId })} />
          </aside>
        )}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div ref={stage} className="flex min-h-0 flex-1 items-center justify-center gap-4 overflow-hidden bg-media/40 p-3">
            <EdlPreview ref={preview} edl={edl} src={fileUrl(st.proxy_url, manifest)} poster={fileUrl(st.clip.thumb_url, manifest)} width={previewWidth} onTime={setT} />
            {st.variants.length > 0 && (
              <div className="flex flex-col gap-1.5" aria-label="Hook variants">
                <span className="text-muted">Hook variants</span>
                {st.variants.map((v) => (
                  <Link key={v.id} to="/edit/$clipId" params={{ clipId: String(v.id) }} className="text-accent hover:underline">
                    {v.variant_label ?? `Variant ${v.id}`}
                  </Link>
                ))}
              </div>
            )}
          </div>
          <Timeline
            edl={edl}
            t={t}
            onSeek={(x) => preview.current?.seek(x)}
            agentRange={agentRange}
            agentLabel={agentText}
            selection={selection}
            manual={mine}
            onWord={(w) => {
              setWord(w);
              setWordText(w.text);
              setWordEmph(w.emphasis);
            }}
          />
        </main>
        <aside aria-label="Agenda" className={cn("flex min-h-0 flex-col border-l border-line bg-panel", popout ? "h-[360px] border-t" : "w-[290px] shrink-0")}>
          <AgendaPanel
            plan={st.plan}
            notes={st.notes}
            noteRef={noteRef}
            onSend={(text, scope) =>
              note.mutate({
                text,
                scope,
                scope_id: scope === "clip" ? String(clipId) : scope === "campaign" ? String(st.clip.campaign_id ?? "") : null,
                pinned: false,
                campaign_id: st.clip.campaign_id,
              })
            }
          />
        </aside>
      </div>
      <footer className="flex h-6 shrink-0 items-center overflow-hidden border-t border-line bg-chrome text-[11px] whitespace-nowrap text-muted">
        <span className="border-r border-line px-2.5">Preview: proxy, drawn from the EDL (no render)</span>
        <span className="border-r border-line px-2.5">{mine ? "Locked by you" : st.locked_by ? `Locked by ${actorIsAgent(st.locked_by) ? "Claude" : st.locked_by}` : agentText ? "Claude is working" : "Unlocked"}</span>
        <span className="num border-r border-line px-2.5">
          {duration(total)} · {edl.output.width}×{edl.output.height} · {edl.output.fps} fps
        </span>
        <span className="px-2.5">Status: {qa.replace(/_/g, " ")}</span>
        <span className="flex-1" />
        <span className="truncate-1 px-2.5">Space play · I/O mark · S split · Del delete · Ctrl+Z undo · N note · T take over</span>
      </footer>
      <Dialog
        open={word !== null}
        onOpenChange={(o) => !o && setWord(null)}
        title="Caption word"
        width={380}
        footer={
          <>
            <Button
              variant="primary"
              onClick={() => {
                if (!word) return;
                if (wordText !== word.text) run("edit_caption_words", { edits: [{ index: word.index, text: wordText }] }, `caption “${word.text}” → “${wordText}”`);
                if (wordEmph !== word.emphasis) run("emphasize", { indices: [word.index], on: wordEmph }, `${wordEmph ? "emphasize" : "un-emphasize"} “${wordText}”`);
                setWord(null);
              }}
            >
              OK
            </Button>
            <Button onClick={() => setWord(null)}>Cancel</Button>
          </>
        }
      >
        <div className="flex flex-col gap-2.5">
          <label htmlFor="word-text" className="text-muted">
            Text (empty hides the word)
          </label>
          <TextField id="word-text" autoFocus value={wordText} onChange={(e) => setWordText(e.target.value)} />
          <Check checked={wordEmph} onChange={setWordEmph} label="Emphasize (color pop)" />
        </div>
      </Dialog>
    </div>
  );
}
