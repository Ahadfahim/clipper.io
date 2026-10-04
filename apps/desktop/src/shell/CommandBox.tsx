import * as D from "@radix-ui/react-dialog";
import { Command as Cmdk } from "cmdk";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useDirectorChat } from "@/api/actions";
import { useCampaigns, useClips, useDirector } from "@/api/queries";
import { clock } from "@/lib/format";
import { MARKET_LABEL } from "@/lib/platforms";
import { useUi } from "@/state/ui";
import type { Command } from "./commands";

const NONE: never[] = [];

const item =
  "flex h-7 cursor-default items-center gap-2 rounded-[3px] px-2 data-[selected=true]:bg-accent-soft data-[disabled=true]:text-faint";

/**
 * Ctrl+K: jump to any campaign or clip, run any command, flip any switch ("turn off whop"), or
 * start with `>` to message the Director (the same conversation as #control in Discord).
 */
export function CommandBox({ commands }: { commands: Command[] }) {
  const open = useUi((s) => s.commandOpen);
  const seed = useUi((s) => s.commandSeed);
  const close = useUi((s) => s.closeCommand);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const campaigns = useCampaigns().data ?? [];
  const clips = useClips().data ?? [];
  const director = useDirector().data ?? NONE;
  const chat = useDirectorChat();
  const input = useRef<HTMLInputElement>(null);
  const director_mode = q.startsWith(">");

  useEffect(() => {
    if (open) setQ(seed);
  }, [open, seed]);

  const recent = useMemo(() => director.slice(-6), [director]);
  const run = (fn: () => void) => {
    close();
    fn();
  };

  return (
    <D.Root open={open} onOpenChange={(o) => !o && close()}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/20" />
        <D.Content
          className="fixed top-[12%] left-1/2 z-50 w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-[var(--radius)] border border-line bg-panel shadow-[0_16px_48px_rgba(0,0,0,0.35)]"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            input.current?.focus();
          }}
        >
          <D.Title className="sr-only">Search and commands</D.Title>
          <D.Description className="sr-only">Type to search, or start with &gt; to message the Director.</D.Description>
          <Cmdk shouldFilter={!director_mode} loop label="Search and commands">
            <div className="flex items-center gap-2 border-b border-line px-3">
              <span className="num text-muted">{director_mode ? ">" : "⌕"}</span>
              <Cmdk.Input
                ref={input}
                value={director_mode ? q.slice(1) : q}
                onValueChange={(v) => setQ(director_mode ? `>${v}` : v)}
                onKeyDown={(e) => {
                  if (director_mode && e.key === "Backspace" && q === ">") setQ("");
                  if (director_mode && e.key === "Enter" && q.slice(1).trim()) {
                    e.preventDefault();
                    chat.mutate(q.slice(1).trim());
                    setQ(">");
                  }
                }}
                placeholder={director_mode ? "Message the Director (Enter to send)" : "Search campaigns, clips and commands · > to message the Director"}
                className="h-10 flex-1 bg-transparent outline-none placeholder:text-muted"
              />
              <span className="num text-[11px] text-muted">Esc</span>
            </div>
            {director_mode ? (
              <div className="flex max-h-[360px] flex-col gap-2 overflow-auto p-3" aria-live="polite">
                {recent.length === 0 && <div className="text-muted">Ask about earnings, campaigns or clips, or tell the agents what to do.</div>}
                {recent.map((m) => (
                  <div key={m.id} className={m.type === "user" ? "self-end text-right" : ""}>
                    <div className="text-[11px] text-muted">
                      {m.type === "user" ? "You" : "Director"} · {clock(m.ts, false)}
                    </div>
                    <div className={m.type === "user" ? "rounded-[var(--radius)] bg-accent-soft px-2 py-1" : "voice selectable text-[13px]"}>{m.text}</div>
                  </div>
                ))}
                {chat.isPending && <div className="text-muted">Sending…</div>}
              </div>
            ) : (
              <Cmdk.List className="max-h-[400px] overflow-auto p-1">
                <Cmdk.Empty className="px-3 py-4 text-muted">No matches. Start with &gt; to ask the Director.</Cmdk.Empty>
                <Cmdk.Group heading="Commands" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted">
                  {commands.map((c) => (
                    <Cmdk.Item key={c.id} value={`${c.label} ${c.group}`} disabled={c.disabled} onSelect={() => run(c.run)} className={item}>
                      <span className="flex-1">
                        {c.label}
                        {c.checked !== undefined && <span className="text-muted"> ({c.checked ? "on" : "off"})</span>}
                      </span>
                      {c.shortcut && <span className="num text-[11px] text-muted">{c.shortcut}</span>}
                    </Cmdk.Item>
                  ))}
                </Cmdk.Group>
                <Cmdk.Group heading="Campaigns" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted">
                  {campaigns.map((c) => (
                    <Cmdk.Item key={c.id} value={`campaign ${c.title} ${c.brand ?? ""} ${c.marketplace}`} onSelect={() => run(() => void navigate({ to: "/campaigns", search: { open: c.id } }))} className={item}>
                      <span className="flex-1">{c.title}</span>
                      <span className="text-muted">{MARKET_LABEL[c.marketplace]} · {c.status}</span>
                    </Cmdk.Item>
                  ))}
                </Cmdk.Group>
                <Cmdk.Group heading="Clips" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:text-muted">
                  {clips.map((c) => (
                    <Cmdk.Item key={c.id} value={`clip ${c.id} ${c.hook} ${c.campaign_title ?? ""}`} onSelect={() => run(() => void navigate({ to: "/library/$clipId", params: { clipId: String(c.id) } }))} className={item}>
                      <span className="num w-8 text-muted">#{c.id}</span>
                      <span className="flex-1 truncate-1">{c.hook}</span>
                      <span className="text-muted">{c.campaign_title}</span>
                    </Cmdk.Item>
                  ))}
                </Cmdk.Group>
              </Cmdk.List>
            )}
          </Cmdk>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
