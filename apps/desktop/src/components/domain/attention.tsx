import { ChevronDown16Regular, ChevronRight16Regular } from "@fluentui/react-icons";
import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { useDismiss, useReply, useSnooze } from "@/api/actions";
import { useManifest, useNeedsYouDetail } from "@/api/queries";
import { fileUrl, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Select, TextArea } from "@/components/ui/fields";
import { PropertyGrid } from "@/components/ui/misc";
import { Dot, type StatusTone } from "@/components/ui/status";
import { cn } from "@/lib/cn";
import { clock, relative } from "@/lib/format";
import { age, inlineActions, snoozeLabel, type NeedsAction, type NeedsItem } from "@/lib/needsYou";
import { nowMs } from "@/lib/now";

const KIND: Record<NeedsItem["kind"], { label: string; tone: StatusTone }> = {
  challenge: { label: "Blocked", tone: "bad" },
  question: { label: "Question", tone: "agent" },
  review: { label: "Review", tone: "warn" },
  campaign: { label: "Campaign", tone: "accent" },
  alert: { label: "Alert", tone: "warn" },
  failure: { label: "Failed", tone: "bad" },
};

const PRIMARY = new Set(["review", "take", "resume_account", "retry_job"]);
const SOON_MS = 2 * 3_600_000;
const REPLY: Record<Schemas["NeedsYouDetail"]["reply_to"], { label: string; placeholder: string; send: string; sent: string }> = {
  question: { label: "Something else", placeholder: "Answer in your own words", send: "Send answer", sent: "Answered." },
  campaign: { label: "Tell the agent", placeholder: "Tell the campaign agent what to do", send: "Send to the agent", sent: "Sent. The campaign's agent picks it up now." },
  director: { label: "Tell the Director", placeholder: "Tell the Director what to do", send: "Send to the Director", sent: "Sent to the Director." },
};

type OnAction = (action: NeedsAction, item: NeedsItem) => void;

/** "Needs you" grid: urgency order (blocked → questions → reviews → picks → alerts → failures). A row says what
 * it is in one or two lines and offers at most two buttons; opening it (click, Enter or →) shows everything
 * about it, every option, and a place for your own words. One row is open at a time. */
