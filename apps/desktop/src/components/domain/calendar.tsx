import { DndContext, PointerSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragOverEvent } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { canDrop, dayStart, moveToDay, weekDays, type DropCheck } from "@/lib/calendar";
import { clock } from "@/lib/format";
import { nowMs } from "@/lib/now";
import { Check } from "@/components/ui/fields";
import { AccountChip } from "./badges";
import type { Schemas } from "@/api/client";

const dayFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });

function PostCard({ post, thumb, disabled }: { post: Schemas["PostOut"]; thumb?: string; disabled: boolean }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: `post-${post.id}`, data: { post }, disabled });
  const live = post.status === "live" || post.status === "simulated";
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      aria-label={`Clip ${post.clip_id} at ${clock(post.scheduled_at, false)}, ${post.status}`}
      style={{ transform: CSS.Translate.toString(transform) }}
      className={cn(
        "flex h-7 items-center gap-1.5 overflow-hidden rounded-[3px] border bg-panel pr-1.5",
        live ? "border-line text-muted" : post.status === "cancelled" ? "border-dashed border-line text-faint line-through" : "border-line",
        !disabled && "cursor-grab active:cursor-grabbing",
        isDragging && "z-20 opacity-80 shadow-lg",
      )}
    >
      {thumb ? <img src={thumb} alt="" className="h-full w-[16px] object-cover" /> : <span className="h-full w-[16px] bg-media" />}
      <span className="num">{clock(post.scheduled_at, false)}</span>
      <span className="truncate-1 text-muted">#{post.clip_id}</span>
      {post.dry_run && <span className="ml-auto text-[10px] text-warn">dry</span>}
    </div>
  );
}

function DayCell({ id, check, children }: { id: string; check: DropCheck | null; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id });
  return (
    <div
      ref={setNodeRef}
      title={isOver && check && !check.ok ? check.reason : undefined}
      className={cn(
        "flex min-h-[38px] flex-col gap-1 border-l border-line-soft p-1",
        isOver && check?.ok && "bg-accent-soft outline-1 -outline-offset-1 outline-accent",
        isOver && check && !check.ok && "bg-bad-soft outline-2 -outline-offset-2 outline-bad",
      )}
    >
      {children}
    </div>
  );
}

/**
 * Week view, one lane per account. Drag a scheduled post to another day; the cap and minimum-gap
 * rules are checked while dragging (red outline = not allowed). Disabled lanes collapse.
 */
export function CalendarLanes({
  data,
  thumbFor,
  onReschedule,
  onToggleAccount,
}: {
  data: Schemas["CalendarOut"];
  thumbFor: (p: Schemas["PostOut"]) => string | undefined;
  onReschedule: (postId: number, iso: string) => void;
  onToggleAccount: (accountId: number, on: boolean) => void;
}) {
  const now = nowMs();
  const days = weekDays(now - 86_400_000, 7);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const [check, setCheck] = useState<DropCheck | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const accById = new Map(data.accounts.map((a) => [a.id, a]));

  const evaluate = (e: DragOverEvent | DragEndEvent): { check: DropCheck; iso: string; post: Schemas["PostOut"] } | null => {
    const post = (e.active.data.current as { post?: Schemas["PostOut"] } | undefined)?.post;
    const over = e.over?.id ? String(e.over.id) : null;
    if (!post || !over) return null;
    const [, accId, day] = over.split(":");
    const acc = accById.get(Number(accId));
    if (!acc) return null;
    const iso = moveToDay(post.scheduled_at, Number(day));
    if (acc.id !== post.account_id) return { check: { ok: false, reason: "Posts can't move between accounts" }, iso, post };
    return { check: canDrop(post, acc, data.posts, iso, now), iso, post };
  };

  const cols = `220px repeat(${days.length}, minmax(96px, 1fr))`;
  return (
    <DndContext
      sensors={sensors}
      onDragOver={(e) => setCheck(evaluate(e)?.check ?? null)}
      onDragEnd={(e) => {
        const r = evaluate(e);
        setCheck(null);
        if (!r) return;
        if (r.check.ok && r.iso !== r.post.scheduled_at) {
          onReschedule(r.post.id, r.iso);
          setMessage(null);
        } else if (!r.check.ok) setMessage(r.check.reason ?? "Not allowed");
      }}
      onDragCancel={() => setCheck(null)}
    >
      <div className="flex min-h-0 flex-col">
        {message && (
          <div role="status" className="mb-1.5 text-bad">
            Can't move there: {message}
          </div>
        )}
        <div role="grid" aria-label="Posting calendar" className="overflow-auto rounded-[var(--radius)] border border-line bg-panel">
          <div role="row" className="sticky top-0 z-10 grid h-[26px] items-center border-b border-line bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
            <span role="columnheader" className="px-2">Account</span>
            {days.map((d) => (
              <span key={d} role="columnheader" className={cn("border-l border-line-soft px-2", dayStart(now) === d && "font-semibold text-fg")}>
                {dayStart(now) === d ? "Today" : dayFmt.format(new Date(d))}
              </span>
            ))}
          </div>
          {data.accounts.map((a) => {
            const platformOn = data.platforms_enabled[a.platform] ?? true;
            const on = a.enabled && platformOn;
            const posts = data.posts.filter((p) => p.account_id === a.id);
            return (
              <div key={a.id} role="row" className={cn("grid border-b border-line-soft", !on && "opacity-60")} style={{ gridTemplateColumns: cols }}>
                <div role="rowheader" className="flex flex-col justify-center gap-0.5 px-2 py-1">
                  <AccountChip platform={a.platform} handle={a.handle} status={a.status} enabled={on} />
                  <span className="flex items-center gap-2 text-muted">
                    <Check checked={a.enabled} disabled={!platformOn} onChange={(v) => onToggleAccount(a.id, v)} label={platformOn ? "On" : "Social off"} className="px-0" />
                    <span className="num">
                      {a.posts_today}/{a.cap_today} today
                    </span>
                    {a.status !== "active" && <span className="text-warn">{a.paused_reason ?? a.status}</span>}
                  </span>
                </div>
                {on
                  ? days.map((d) => (
                      <DayCell key={d} id={`cell:${a.id}:${d}`} check={check}>
                        {posts
                          .filter((p) => dayStart(Date.parse(p.scheduled_at)) === d)
                          .sort((x, y) => x.scheduled_at.localeCompare(y.scheduled_at))
                          .map((p) => (
                            <PostCard key={p.id} post={p} thumb={thumbFor(p)} disabled={p.status !== "scheduled" || Date.parse(p.scheduled_at) < now} />
                          ))}
                      </DayCell>
                    ))
                  : <div className="col-span-7 flex items-center border-l border-line-soft px-2 text-muted">{platformOn ? "Account off" : "Social switched off"}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </DndContext>
  );
}
