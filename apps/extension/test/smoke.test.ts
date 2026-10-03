import { expect, it } from "vitest";
import { EXTENSION_VERSION } from "../src/version";

it("has a version", () => {
  expect(EXTENSION_VERSION).toBe("0.1.0");
});
