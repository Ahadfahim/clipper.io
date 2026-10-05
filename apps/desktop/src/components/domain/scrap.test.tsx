import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { withProviders } from "@/test/render";
import clips from "../../../public/fixtures/api/clips.json";
import { ScrapDialog } from "./scrap";

const rows = clips as unknown as Schemas["ClipRow"][];
const ready = rows.find((c) => c.status === "in_review")!;
const posted = rows.find((c) => c.status === "posted")!;

function check(over: Partial<Schemas["ScrapCheckOut"]> & { id: number }): Schemas["ScrapCheckOut"] {
  return { can_scrap: true, blocked_reason: null, status: "ready", hook: "", scheduled_posts: [], in_batch: null, editing_by: null, variants: [], bytes: 0, ...over };
}

/** Answers the preview and the scrap call; everything else is the real fixture client. */
function mockApi(preview: Schemas["ScrapPreviewOut"]) {
  const scrapped: unknown[] = [];
  const post = vi.spyOn(api, "POST").mockImplementation(((path: string, init: { body: unknown }) => {
    if (path === "/api/clips/scrap/preview") return Promise.resolve({ data: preview, response: new Response() });
    scrapped.push(init.body);
    return Promise.resolve({ data: { scrapped: (init.body as { clip_ids: number[] }).clip_ids, refused: [], bytes: 0 }, response: new Response() });
  }) as never);
  return { post, scrapped };
}

describe("ScrapDialog", () => {
  it("says why a posted clip can't be scrapped and doesn't count it", async () => {
    withProviders(<ScrapDialog clips={[ready, posted]} open onClose={() => undefined} onScrapped={() => undefined} />);
    const dialog = await screen.findByRole("dialog", { name: "Scrap 2 clips?" });
    expect(within(dialog).getByText(/Can't scrap a posted clip/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Scrap 1 clip" })).toBeEnabled();
  });

  it("with only a posted clip there is nothing to scrap", async () => {
    withProviders(<ScrapDialog clips={[posted]} open onClose={() => undefined} onScrapped={() => undefined} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Scrap 0 clips" })).toBeDisabled();
  });

  it("needs your say-so to cancel scheduled posts, and sends the reason you picked", async () => {
    const { scrapped } = mockApi({
      clips: [check({ id: ready.id, scheduled_posts: [4, 5], bytes: 50 * 1024 ** 2 })],
      scrappable: 1,
      bytes: 50 * 1024 ** 2,
      grace_days: 7,
    });
    const done = vi.fn();
    withProviders(<ScrapDialog clips={[ready]} open onClose={() => undefined} onScrapped={done} />);
    const dialog = await screen.findByRole("dialog", { name: "Scrap this clip?" });
    const go = await within(dialog).findByRole("button", { name: "Scrap 1 clip" });
    const cancel = await within(dialog).findByLabelText(/Cancel 2 scheduled posts/);
    expect(go).toBeDisabled();
    expect(within(dialog).getByText(/files are deleted after 7 days \(50 MB\)/)).toBeInTheDocument();
    fireEvent.click(cancel);
    expect(go).toBeEnabled();
    fireEvent.click(within(dialog).getByLabelText("Bad framing"));
    fireEvent.click(go);
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(scrapped[0]).toEqual({ clip_ids: [ready.id], reason: "Bad framing", include_variants: true, cancel_posts: true, via: "dashboard" });
    vi.restoreAllMocks();
  });

  it("offers to take the hook variants along, and leaves the reason out when you ask it to", async () => {
    const { scrapped } = mockApi({
      clips: [check({ id: ready.id, variants: [901, 902] }), check({ id: 901 }), check({ id: 902 })],
      scrappable: 3,
      bytes: 0,
      grace_days: 7,
    });
    withProviders(<ScrapDialog clips={[ready]} open onClose={() => undefined} onScrapped={() => undefined} />);
    const dialog = await screen.findByRole("dialog");
    const variants = await within(dialog).findByLabelText("Also scrap 2 hook variants");
    expect(within(dialog).getByRole("button", { name: "Scrap 3 clips" })).toBeEnabled();
    fireEvent.click(variants);
    expect(within(dialog).getByRole("button", { name: "Scrap 1 clip" })).toBeEnabled();
    fireEvent.click(within(dialog).getByLabelText("Tell the agents why"));
    expect(within(dialog).queryByLabelText("Weak hook")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Scrap 1 clip" }));
    await waitFor(() => expect(scrapped.length).toBe(1));
    expect(scrapped[0]).toMatchObject({ reason: null, include_variants: false, cancel_posts: false });
    vi.restoreAllMocks();
  });
});
