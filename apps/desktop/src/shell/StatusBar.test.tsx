import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { qk } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { renderApp } from "@/test/render";
import status from "../../public/fixtures/api/status.json";

const base = status as unknown as Schemas["StatusOut"];

async function withBrowser(over: Partial<Schemas["BrowserProfileOut"]>) {
  const { qc } = renderApp("/");
  await screen.findByText(/^Browser /);
  act(() => {
    qc.setQueryData(qk.status, { ...base, browser: base.browser.map((b) => (b.name === "main" ? { ...b, running: true, ...over } : b)) });
  });
  return qc;
}

describe("the browser segment of the status bar", () => {
  it("says shown while you are looking at it", async () => {
    await withBrowser({ visible: true, shown_for_s: 120 });
    await waitFor(() => expect(screen.getByText("Browser shown")).toBeInTheDocument());
  });

  it("turns into a reminder, and hides it when clicked, after it has been showing for half an hour", async () => {
    await withBrowser({ visible: true, shown_for_s: 41 * 60 });
    const seg = await screen.findByText("Browser shown for 41 min · hide");
    expect(seg.closest("button")).toHaveAttribute("title", expect.stringContaining("Click to hide it"));
  });

  it("says nothing special while it is hidden, however long it has been", async () => {
    await withBrowser({ visible: false, shown_for_s: null });
    await waitFor(() => expect(screen.getByText("Browser hidden")).toBeInTheDocument());
  });
});
