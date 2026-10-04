import { describe, expect, it } from "vitest";
import { modelLabel } from "./platforms";

describe("modelLabel", () => {
  it("shortens Claude model ids and passes others through", () => {
    expect(modelLabel("claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(modelLabel("claude-haiku-4-5-20251001")).toBe("Haiku 4.5");
    expect(modelLabel("claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelLabel("my-model")).toBe("my-model");
    expect(modelLabel(null)).toBe("");
  });
});
