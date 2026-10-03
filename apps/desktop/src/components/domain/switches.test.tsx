import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { withProviders } from "@/test/render";
import { SwitchOffDialog } from "./switches";

describe("SwitchOffDialog", () => {
  it("shows what will be affected and passes the chosen handling", async () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    withProviders(<SwitchOffDialog target={{ level: "marketplace", name: "whop", label: "Whop" }} onClose={onClose} onConfirm={onConfirm} />);
    expect(screen.getByRole("dialog", { name: "Turn off Whop?" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Active campaigns/).textContent).toMatch(/\(\d+\)/));
    fireEvent.click(screen.getByLabelText("Pause them now"));
    fireEvent.click(screen.getByLabelText("Cancel them"));
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    expect(onConfirm).toHaveBeenCalledWith({ level: "marketplace", name: "whop", enabled: false, on_active: "pause", on_scheduled: "cancel" });
    expect(onClose).toHaveBeenCalled();
  });
  it("asks only about scheduled posts for a social", () => {
    withProviders(<SwitchOffDialog target={{ level: "social", name: "tiktok", label: "TikTok" }} onClose={() => undefined} onConfirm={() => undefined} />);
    expect(screen.queryByText(/Active campaigns/)).toBeNull();
    expect(screen.getByText(/Scheduled posts/)).toBeInTheDocument();
  });
});
