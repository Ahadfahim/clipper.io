import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Schemas } from "@/api/client";
import { withProviders } from "@/test/render";
import { FootageDrop } from "./footage";

const INSPECT = "/api/sources/{source_id}/inspect";
const FILE = "/api/sources/{source_id}/file";

function info(over: Partial<Schemas["InspectOut"]> = {}): Schemas["InspectOut"] {
  return { name: "episode.mp4", path: "C:\\v\\episode.mp4", size: 1000, duration: 600, width: 1920, height: 1080, has_audio: true, warnings: [], ...over };
}

/** Answers the inspect call with `inspect`, and records every POST. */
function mockPost(inspect: Schemas["InspectOut"]) {
  const calls: { path: string; body: { path?: string; move?: boolean } }[] = [];
  vi.spyOn(api, "POST").mockImplementation(((path: string, init: { body: { path?: string; move?: boolean } }) => {
    calls.push({ path, body: init.body });
    if (path === INSPECT) return Promise.resolve({ data: inspect, response: new Response() });
    return Promise.resolve({ data: { ok: true, id: 7, detail: "adding" }, response: new Response() });
  }) as never);
  return calls;
}

const files = (calls: ReturnType<typeof mockPost>) => calls.filter((c) => c.path === FILE);

function type(text: string) {
  fireEvent.change(screen.getByLabelText("Path of the video file"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Use this file" }));
}

afterEach(() => vi.restoreAllMocks());

describe("FootageDrop", () => {
  it("uses a file that looks right at once, without the quotes Explorer adds", async () => {
    const calls = mockPost(info());
    withProviders(<FootageDrop sourceId={6} campaignId={2} dropFolder="D:/data/campaign_2" />);
    type('"C:\\v\\episode.mp4"');
    await waitFor(() => expect(files(calls)).toHaveLength(1));
    expect(calls[0]).toMatchObject({ path: INSPECT, body: { path: "C:\\v\\episode.mp4" } });
    expect(files(calls)[0]!.body).toEqual({ path: "C:\\v\\episode.mp4", move: false });
    expect(await screen.findByText("Adding episode.mp4")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Drop the video file here" })).toBeNull(); // the copy is under way
  });

  it("shows what looks wrong and waits for you before using the file", async () => {
    const calls = mockPost(info({ warnings: [{ code: "short", text: "This file is only 0:08 long, and the campaign needs clips of at least 0:45." }] }));
    withProviders(<FootageDrop sourceId={6} campaignId={2} />);
    type("C:\\v\\episode.mp4");
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/only 0:08 long/)).toBeInTheDocument();
    expect(files(calls)).toHaveLength(0);
    fireEvent.click(within(alert).getByRole("button", { name: "Choose another" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(files(calls)).toHaveLength(0);
    type("C:\\v\\episode.mp4");
    fireEvent.click(await within(await screen.findByRole("alert")).findByRole("button", { name: "Use anyway" }));
    await waitFor(() => expect(files(calls)).toHaveLength(1));
  });

  it("sends the move choice along with the file", async () => {
    const calls = mockPost(info());
    withProviders(<FootageDrop sourceId={6} campaignId={2} />);
    fireEvent.click(screen.getByLabelText("Move the file instead of copying it"));
    type("C:\\v\\episode.mp4");
    await waitFor(() => expect(files(calls)).toHaveLength(1));
    expect(files(calls)[0]!.body.move).toBe(true);
  });

  it("checks a dropped file like a chosen one, and says when it isn't a video", async () => {
    const calls = mockPost(info());
    withProviders(<FootageDrop sourceId={6} campaignId={2} />);
    act(() => void window.__clipperTestDrop?.(["C:\\v\\notes.txt"]));
    expect(await screen.findByText(/notes.txt isn't a video/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    act(() => void window.__clipperTestDrop?.(["C:\\v\\notes.txt", "C:\\v\\a.mov", "C:\\v\\b.mp4"]));
    await waitFor(() => expect(files(calls)).toHaveLength(1));
    expect(calls[0]!.body.path).toBe("C:\\v\\a.mov");
  });

  it("offers the videos you downloaded recently, newest first", async () => {
    const calls = mockPost(info());
    withProviders(<FootageDrop sourceId={6} campaignId={2} />);
    const use = await screen.findByRole("button", { name: "Use episode-212.mp4" });
    expect(screen.getByText("Recent downloads")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((li) => li.querySelector("span")?.textContent)).toEqual(["episode-212.mp4", "Raw episode final.mov"]);
    fireEvent.click(use);
    await waitFor(() => expect(files(calls)).toHaveLength(1));
    expect(files(calls)[0]!.body.path).toBe("C:/Users/you/Downloads/episode-212.mp4");
  });

  it("shows the copy's progress instead of the drop box while a file is being added", () => {
    mockPost(info());
    withProviders(<FootageDrop sourceId={6} campaignId={2} activity={{ job_id: 3, kind: "import", label: "Adding your file", progress: 0.4 }} />);
    expect(screen.getByRole("progressbar", { name: "Adding the file" })).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByText("Adding your file")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Drop the video file here" })).toBeNull();
    expect(screen.queryByLabelText("Path of the video file")).toBeNull();
  });
});
