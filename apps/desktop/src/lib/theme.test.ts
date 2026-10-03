import { describe, expect, it } from "vitest";
import { applyAppearance, inkFor } from "./theme";

describe("theme", () => {
  it("picks readable ink for an accent", () => {
    expect(inkFor("#4cc2ff")).toBe("#000000");
    expect(inkFor("#005fb8")).toBe("#ffffff");
    expect(inkFor("nonsense")).toBe("#ffffff");
  });
  it("writes theme, density and accent to <html>", () => {
    const el = document.createElement("html");
    applyAppearance(el, { theme: "dark", density: "comfortable", accent: "#ff8800" });
    expect(el.getAttribute("data-theme")).toBe("dark");
    expect(el.getAttribute("data-density")).toBe("comfortable");
    expect(el.getAttribute("data-accent")).toBe("user");
    expect(el.style.getPropertyValue("--accent-user")).toBe("#ff8800");
    applyAppearance(el, { theme: "system", density: "compact", accent: null });
    expect(el.hasAttribute("data-theme")).toBe(false);
    expect(el.hasAttribute("data-accent")).toBe(false);
  });
});
