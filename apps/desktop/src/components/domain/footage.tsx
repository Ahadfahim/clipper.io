import { ArrowUpload16Regular, FolderOpen16Regular } from "@fluentui/react-icons";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { inspectFile, useAttachFile } from "@/api/actions";
import { useSourceCandidates } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Check, TextField } from "@/components/ui/fields";
import { Progress } from "@/components/ui/misc";
import { cn } from "@/lib/cn";
import { cleanPath, fileName, pickVideo, registerDropZone, VIDEO_EXTENSIONS } from "@/lib/filedrop";
import { duration } from "@/lib/format";
import { bytesLabel } from "@/lib/library";
import { age } from "@/lib/needsYou";
import { IN_TAURI, openPath, pickFile } from "@/lib/tauri";

const BROWSER_NOTE = "A browser can't tell where a dropped file lives. Paste its path below, or use the Clipper desktop app.";

function ago(iso: string): string {
  const a = age(iso);
  return a === "now" ? "just now" : `${a} ago`;
}

/** Hand Clipper the video for a source it can't download. Drop the file on the box (desktop app), choose it,
 * paste its path, or pick one of the videos you downloaded recently. A file that looks wrong (much shorter than
 * the campaign's clips) is shown back to you before it is used. The copy runs as a job: its progress shows here. */