export function NeedsYouList({
  items,
  onAction,
  empty,
  openKey,
  onOpenKeyChange,
}: {
  items: NeedsItem[];
  onAction: OnAction;
  empty: string;
  /** The open row (controlled, e.g. from the URL). Leave out to let the list keep it. */
  openKey?: string | null;
  onOpenKeyChange?: (key: string | null) => void;
}) {
  const [local, setLocal] = useState<string | null>(null);
  const open = openKey !== undefined ? openKey : local;
  const setOpen = onOpenKeyChange ?? setLocal;
  const openItem = items.find((i) => i.key === open);

  // opened from a link (a toast, the tray): bring it into view
  useEffect(() => {
    if (open) document.querySelector(`[data-needs-row][data-key="${open}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.matches("input, textarea, select, [contenteditable]")) return;
    const row = target.closest<HTMLElement>("[data-needs-row]");
    // number keys answer the open question from anywhere inside the list
    if (/^[1-9]$/.test(e.key) && openItem?.kind === "question" && !e.ctrlKey && !e.altKey && !e.metaKey) {
      const a = openItem.actions[Number(e.key) - 1];
      if (a) {
        e.preventDefault();
        onAction(a, openItem);
      }
      return;
    }
    if (!row || target !== row) return;
    const rows = [...e.currentTarget.querySelectorAll<HTMLElement>("[data-needs-row]")];
    const i = rows.indexOf(row);
    const key = row.dataset["key"] ?? null;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        rows[i + 1]?.focus();
        break;
      case "ArrowUp":
        e.preventDefault();
        rows[i - 1]?.focus();
        break;
      case "Enter":
      case "ArrowRight":
        e.preventDefault();
        setOpen(key);
        break;
      case "ArrowLeft":
      case "Escape":
        if (open === key) {
          e.preventDefault();
          setOpen(null);
        }
        break;
    }
  };

  const cols = "20px 84px minmax(0,1fr) minmax(0,150px) 44px minmax(0,max-content)";
  return (
    <div role="table" aria-label="Needs you" onKeyDown={onKeyDown} className="overflow-hidden rounded-[var(--radius)] border border-line">
      <div role="row" className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
        <span role="columnheader" aria-label="Open" />
        <span role="columnheader" className="px-1">Type</span>
        <span role="columnheader" className="px-2">What needs you</span>
        <span role="columnheader" className="px-2">Campaign</span>
        <span role="columnheader" className="px-1 text-right">Age</span>
        <span role="columnheader" className="px-2">Action</span>
      </div>
      {items.length === 0 && <div className="border-t border-line bg-panel px-2 py-2 text-muted">{empty}</div>}
      {items.map((n) => {
        const k = KIND[n.kind];
        const isOpen = open === n.key;
        const timeout = n.timeout_at ? Date.parse(n.timeout_at) : null;
        const soon = timeout !== null && timeout - nowMs() <= SOON_MS;
        return (
          <div key={n.key} role="rowgroup" className="border-t border-line bg-panel">
            <div
              role="row"
              tabIndex={0}
              data-needs-row
              data-key={n.key}
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : n.key)}
              className={cn(
                "grid min-h-9 cursor-default items-center py-1 outline-none hover:bg-[color-mix(in_srgb,var(--fg)_4%,var(--panel))] focus-visible:bg-accent-soft",
                isOpen && "bg-[color-mix(in_srgb,var(--fg)_5%,var(--panel))]",
              )}
              style={{ gridTemplateColumns: cols }}
            >
              <span role="cell" className="flex justify-center text-muted">
                {isOpen ? <ChevronDown16Regular /> : <ChevronRight16Regular />}
              </span>
              <span role="cell" className="flex items-center gap-1.5 px-1">
                <Dot tone={k.tone} />
                {k.label}
              </span>
              <span role="cell" className="flex min-w-0 flex-col px-2">
                <span className="line-clamp-2 break-words" title={n.title}>
                  {n.title}
                </span>
                <span className="truncate-1 text-muted" title={n.detail}>
                  {n.detail}
                  {timeout !== null && <span className={cn(soon && "text-warn")}>{`${n.detail ? " · " : ""}times out ${relative(n.timeout_at)}`}</span>}
                </span>
              </span>
              <span role="cell" className="min-w-0 px-2">
                {n.campaign_id !== null && n.campaign_title && n.kind !== "campaign" && (
                  <button
                    type="button"
                    className="truncate-1 max-w-full text-left text-accent hover:underline"
                    title={`Open ${n.campaign_title}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onAction({ label: "Open campaign", action: "open_campaign", args: { campaign_id: n.campaign_id } }, n);
                    }}
                  >
                    {n.campaign_title}
                  </button>
                )}
              </span>
              <span role="cell" className="num px-1 text-right text-muted" title={n.since ? clock(n.since, false) : undefined}>
                {age(n.since)}
              </span>
              <span role="cell" className="flex min-w-0 flex-wrap justify-end gap-1 px-2" onClick={(e) => e.stopPropagation()}>
                {inlineActions(n).map((a) => (
                  <Button
                    key={a.label}
                    size="sm"
                    variant={PRIMARY.has(a.action) ? "primary" : "default"}
                    title={a.label}
                    className="max-w-[160px]"
                    onClick={() => (a.action === "expand" ? setOpen(n.key) : onAction(a, n))}
                  >
                    <span className="min-w-0 truncate">{a.label}</span>
                  </Button>
                ))}
              </span>
            </div>
            {isOpen && (
              <div role="region" aria-label={`Details: ${n.title}`} className="border-t border-line-soft bg-bg">
                <NeedsYouPanel item={n} onAction={onAction} onClose={() => setOpen(null)} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Caption({ children }: { children: ReactNode }) {
  return <h3 className="m-0 mb-1.5 text-[11px] font-semibold tracking-wide text-muted uppercase">{children}</h3>;
}

/** Everything about one item: what happened (text, facts, what the agent said, the evidence) on the left,
 * what to do (every option, your own words, snooze, dismiss) on the right. */
export function NeedsYouPanel({ item, onAction, onClose }: { item: NeedsItem; onAction: OnAction; onClose: () => void }) {
  const q = useNeedsYouDetail(item.key);
  const manifest = useManifest().data;
  const reply = useReply();
  const snooze = useSnooze();
  const dismiss = useDismiss();
  const [text, setText] = useState("");
  const d = q.data;

  if (q.isLoading) return <div className="px-4 py-3 text-muted">Loading…</div>;
  if (!d) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 text-muted">
        This isn't waiting on you any more.
        <Button size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    );
  }

  const r = REPLY[d.reply_to];
  const send = () => {
    const t = text.trim();
    if (!t || reply.isPending) return;
    reply.mutate({ key: item.key, text: t }, { onSuccess: () => setText("") });
  };
  const isQuestion = item.kind === "question";
  const rest = item.actions.filter((a) => a.action !== "open_campaign" || item.kind === "alert" || item.kind === "failure");

  return (
    <div className="@container px-4 py-3">
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 @[640px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <section aria-label="What happened" className="min-w-0">
          <Caption>What happened</Caption>
          <p className="selectable m-0 mb-2.5 break-words whitespace-pre-wrap">{d.body}</p>
          {d.facts.length > 0 && (
            <PropertyGrid
              labelWidth={96}
              className="mb-2.5 overflow-hidden rounded-[var(--radius)] border border-line"
              rows={d.facts.map((f): [ReactNode, ReactNode] => [
                f.label,
                f.at ? (
                  <span key={f.label} title={clock(f.at)}>
                    {relative(f.at)} <span className="num text-muted">· {clock(f.at, false)}</span>
                  </span>
                ) : (
                  f.value
                ),
              ])}
            />
          )}
          {d.agent && d.agent.messages.length > 0 && (
            <div className="mb-2.5">
              <Caption>
                The {d.agent.role} agent said <span className="font-normal normal-case">(session {d.agent.session_id}, {d.agent.status})</span>
              </Caption>
              <div className="flex flex-col gap-1 border-l-2 border-agent pl-2.5">
                {d.agent.messages.map((m, i) => (
                  <span key={i} className="voice selectable text-[13px] break-words whitespace-pre-wrap">
                    {m.text}
                  </span>
                ))}
              </div>
            </div>
          )}
          {d.thumbs.length > 0 && (
            <div className="mb-2.5 flex gap-1.5 overflow-hidden">
              {d.thumbs.map((t) => (
                <img key={t} src={fileUrl(t, manifest)} alt="" className="h-20 shrink-0 rounded-[3px] border border-line bg-media" />
              ))}
            </div>
          )}
          {d.evidence?.screenshot_url && (
            <img src={fileUrl(d.evidence.screenshot_url, manifest)} alt="What the browser showed" className="mb-2.5 max-h-48 max-w-full rounded-[3px] border border-line" />
          )}
          {d.evidence?.raw_tail && (
            <details className="mb-2.5">
              <summary className="cursor-default text-muted">Full output</summary>
              <pre className="selectable m-0 mt-1 max-h-48 overflow-auto rounded-[var(--radius)] border border-line bg-panel p-2 font-mono text-[11px] whitespace-pre-wrap">{d.evidence.raw_tail}</pre>
            </details>
          )}
          {d.timeline.length > 0 && (
            <details>
              <summary className="cursor-default text-muted">Timeline ({d.timeline.length})</summary>
              <div className="mt-1 flex flex-col">
                {d.timeline.map((t, i) => (
                  <div key={i} className="flex gap-2 border-b border-line-soft py-0.5">
                    <span className="num text-muted">{clock(t.ts, false)}</span>
                    <span className="selectable min-w-0 flex-1 break-words">{t.text}</span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </section>

        <section aria-label="What to do" className="min-w-0">
          <Caption>{isQuestion ? "Your answer" : "What to do"}</Caption>
          {isQuestion ? (
            <ol className="m-0 mb-3 flex list-none flex-col gap-1 p-0">
              {item.options.map((o, i) => (
                <li key={o}>
                  <button
                    type="button"
                    onClick={() => onAction(item.actions[i]!, item)}
                    className="flex w-full items-start gap-2 rounded-[var(--radius)] border border-line bg-panel-2 px-2 py-1.5 text-left hover:bg-[color-mix(in_srgb,var(--panel-2)_80%,var(--fg)_8%)]"
                  >
                    <span className="num w-3 shrink-0 text-muted">{i + 1}</span>
                    <span className="min-w-0 break-words">{o}</span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            rest.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {rest.map((a) => (
                  <Button key={a.label} variant={PRIMARY.has(a.action) ? "primary" : "default"} onClick={() => onAction(a, item)}>
                    {a.label}
                  </Button>
                ))}
              </div>
            )
          )}

          <label htmlFor={`reply-${item.key}`} className="mb-1 block text-muted">
            {r.label}
          </label>
          <TextArea
            id={`reply-${item.key}`}
            rows={3}
            value={text}
            placeholder={r.placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                send();
              }
              e.stopPropagation(); // typing must not trigger the list's shortcuts
            }}
            className="w-full"
          />
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!text.trim() || reply.isPending} onClick={send} shortcut="Ctrl+Enter">
              {r.send}
            </Button>
            {reply.isSuccess && !text && reply.data.routed_to !== "question" && <span className="text-muted">{r.sent}</span>}
            {reply.error && <span className="text-bad">{reply.error.message}</span>}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
            <label htmlFor={`snooze-${item.key}`} className="text-muted">
              Hide for
            </label>
            <Select
              id={`snooze-${item.key}`}
              value=""
              className="h-[var(--control-sm)] w-28"
              onChange={(e) => e.target.value && snooze.mutate({ key: item.key, minutes: Number(e.target.value) })}
            >
              <option value="">Choose…</option>
              {d.snooze_options.map((m) => (
                <option key={m} value={m}>
                  {snoozeLabel(m)}
                </option>
              ))}
            </Select>
            {item.dismissable && (
              <Button size="sm" onClick={() => dismiss.mutate(item.key)}>
                Dismiss
              </Button>
            )}
            {isQuestion && d.agent && (
              <Button size="sm" variant="ghost" onClick={() => onAction({ label: "Open transcript", action: "open_session", args: { session_id: d.agent?.session_id } }, item)}>
                Open transcript
              </Button>
            )}
            <span className="flex-1" />
            <Button size="sm" variant="ghost" onClick={onClose}>
              Close
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}

/** An agent's question with its answer buttons and timeout (Home, Discord). Answering resumes the agent. */
export function AskUserCard({ q, onAnswer, className }: { q: Schemas["QuestionOut"]; onAnswer: (answer: string) => void; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1.5 rounded-[var(--radius)] border border-line bg-panel px-3 py-2", className)}>
      <div className="flex items-center gap-1.5 text-muted">
        <Dot tone="agent" />
        Question from the agent{q.campaign_id ? ` · campaign ${q.campaign_id}` : ""}
        {q.timeout_at && <span className="ml-auto">times out {relative(q.timeout_at)}</span>}
      </div>
      <div>{q.text}</div>
      {q.status === "open" ? (
        <div className="flex flex-wrap gap-1">
          {q.options.map((o) => (
            <Button key={o} size="sm" onClick={() => onAnswer(o)}>
              {o}
            </Button>
          ))}
        </div>
      ) : (
        <div className="text-muted">Answered: {q.answer}</div>
      )}
    </div>
  );
}
