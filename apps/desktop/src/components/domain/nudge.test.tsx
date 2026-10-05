import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { withProviders } from "@/test/render";
import boardJson from "../../../public/fixtures/api/agents/board.json";
import jobsJson from "../../../public/fixtures/api/jobs.json";
import needsJson from "../../../public/fixtures/api/needs-you.json";
import { StageStepper } from "./meters";
import { NudgeButton } from "./nudge";
import { NeedsYouList } from "./attention";
import { SlotBoard } from "./agents";

const boardFixture = boardJson as unknown as Schemas["BoardOut"];
const jobsFixture = jobsJson as unknown as Schemas["JobOut"][];
const needsFixture = needsJson as unknown as Schemas["NeedsYouItem"][];

function mockPost(data: unknown = { ok: true, id: 1, detail: "nudged" }) {
  return vi.spyOn(api, "POST").mockResolvedValue({ data, response: new Response() } as never);
}

afterEach(() => vi.restoreAllMocks());

describe("NudgeButton", () => {
  it("nudges a session with your own words and closes", async () => {
    const post = mockPost();
    withProviders(<NudgeButton sessionId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Nudge" }));
    const box = await screen.findByLabelText("Message (optional)");
    fireEvent.change(box, { target: { value: "  Use the second source  " } });
    fireEvent.click(screen.getByRole("button", { name: /Nudge agent/ }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/agents/sessions/{session_id}/nudge", { params: { path: { session_id: 7 } }, body: { text: "Use the second source" } });
    await waitFor(() => expect(screen.queryByRole("group", { name: "Nudge the agent" })).toBeNull());
  });

  it("sends Ctrl+Enter, and nudges a campaign's agent with no message to say it looks stuck", async () => {
    const post = mockPost();
    withProviders(<NudgeButton campaignId={3} label="Nudge agent" />);
    fireEvent.click(screen.getByRole("button", { name: "Nudge agent" }));
    const box = await screen.findByLabelText("Message (optional)");
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/campaigns/{campaign_id}/nudge", { params: { path: { campaign_id: 3 } }, body: { text: "" } });
  });

  it("says why when the nudge is refused and keeps the message", async () => {
    vi.spyOn(api, "POST").mockResolvedValue({ error: { detail: "MrBeast is ended: there is nothing left to nudge" }, response: new Response(null, { status: 400 }) } as never);
    withProviders(<NudgeButton campaignId={3} />);
    fireEvent.click(screen.getByRole("button", { name: "Nudge" }));
    const box = await screen.findByLabelText("Message (optional)");
    fireEvent.change(box, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: /Nudge agent/ }));
    expect(await screen.findByText(/nothing left to nudge/)).toBeInTheDocument();
    expect(box).toHaveValue("hello");
  });
});

describe("a slot that has gone quiet", () => {
  it("shows how long, offers a nudge, and the queue says why a request waits", () => {
    const board: Schemas["BoardOut"] = {
      ...boardFixture,
      slots: boardFixture.slots.map((s, i) => (i === 0 ? { ...s, quiet_s: 12 * 60, hung: true, session_id: 4 } : s)),
    };
    withProviders(<SlotBoard board={board} />);
    const slots = screen.getByRole("table", { name: "Agent slots" });
    expect(within(slots).getByText("quiet 12m")).toBeInTheDocument();
    expect(within(slots).getByRole("button", { name: "Nudge" })).toBeInTheDocument();
    const queue = screen.getByRole("table", { name: "Queue" });
    expect(within(queue).getByText(/held by session 4/)).toBeInTheDocument();
  });
});

describe("a stuck item in Needs you", () => {
  const stuck = needsFixture.find((i) => i.key === "stuck:job_stalled:2")!;
  const blocked = needsFixture.find((i) => i.key === "stuck:request_blocked:3")!;

  it("leads with the repair, then the other things you can do", () => {
    const onAction = vi.fn();
    withProviders(<NeedsYouList items={[stuck]} onAction={onAction} empty="Nothing" />);
    const row = screen.getByRole("row", { name: /hasn't moved for 38 min/ });
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["Ali Abdaal podcast cuts", "Cancel and retry", "Show jobs"]);
    fireEvent.click(within(row).getByRole("button", { name: "Cancel and retry" }));
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ action: "cancel_retry", args: { stall: "job_stalled:2" } }), stuck);
  });

  it("opens with the evidence and a box that nudges with your words", async () => {
    const post = mockPost({ routed_to: "campaign", id: 5 });
    withProviders(<NeedsYouList items={[blocked]} onAction={() => undefined} empty="Nothing" openKey={blocked.key} onOpenKeyChange={() => undefined} />);
    const region = await screen.findByRole("region");
    expect(await within(region).findByText(/held by session 4/)).toBeInTheDocument();
    expect(within(region).getByText("Evidence")).toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Run now" })).toBeInTheDocument();
    expect(within(region).getByRole("button", { name: "Release lease" })).toBeInTheDocument();
    const box = within(region).getByPlaceholderText("Tell the agent what to try");
    expect(within(region).getByText("Nudge with a message")).toBeInTheDocument();
    fireEvent.change(box, { target: { value: "Carry on with the second source" } });
    fireEvent.click(within(region).getByRole("button", { name: /Nudge agent/ }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/needs-you/{slug}/reply", { params: { path: { slug: "stuck-request_blocked-3" } }, body: { text: "Carry on with the second source", via: "dashboard" } });
    expect(await within(region).findByText(/Nudged\. The agent reads it first in line\./)).toBeInTheDocument();
  });
});

describe("the Jobs list", () => {
  it("has the data the stalled job's row needs", () => {
    const stalled = jobsFixture.find((j) => j.stalled)!;
    expect(stalled).toMatchObject({ id: 2, detail: "Tracking faces", status: "running" });
  });
});

describe("StageStepper", () => {
  it("turns the current stage red and says so when the campaign is stuck", () => {
    const stages = [
      { name: "Brief", state: "done" },
      { name: "Analyze", state: "active" },
      { name: "Clips", state: "pending" },
    ] as Schemas["Stage"][];
    const { container } = withProviders(<StageStepper stages={stages} stuck="Analysis hasn't moved for 38 min." />);
    expect(screen.getByText(/Analyze · stuck/)).toBeInTheDocument();
    expect(container.querySelector(".bg-bad")).not.toBeNull();
    expect(container.querySelector("[title^='Looks stuck']")).not.toBeNull();
  });
});
