import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { withProviders } from "@/test/render";
import { age, fitsInline, inlineActions, slugOf, snoozeLabel, type NeedsItem } from "@/lib/needsYou";
import fixture from "../../../public/fixtures/api/needs-you.json";
import { NeedsYouList } from "./attention";

const items = fixture as unknown as NeedsItem[];
const question = items.find((i) => i.kind === "question")!;

function longQuestion(): NeedsItem {
  const options = ["I'll join the campaign on Vyro myself and give you the correct URL", "The campaign has ended or been removed", "Leave it for now"];
  return {
    ...question,
    key: "question:9",
    title: "Post 1 is live on YouTube, but I couldn't submit it to Vyro. How should I proceed?",
    options,
    actions: options.map((label) => ({ label, action: "answer", args: { question_id: 9, answer: label } })),
  };
}

describe("needs you helpers", () => {
  it("turns keys into addresses, ages into short labels", () => {
    expect(slugOf("failure:job:2")).toBe("failure-job-2");
    const now = Date.parse("2026-10-02T18:00:00Z");
    expect(age("2026-10-02T17:56:00Z", now)).toBe("4m");
    expect(age("2026-10-02T15:00:00Z", now)).toBe("3h");
    expect(age("2026-09-29T18:00:00Z", now)).toBe("3d");
    expect(age("2026-10-02T17:59:50Z", now)).toBe("now");
    expect(age(null, now)).toBe("");
  });
  it("only short answers fit in a row", () => {
    expect(fitsInline(["Yes", "No", "Skip campaign"])).toBe(true);
    expect(fitsInline(["Yes", "No", "Maybe", "Later"])).toBe(false);
    expect(fitsInline(["I'll join the campaign on Vyro myself"])).toBe(false);
    expect(inlineActions(longQuestion()).map((a) => a.label)).toEqual(["Answer"]);
    expect(inlineActions(question).map((a) => a.label)).toEqual(["Yes", "No", "Skip campaign"]);
  });
  it("labels snooze times", () => {
    expect([60, 240, 1440, 4320].map(snoozeLabel)).toEqual(["1 hour", "4 hours", "1 day", "3 days"]);
  });
});

describe("NeedsYouList", () => {
  it("shows the whole question and keeps long answers out of the row", () => {
    const long = longQuestion();
    withProviders(<NeedsYouList items={[long]} onAction={() => undefined} empty="Nothing" />);
    const row = screen.getByRole("row", { name: /couldn't submit it to Vyro/ });
    expect(within(row).getByText(/How should I proceed\?/)).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Answer" })).toBeInTheDocument();
    expect(within(row).getAllByRole("button").map((b) => b.textContent)).toEqual(["MrBeast #42 clipping", "Answer"]); // the campaign link, then one button
    expect(screen.queryByText(/I'll join the campaign on Vyro myself/)).toBeNull();
  });

  it("answers a short question right from the row without opening it", () => {
    const onAction = vi.fn();
    withProviders(<NeedsYouList items={[question]} onAction={onAction} empty="Nothing" />);
    fireEvent.click(screen.getByRole("button", { name: "Skip campaign" }));
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ action: "answer", args: expect.objectContaining({ answer: "Skip campaign" }) }), question);
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("opens one row at a time and shows every option, a place for your own words and the facts", async () => {
    withProviders(<NeedsYouList items={items} onAction={() => undefined} empty="Nothing" />);
    fireEvent.click(screen.getByRole("row", { name: /Rules unclear/ }));
    const region = await screen.findByRole("region", { name: /Details: Rules unclear/ });
    await within(region).findByText("Your answer");
    expect(within(region).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["1Yes", "2No", "3Skip campaign"]);
    expect(within(region).getByPlaceholderText("Answer in your own words")).toBeInTheDocument();
    expect(within(region).getByText("Asked by")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("row", { name: /5 of 12 clips to review/ }));
    await screen.findByRole("region", { name: /Details: 5 of 12 clips/ });
    expect(screen.getAllByRole("region")).toHaveLength(1);
  });

  it("works from the keyboard: arrows move, Enter opens, Escape closes", async () => {
    withProviders(<NeedsYouList items={items} onAction={() => undefined} empty="Nothing" />);
    const rows = screen.getAllByRole("row").filter((r) => r.hasAttribute("data-needs-row"));
    rows[0]!.focus();
    fireEvent.keyDown(rows[0]!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[1]);
    fireEvent.keyDown(rows[1]!, { key: "Enter" });
    await screen.findByRole("region");
    expect(rows[1]).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(rows[1]!, { key: "Escape" });
    expect(screen.queryByRole("region")).toBeNull();
  });

  it("number keys answer the open question", async () => {
    const onAction = vi.fn();
    withProviders(<NeedsYouList items={items} onAction={onAction} empty="Nothing" openKey={question.key} onOpenKeyChange={() => undefined} />);
    await screen.findByRole("region");
    fireEvent.keyDown(screen.getByRole("row", { name: /Rules unclear/ }), { key: "3" });
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ label: "Skip campaign" }), question);
  });

  it("sends your own words with Ctrl+Enter and not before there is something to send", async () => {
    const post = vi.spyOn(api, "POST").mockResolvedValue({ data: { routed_to: "question", id: 1 }, response: new Response() } as never);
    withProviders(<NeedsYouList items={items} onAction={() => undefined} empty="Nothing" openKey={question.key} onOpenKeyChange={() => undefined} />);
    const region = await screen.findByRole("region");
    const box = await within(region).findByPlaceholderText("Answer in your own words");
    expect(within(region).getByRole("button", { name: /Send answer/ })).toBeDisabled();
    fireEvent.change(box, { target: { value: "Use the full episode, not the trailer" } });
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/needs-you/{slug}/reply", {
      params: { path: { slug: "question-1" } },
      body: { text: "Use the full episode, not the trailer", via: "dashboard" },
    });
    post.mockRestore();
  });

  it("says so when an item is no longer waiting", async () => {
    const gone: NeedsItem = { ...question, key: "question:404" };
    withProviders(<NeedsYouList items={[gone]} onAction={() => undefined} empty="Nothing" openKey="question:404" onOpenKeyChange={() => undefined} />);
    expect(await screen.findByText("This isn't waiting on you any more.")).toBeInTheDocument();
  });

  it("shows the empty message", () => {
    withProviders(<NeedsYouList items={[]} onAction={() => undefined} empty="You're all caught up." />);
    expect(screen.getByText("You're all caught up.")).toBeInTheDocument();
  });
});
