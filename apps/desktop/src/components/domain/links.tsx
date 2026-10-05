import { LinkSquare16Regular, Warning16Regular } from "@fluentui/react-icons";
import { useState, type ReactNode } from "react";
import { useSkipCampaign } from "@/api/actions";
import { api, unwrap, type Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/cn";
import { openMarketplace } from "@/lib/tauri";

export type CampaignLink = Schemas["Link"];

/** A small icon button that opens a campaign's page on its marketplace (in Clipper's logged-in Chrome by
 * default). A warning icon replaces it when the marketplace said the page isn't there. */
export function CampaignLinkButton({
  link,
  status,
  checked,
  className,
}: {
  link: CampaignLink | null | undefined;
  /** ok | unavailable | unknown: did the page open when it was last read */
  status?: string;
  checked?: string | null;
  className?: string;
}) {
  if (!link) return null;
  const gone = status === "unavailable";
  const title = gone
    ? `${link.host} said this campaign isn't available${checked ? ` (checked ${new Date(checked).toLocaleString()})` : ""}. ${link.label}`
    : `${link.label} · ${link.host}`;
  return (
    <button
      type="button"
      title={title}
      aria-label={link.label}
      onClick={(e) => {
        e.stopPropagation();
        void openMarketplace(link);
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      className={cn(
        "inline-flex size-6 shrink-0 items-center justify-center rounded-[3px] hover:bg-panel-2",
        gone ? "text-warn" : "text-muted hover:text-accent",
        className,
      )}
    >
      {gone ? <Warning16Regular /> : <LinkSquare16Regular />}
    </button>
  );
}

/** Skip a campaign. When it has live posts that aren't submitted yet, skipping would drop what they could
 * earn, so this asks first: finish the submissions, skip anyway, or cancel. */
export function useSkipFlow(): { request: (id: number, title?: string) => void; dialog: ReactNode } {
  const skip = useSkipCampaign();
  const [pending, setPending] = useState<{ id: number; title?: string; count: number } | null>(null);
  const request = (id: number, title?: string) => {
    void (async () => {
      try {
        const pre = await unwrap(api.GET("/api/campaigns/{campaign_id}/skip-preview", { params: { path: { campaign_id: id } } }));
        if (pre.live_unsubmitted > 0) {
          setPending({ id, title, count: pre.live_unsubmitted });
          return;
        }
      } catch {
        /* no preview (fixture mode, offline): skipping is still allowed */
      }
      skip.mutate({ id, keepSubmitting: false });
    })();
  };
  const done = (keepSubmitting: boolean) => {
    if (pending) skip.mutate({ id: pending.id, keepSubmitting });
    setPending(null);
  };
  const dialog = (
    <Dialog
      open={pending !== null}
      onOpenChange={(o) => !o && setPending(null)}
      title="Skip this campaign?"
      width={500}
      description={
        pending
          ? `${pending.title ?? "This campaign"} has ${pending.count} live post${pending.count === 1 ? "" : "s"} that ${pending.count === 1 ? "isn't" : "aren't"} submitted yet. Skipping stops the submission, and that post can't earn.`
          : undefined
      }
      footer={
        <>
          <Button variant="primary" onClick={() => done(true)}>
            Skip and keep submitting
          </Button>
          <Button onClick={() => done(false)}>Skip anyway</Button>
          <Button onClick={() => setPending(null)}>Cancel</Button>
        </>
      }
    >
      <p className="m-0 text-muted">Keep submitting lets the campaign's agent send the live posts to the marketplace first, then end the campaign.</p>
    </Dialog>
  );
  return { request, dialog };
}
