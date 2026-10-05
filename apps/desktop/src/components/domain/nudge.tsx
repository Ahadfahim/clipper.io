import { useState } from "react";
import { useNudge } from "@/api/actions";
import { Button } from "@/components/ui/button";
import { TextArea } from "@/components/ui/fields";
import { Popover } from "@/components/ui/popover";

/** "Nudge" for an agent that looks stuck: a small popover with an optional message. The agent gets it first in
 * line, as "You look stuck" or your own words. Name a session (any role) or a campaign (its agent). */
export function NudgeButton({
  sessionId,
  campaignId,
  label = "Nudge",
  size = "sm",
  disabled,
  title,
  variant = "default",
}: {
  sessionId?: number;
  campaignId?: number;
  label?: string;
  size?: "sm" | "md";
  disabled?: boolean;
  title?: string;
  variant?: "default" | "primary" | "ghost";
}) {
  const nudge = useNudge();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const send = () => {
    if (nudge.isPending) return;
    nudge.mutate(
      { sessionId, campaignId, text: text.trim() },
      {
        onSuccess: () => {
          setText("");
          setOpen(false);
        },
      },
    );
  };
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      side="bottom"
      trigger={
        <Button size={size} variant={variant} disabled={disabled} title={title ?? "Tell the agent it looks stuck"}>
          {label}
        </Button>
      }
    >
      <div role="group" aria-label="Nudge the agent" className="flex w-[300px] flex-col gap-2">
        <label htmlFor="nudge-message" className="text-muted">
          Message (optional)
        </label>
        <TextArea
          id="nudge-message"
          rows={3}
          autoFocus
          value={text}
          maxLength={1000}
          placeholder="Tell the agent what to try. Leave it empty to say it looks stuck."
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send();
            }
            e.stopPropagation();
          }}
        />
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" disabled={nudge.isPending} onClick={send} shortcut="Ctrl+Enter">
            Nudge agent
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
        {nudge.error && <span className="text-bad">{nudge.error.message}</span>}
        <span className="text-[11px] text-muted">It reads this first, before anything else that is queued.</span>
      </div>
    </Popover>
  );
}
