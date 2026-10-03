import { describe, expect, it } from "vitest";
import { lineDiff } from "./SettingsDialog";

describe("prompt diff", () => {
  it("marks added and removed lines", () => {
    expect(lineDiff("a\nb\nc", "a\nB\nc\nd")).toEqual([
      { kind: " ", text: "a" },
      { kind: "-", text: "b" },
      { kind: "+", text: "B" },
      { kind: " ", text: "c" },
      { kind: "+", text: "d" },
    ]);
  });
});
