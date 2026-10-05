import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { withProviders } from "@/test/render";
import { CampaignLinkButton, useSkipFlow } from "./links";

const vyro = { label: "Open on Vyro", url: "https://app.vyro.com/campaigns?c=cinematic-edits", kind: "marketplace", host: "app.vyro.com", open_in: "clipper" } as const;

describe("CampaignLinkButton", () => {
  it("opens the page in Clipper's own browser, and doesn't select the row it sits in", async () => {
    const post = vi.spyOn(api, "POST").mockResolvedValue({ data: {}, response: new Response() } as never);
    const rowClick = vi.fn();
    withProviders(
      <div onClick={rowClick}>
        <CampaignLinkButton link={vyro} />
      </div>,
    );
    const button = screen.getByRole("button", { name: "Open on Vyro" });
    expect(button).toHaveAttribute("title", "Open on Vyro · app.vyro.com");
    fireEvent.click(button);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/browser/open", { body: { url: vyro.url, profile: "main" } }));
    expect(rowClick).not.toHaveBeenCalled();
    post.mockRestore();
  });

  it("warns when the marketplace said the page isn't there", () => {
    withProviders(<CampaignLinkButton link={vyro} status="unavailable" checked="2026-10-04T21:04:00Z" />);
    expect(screen.getByRole("button", { name: "Open on Vyro" }).getAttribute("title")).toMatch(/said this campaign isn't available/);
  });

  it("renders nothing without a link", () => {
    const { container } = withProviders(<CampaignLinkButton link={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

function Skipper({ id }: { id: number }) {
  const { request, dialog } = useSkipFlow();
  return (
    <>
      <button onClick={() => request(id, "Diary of a CEO")}>skip</button>
      {dialog}
    </>
  );
}

describe("useSkipFlow", () => {
  it("skips at once when nothing is left to submit", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue({ data: { live_unsubmitted: 0 }, response: new Response() } as never);
    const post = vi.spyOn(api, "POST").mockResolvedValue({ data: {}, response: new Response() } as never);
    withProviders(<Skipper id={4} />);
    fireEvent.click(screen.getByText("skip"));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/api/campaigns/{campaign_id}/skip", { params: { path: { campaign_id: 4 }, query: { via: "dashboard", keep_submitting: false } } });
    expect(screen.queryByRole("dialog")).toBeNull();
    get.mockRestore();
    post.mockRestore();
  });

  it("asks first when live posts aren't submitted, and can keep submitting", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue({ data: { live_unsubmitted: 2 }, response: new Response() } as never);
    const post = vi.spyOn(api, "POST").mockResolvedValue({ data: {}, response: new Response() } as never);
    withProviders(<Skipper id={4} />);
    fireEvent.click(screen.getByText("skip"));
    const dialog = await screen.findByRole("dialog", { name: "Skip this campaign?" });
    expect(dialog).toHaveTextContent("Diary of a CEO has 2 live posts that aren't submitted yet");
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Skip and keep submitting" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/campaigns/{campaign_id}/skip", { params: { path: { campaign_id: 4 }, query: { via: "dashboard", keep_submitting: true } } }));
    get.mockRestore();
    post.mockRestore();
  });

  it("Cancel leaves the campaign alone", async () => {
    const get = vi.spyOn(api, "GET").mockResolvedValue({ data: { live_unsubmitted: 1 }, response: new Response() } as never);
    const post = vi.spyOn(api, "POST").mockResolvedValue({ data: {}, response: new Response() } as never);
    withProviders(<Skipper id={4} />);
    fireEvent.click(screen.getByText("skip"));
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(post).not.toHaveBeenCalled();
    get.mockRestore();
    post.mockRestore();
  });
});