export function FootageDrop({
  sourceId,
  campaignId,
  dropFolder,
  activity,
  importing = false,
}: {
  sourceId: number;
  campaignId: number | null;
  dropFolder?: string | null;
  /** The file being copied in right now (the Needs you item carries it). */
  activity?: Schemas["JobActivity"] | null;
  /** Same thing, for a source in the campaign drawer. */
  importing?: boolean;
}) {
  const attach = useAttachFile(campaignId);
  const [over, setOver] = useState(false);
  const [text, setText] = useState("");
  const [move, setMove] = useState(false);
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ path: string; info: Schemas["InspectOut"] } | null>(null);
  const [added, setAdded] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const seen = useRef(false);
  const busy = Boolean(activity) || importing || added !== null;
  const candidates = useSourceCandidates(sourceId, !busy);

  const add = (path: string) =>
    attach.mutate(
      { sourceId, path, move },
      {
        onSuccess: () => {
          setAdded(fileName(path));
          setText("");
          setConfirm(null);
          setProblem(null);
        },
        onError: (e) => setProblem(e.message),
      },
    );

  const choose = async (raw: string) => {
    const path = cleanPath(raw);
    if (!path) return;
    setProblem(null);
    setConfirm(null);
    setChecking(true);
    try {
      const info = await inspectFile(sourceId, path);
      if (Array.isArray(info.warnings) && info.warnings.length > 0) setConfirm({ path, info });
      else add(path);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Couldn't read that file.");
    } finally {
      setChecking(false);
    }
  };
  // the drop zone is registered once; it must call the newest closure
  const chooseRef = useRef(choose);
  chooseRef.current = choose;

  useEffect(() => {
    return registerDropZone({
      el: () => box.current,
      onHover: setOver,
      onDrop: (paths) => {
        const picked = pickVideo(paths);
        if ("error" in picked) setProblem(picked.error);
        else void chooseRef.current(picked.path);
      },
    });
  }, []);

  // once the copy has been seen running and is over, the zone comes back (it stays hidden if the item is gone)
  useEffect(() => {
    if (activity || importing) seen.current = true;
    else if (added !== null && seen.current) {
      seen.current = false;
      setAdded(null);
    }
  }, [activity, importing, added]);
  useEffect(() => {
    if (added === null) return;
    const t = setTimeout(() => setAdded(null), 20_000);
    return () => clearTimeout(t);
  }, [added]);

  const browse = async () => {
    const path = await pickFile("Video", VIDEO_EXTENSIONS);
    if (path) void choose(path);
  };
  // in a browser the drop carries no path: say so instead of doing nothing
  const htmlDrop = IN_TAURI
    ? {}
    : {
        onDragOver: (e: DragEvent) => {
          e.preventDefault();
          setOver(true);
        },
        onDragLeave: () => setOver(false),
        onDrop: (e: DragEvent) => {
          e.preventDefault();
          setOver(false);
          setProblem(BROWSER_NOTE);
        },
      };

  const recent = candidates.data ?? [];
  const pct = Math.round((activity?.progress ?? 0) * 100);

  return (
    <div className="flex flex-col gap-2">
      {busy ? (
        <div role="status" className="flex flex-col gap-1.5 rounded-[var(--radius)] border border-line bg-panel px-3 py-2.5">
          <span className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate">{added ? `Adding ${added}` : (activity?.label ?? "Adding your file")}</span>
            <span className="num text-muted">{pct}%</span>
          </span>
          <Progress value={pct / 100} label="Adding the file" />
          <span className="text-muted">Clipper copies it into the campaign's folder, checks it, then the campaign's agent carries on.</span>
        </div>
      ) : (
        <>
          <div
            ref={box}
            role="group"
            aria-label="Drop the video file here"
            {...htmlDrop}
            className={cn(
              "flex flex-col items-center gap-1.5 rounded-[var(--radius)] border border-dashed px-3 py-3.5 text-center",
              over ? "border-accent bg-accent-soft" : "border-[color-mix(in_srgb,var(--fg)_32%,var(--line))] bg-panel",
            )}
          >
            <ArrowUpload16Regular className={over ? "text-accent" : "text-muted"} />
            <span>{over ? "Release to use this file" : "Drop the video file here"}</span>
            {IN_TAURI && (
              <Button size="sm" disabled={checking} onClick={() => void browse()}>
                Choose file…
              </Button>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <TextField
              aria-label="Path of the video file"
              className="flex-1"
              value={text}
              placeholder="Or paste the file's path, C:\Users\you\Downloads\episode.mp4"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && text.trim()) {
                  e.preventDefault();
                  void choose(text);
                }
                e.stopPropagation(); // typing must not trigger the list's shortcuts
              }}
            />
            <Button size="sm" disabled={!text.trim() || checking} onClick={() => void choose(text)}>
              Use this file
            </Button>
          </div>
        </>
      )}

      {confirm && (
        <div role="alert" className="flex flex-col gap-1.5 rounded-[var(--radius)] border border-warn bg-warn-soft px-3 py-2">
          <span className="font-semibold">{fileName(confirm.path)}</span>
          {confirm.info.warnings.map((w) => (
            <span key={w.code}>{w.text}</span>
          ))}
          <span className="flex gap-1.5">
            <Button size="sm" variant="primary" onClick={() => add(confirm.path)}>
              Use anyway
            </Button>
            <Button size="sm" onClick={() => setConfirm(null)}>
              Choose another
            </Button>
          </span>
        </div>
      )}
      {problem && <span className="text-bad">{problem}</span>}

      {!busy && (
        <Check
          checked={move}
          onChange={setMove}
          label="Move the file instead of copying it"
          title="Saves disk space. The original is no longer in its folder afterwards."
        />
      )}

      {!busy && recent.length > 0 && (
        <div>
          <h4 className="m-0 mb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">Recent downloads</h4>
          <ul className="m-0 flex list-none flex-col p-0">
            {recent.map((c) => (
              <li key={c.path} className="flex items-center gap-2 border-b border-line-soft py-1">
                <span className="min-w-0 flex-1 truncate" title={c.path}>
                  {c.name}
                </span>
                <span className="num shrink-0 text-muted">
                  {bytesLabel(c.size)}
                  {c.duration ? ` · ${duration(c.duration)}` : ""} · {ago(c.modified)}
                </span>
                <Button size="sm" disabled={checking} onClick={() => void choose(c.path)} aria-label={`Use ${c.name}`}>
                  Use
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dropFolder && (
        <div className="flex items-center gap-2 text-muted">
          <span className="shrink-0">Drop folder</span>
          <span className="num truncate-1 flex-1 text-[11px]" title={dropFolder}>
            {dropFolder}
          </span>
          <Button size="sm" icon={<FolderOpen16Regular />} onClick={() => void openPath(dropFolder)}>
            Open folder
          </Button>
        </div>
      )}
    </div>
  );
}
