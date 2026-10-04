import { cn } from "@/lib/cn";
import { relative } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Dot, type StatusTone } from "@/components/ui/status";
import type { Schemas } from "@/api/client";

const KIND: Record<Schemas["NeedsYouItem"]["kind"], { label: string; tone: StatusTone }> = {
  challenge: { label: "Blocked", tone: "bad" },
  question: { label: "Question", tone: "agent" },
  review: { label: "Review", tone: "warn" },
  campaign: { label: "Campaign", tone: "accent" },
  failure: { label: "Failed", tone: "bad" },
};

const PRIMARY = new Set(["review", "take", "resume_account"]);

/** "Needs you" grid: urgency order (blocked → reviews → questions → picks → failures), actions inline.
 * The question or title gets the full width of its row and the actions sit under it, so a long
 * answer never pushes the text it answers out of view. */
export function NeedsYouList({
  items,
  onAction,
  empty,
}: {
  items: Schemas["NeedsYouItem"][];
  onAction: (action: Schemas["NeedsYouAction"], item: Schemas["NeedsYouItem"]) => void;
  empty: string;
}) {
  const cols = "92px minmax(0,1fr)";
  return (
    <div role="table" aria-label="Needs you" className="overflow-hidden rounded-[var(--radius)] border border-line">
      <div role="row" className="grid h-[26px] items-center bg-panel-2 text-muted" style={{ gridTemplateColumns: cols }}>
        <span role="columnheader" className="px-2">Type</span>
        <span role="columnheader" className="px-2">What needs you</span>
      </div>
      {items.length === 0 && <div className="border-t border-line bg-panel px-2 py-2 text-muted">{empty}</div>}
      {items.map((n, i) => {
        const k = KIND[n.kind];
        const detail = n.detail.replace(/times out (\S+)$/, (_m, iso: string) => `times out ${relative(iso)}`);
        return (
          <div key={i} role="row" className="grid items-start border-t border-line bg-panel py-1.5" style={{ gridTemplateColumns: cols }}>
            <span role="cell" className="flex items-center gap-1.5 px-2 py-0.5">
              <Dot tone={k.tone} />
              {k.label}
            </span>
            <span role="cell" className="flex min-w-0 flex-col gap-1 px-2">
              <span className="selectable line-clamp-3 break-words" title={n.title}>{n.title}</span>
              {detail && (
                <span className="line-clamp-2 break-words text-muted" title={n.detail}>
                  {detail}
                </span>
              )}
              {n.actions.length > 0 && (
                <span className="flex flex-wrap gap-1 pt-0.5">
                  {n.actions.map((a) => (
                    <Button
                      key={a.label}
                      size="sm"
                      variant={PRIMARY.has(a.action) ? "primary" : "default"}
                      title={a.label}
                      className="max-w-full"
                      onClick={() => onAction(a, n)}
                    >
                      <span className="min-w-0 truncate">{a.label}</span>
                    </Button>
                  ))}
                </span>
              )}
            </span>
          </div>
        );
      })}
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
