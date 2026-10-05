import { useEffect, useMemo, useState } from "react";
import { usePurge, useScrap } from "@/api/actions";
import { useCleanup, useScrapPreview } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Check, Radio, TextField } from "@/components/ui/fields";
import { Dot } from "@/components/ui/status";
import { bytesLabel, SCRAP_REASONS } from "@/lib/library";

type Row = Schemas["ClipRow"];
type Check_ = Schemas["ScrapCheckOut"];

/** What the confirm dialog shows when the server hasn't answered (yet): worked out from the cards. */
function localCheck(c: Row): Check_ {
  const posted = c.status === "posted" || c.platforms_posted.length > 0;
  return {
    id: c.id,
    can_scrap: !posted,
    blocked_reason: posted ? "Can't scrap a posted clip: its post counts toward earnings. Hide it instead." : null,
    status: c.status,
    hook: c.hook,
    scheduled_posts: [],
    in_batch: null,
    editing_by: null,
    variants: [],
    bytes: 0,
  };
}

/** Scrap clips: shows each clip with the reason it can't be (a posted clip), the options that apply (variants,
 * scheduled posts), an optional reason the agents learn from, and when the files are deleted. */
export function ScrapDialog({
  clips,
  open,
  onClose,
  onScrapped,
}: {
  clips: Row[];
  open: boolean;
  onClose: () => void;
  onScrapped: (res: Schemas["ScrapOut"]) => void;
}) {
  const ids = useMemo(() => clips.map((c) => c.id), [clips]);
  const [includeVariants, setIncludeVariants] = useState(true);
  const [cancelPosts, setCancelPosts] = useState(false);
  const [reason, setReason] = useState<string>(SCRAP_REASONS[0]);
  const [other, setOther] = useState("");
  const [useReason, setUseReason] = useState(true);
  const preview = useScrapPreview(ids, true, open); // always with variants: the checkbox says whether they come along
  const scrap = useScrap();
  useEffect(() => {
    if (open) {
      setIncludeVariants(true);
      setCancelPosts(false);
      setUseReason(true);
      setReason(SCRAP_REASONS[0]);
      setOther("");
    }
  }, [open]);

  const answered = preview.data && Array.isArray(preview.data.clips);
  const all: Check_[] = answered ? preview.data!.clips : clips.map(localCheck);
  const variantCount = all.filter((c) => !ids.includes(c.id)).length;
  const checks = includeVariants ? all : all.filter((c) => ids.includes(c.id));
  const byId = new Map(clips.map((c) => [c.id, c]));
  const ok = checks.filter((c) => c.can_scrap);
  const scheduled = checks.filter((c) => c.can_scrap && c.scheduled_posts.length > 0);
  const scheduledCount = scheduled.reduce((n, c) => n + c.scheduled_posts.length, 0);
  const blockedByScheduled = scheduled.length > 0 && !cancelPosts;
  const canGo = ok.length > 0 && !blockedByScheduled && !scrap.isPending;
  const days = answered ? preview.data!.grace_days : 7;
  const why = !useReason ? null : reason === "Other" ? other.trim() || null : reason;
  const bytes = ok.reduce((n, c) => n + c.bytes, 0);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={clips.length === 1 ? "Scrap this clip?" : `Scrap ${clips.length} clips?`}
      width={560}
      footer={
        <>
          <Button
            variant="primary"
            disabled={!canGo}
            onClick={() =>
              scrap.mutate(
                { ids, reason: why, includeVariants, cancelPosts },
                {
                  onSuccess: (res) => {
                    onScrapped({ ...res, scrapped: res.scrapped ?? ok.map((c) => c.id) });
                    onClose();
                  },
                },
              )
            }
          >
            {ok.length === 1 ? "Scrap 1 clip" : `Scrap ${ok.length} clips`}
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <ul className="m-0 flex max-h-44 list-none flex-col overflow-auto rounded-[var(--radius)] border border-line p-0">
          {checks.map((c) => (
            <li key={c.id} className="flex items-baseline gap-2 border-b border-line-soft px-2 py-1 last:border-b-0">
              <Dot tone={c.can_scrap ? "muted" : "bad"} />
              <span className="num w-14 shrink-0">Clip {c.id}</span>
              <span className="w-20 shrink-0 text-muted">{c.status.replace(/_/g, " ")}</span>
              <span className="min-w-0 flex-1 break-words">
                {c.can_scrap ? <span className="truncate-1 text-muted">{byId.get(c.id)?.hook ?? c.hook}</span> : <span className="text-bad">{c.blocked_reason}</span>}
              </span>
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-1">
          <Check checked={useReason} onChange={setUseReason} label="Tell the agents why" />
          {useReason && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 pl-5" role="radiogroup" aria-label="Reason">
              {[...SCRAP_REASONS, "Other"].map((r) => (
                <Radio key={r} name="scrap-reason" checked={reason === r} onChange={() => setReason(r)} label={r} />
              ))}
              {reason === "Other" && <TextField aria-label="Other reason" value={other} maxLength={200} onChange={(e) => setOther(e.target.value)} placeholder="What was wrong" className="w-56" />}
            </div>
          )}
        </div>
        {variantCount > 0 && <Check checked={includeVariants} onChange={setIncludeVariants} label={`Also scrap ${variantCount} hook variant${variantCount === 1 ? "" : "s"}`} />}
        {scheduledCount > 0 && (
          <Check checked={cancelPosts} onChange={setCancelPosts} label={`Cancel ${scheduledCount} scheduled post${scheduledCount === 1 ? "" : "s"} (needed to scrap ${scheduled.length === 1 ? "this clip" : "these clips"})`} />
        )}
        <p className="m-0 text-muted">
          Scrapped clips can't be posted. Their files are deleted after {days} day{days === 1 ? "" : "s"}{bytes > 0 ? ` (${bytesLabel(bytes)})` : ""}; you can restore a clip until then.
        </p>
        {scrap.error && <p className="m-0 text-bad">{scrap.error.message}</p>}
      </div>
    </Dialog>
  );
}

/** Clean up: groups of clips worth throwing away, each with the space it would free. */
export function CleanupDialog({ open, onClose, onScrapped }: { open: boolean; onClose: () => void; onScrapped: (ids: number[]) => void }) {
  const q = useCleanup(open);
  const groups = useMemo(() => q.data ?? [], [q.data]);
  const [off, setOff] = useState<Set<string>>(new Set());
  const scrap = useScrap();
  const purge = usePurge();
  const [freed, setFreed] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setOff(new Set());
      setFreed(null);
    }
  }, [open]);
  const on = groups.filter((g) => !off.has(g.key));
  const scrapIds = [...new Set(on.filter((g) => g.action === "scrap").flatMap((g) => g.clip_ids))];
  const fileGroups = on.filter((g) => g.action === "delete_files");
  const bytes = on.reduce((n, g) => n + g.bytes, 0);
  const busy = scrap.isPending || purge.isPending;
  const go = async () => {
    if (scrapIds.length) {
      const res = await scrap.mutateAsync({ ids: scrapIds, reason: "Clean up", includeVariants: false, cancelPosts: false });
      onScrapped(res.scrapped ?? scrapIds);
    }
    for (const g of fileGroups) await purge.mutateAsync({ ids: g.clip_ids, oldVersions: true });
    setFreed(bytesLabel(bytes));
    if (!fileGroups.length) onClose();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Clean up the Library"
      description="Things that are probably safe to throw away. Nothing is deleted until you press the button, and clips you scrap can be restored for a while."
      width={560}
      footer={
        <>
          <Button variant="primary" disabled={busy || (!scrapIds.length && !fileGroups.length)} onClick={() => void go()}>
            {scrapIds.length ? `Scrap ${scrapIds.length} clip${scrapIds.length === 1 ? "" : "s"} and free ${bytesLabel(bytes)}` : `Free ${bytesLabel(bytes)}`}
          </Button>
          <Button onClick={onClose}>{freed ? "Close" : "Cancel"}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-1">
        {q.isLoading && <span className="text-muted">Looking…</span>}
        {!q.isLoading && groups.length === 0 && <span className="text-muted">Nothing to clean up.</span>}
        {groups.map((g) => (
          <label key={g.key} className="flex items-center gap-2 border-b border-line-soft py-1.5 last:border-b-0">
            <input
              type="checkbox"
              checked={!off.has(g.key)}
              onChange={(e) => setOff((s) => (e.target.checked ? new Set([...s].filter((k) => k !== g.key)) : new Set([...s, g.key])))}
            />
            <span className="min-w-0 flex-1">{g.label}</span>
            <span className="num text-muted">{g.clip_ids.length}</span>
            <span className="num w-16 text-right">{bytesLabel(g.bytes)}</span>
          </label>
        ))}
        {freed && <p className="m-0 mt-2 text-muted">Freed {freed}.</p>}
        {(scrap.error || purge.error) && <p className="m-0 mt-2 text-bad">{(scrap.error ?? purge.error)?.message}</p>}
      </div>
    </Dialog>
  );
}

/** Delete the files of scrapped clips now: shows how much space that frees. */
export function DeleteFilesDialog({ clips, open, onClose }: { clips: Row[]; open: boolean; onClose: () => void }) {
  const purge = usePurge();
  const bytes = clips.reduce((n, c) => n + (c.bytes ?? 0), 0);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Delete files now?"
      width={460}
      description={`${clips.length} scrapped clip${clips.length === 1 ? "" : "s"}${bytes > 0 ? `, ${bytesLabel(bytes)}` : ""}. The thumbnails stay. These clips can't be restored afterwards.`}
      footer={
        <>
          <Button
            variant="danger"
            disabled={purge.isPending || clips.length === 0}
            onClick={() => purge.mutate({ ids: clips.map((c) => c.id) }, { onSuccess: onClose })}
          >
            Delete files
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </>
      }
    >
      <span className="sr-only">Deleting the files of scrapped clips frees disk space.</span>
    </Dialog>
  );
}
