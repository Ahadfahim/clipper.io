import { describe, expect, it } from "vitest";
import { comboOf, isTyping } from "./hotkeys";

describe("hotkeys", () => {
  it("normalizes combos", () => {
    expect(comboOf(new KeyboardEvent("keydown", { key: "K", ctrlKey: true }))).toBe("ctrl+k");
    expect(comboOf(new KeyboardEvent("keydown", { key: "A", shiftKey: true }))).toBe("shift+a");
    expect(comboOf(new KeyboardEvent("keydown", { key: " " }))).toBe("space");
    expect(comboOf(new KeyboardEvent("keydown", { key: "ArrowLeft" }))).toBe("arrowleft");
  });
  it("knows when the user is typing", () => {
    const input = document.createElement("input");
    const e = new KeyboardEvent("keydown", { key: "a" });
    Object.defineProperty(e, "target", { value: input });
    expect(isTyping(e)).toBe(true);
  });
});
