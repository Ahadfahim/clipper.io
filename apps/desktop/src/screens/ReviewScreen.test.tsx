import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "@/test/render";

const selected = () => screen.getByRole("listbox", { name: "Clips in this batch" }).querySelector('[aria-selected="true"]')!;

describe("Review keyboard flow", () => {
  it("A approves and moves to the next pending clip; R picks a reason; arrows move", async () => {
    renderApp("/review/1");
    await waitFor(() => expect(screen.getByRole("listbox", { name: "Clips in this batch" })).toBeInTheDocument(), { timeout: 4000 });
    // first pending clip by score is selected
    expect(selected().textContent).toContain("He thought it was a prank");
    act(() => {
      fireEvent.keyDown(window, { key: "a" });
    });
    await waitFor(() => expect(selected().textContent).toContain("I can't believe he said yes"));
    const list = screen.getByRole("listbox", { name: "Clips in this batch" });
    expect(within(list).getByText("He thought it was a prank").closest("button")?.textContent).toContain("Approved");
    // reject with a reason by number key
    act(() => {
      fireEvent.keyDown(window, { key: "r" });
    });
    expect(screen.getByRole("menu", { name: "Reject reason" })).toBeInTheDocument();
    act(() => {
      fireEvent.keyDown(window, { key: "2" });
    });
    await waitFor(() => expect(within(list).getByText("I can't believe he said yes").closest("button")?.textContent).toContain("Rejected"));
    expect(selected().textContent).toContain("100 hours in a box");
    act(() => {
      fireEvent.keyDown(window, { key: "ArrowLeft" });
    });
    expect(selected().textContent).toContain("I can't believe he said yes");
    // header counts follow
    expect(screen.getByText(/9\/12 reviewed/)).toBeInTheDocument();
  });
});
