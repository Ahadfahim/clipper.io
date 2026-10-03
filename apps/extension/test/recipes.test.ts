import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { hostAllowed } from "../src/shared/allowlist";
import { fill, validateRecipe, type Recipe } from "../src/shared/recipe";
import { RECIPES } from "../src/background/recipes";

const dir = resolve(__dirname, "../recipes");
const files = readdirSync(dir).filter((f) => f.endsWith(".json") && f !== "schema.json");
const REQUIRED = ["youtube.upload_short", "tiktok.upload", "instagram.upload_reel", "vyro.list_campaigns", "vyro.submit_url", "whop.list_campaigns", "whop.submit_url"];
const CORE_UPLOAD_PARAMS = ["file_url", "file_name", "title", "caption", "hashtags", "schedule_at", "handle"]; // core/clipper/publishing/browser.py

describe("shipped recipes", () => {
  it("include every recipe the core calls and all are bundled", () => {
    for (const name of REQUIRED) expect(RECIPES[name], name).toBeDefined();
    expect(Object.keys(RECIPES).sort()).toEqual(files.map((f) => f.replace(/\.json$/, "")).sort());
  });

  it.each(files)("%s is valid, UNVERIFIED, and only opens allowlisted https sites", (f) => {
    const r = JSON.parse(readFileSync(resolve(dir, f), "utf-8")) as Recipe;
    expect(validateRecipe(r)).toEqual([]);
    expect(`${r.name}.json`).toBe(f);
    expect(r.status).toBe("UNVERIFIED");
    for (const s of r.steps.filter((x) => x.action === "navigate")) {
      const url = fill(s.url, { id: "abc", handle: "@me" })!;
      expect(hostAllowed(url), url).toBe(true);
    }
  });

  it("upload recipes accept the params the core sends and mark the publish click final", () => {
    for (const name of ["youtube.upload_short", "tiktok.upload", "instagram.upload_reel"]) {
      const r = RECIPES[name]!;
      for (const p of CORE_UPLOAD_PARAMS) expect(Object.keys(r.params), `${name} ${p}`).toContain(p);
      expect(r.steps.filter((s) => s.final)).toHaveLength(1);
      expect(r.returns).toEqual(["post_url"]);
      expect(r.steps.some((s) => s.action === "attach_file" && s.file === "{{file_url}}")).toBe(true);
    }
    for (const name of ["vyro.submit_url", "whop.submit_url"]) expect(RECIPES[name]!.steps.filter((s) => s.final)).toHaveLength(1);
  });

  it("validation catches mistakes", () => {
    const bad = { name: "youtube.x", version: 1, site: "youtube", status: "UNVERIFIED", description: "", params: {}, returns: ["post_url"], steps: [{ action: "type", selector: "#t", value: "{{title|shout}} {{nope}}" }, { action: "fly" }] };
    const errs = validateRecipe(bad);
    expect(errs.join("\n")).toMatch(/unknown param \{\{title\}\}/);
    expect(errs.join("\n")).toMatch(/unknown filter \|shout/);
    expect(errs.join("\n")).toMatch(/unknown action fly/);
    expect(errs.join("\n")).toMatch(/returns post_url but no step saves it/);
  });

  it("template filters", () => {
    expect(fill("https://www.tiktok.com/@{{handle|noat}}", { handle: "@clipsdaily" })).toBe("https://www.tiktok.com/@clipsdaily");
    expect(fill("{{caption}} {{hashtags|tags}}", { caption: "So good", hashtags: ["mrbeast", "#shorts"] })).toBe("So good #mrbeast #shorts");
    expect(fill("{{id|url}}", { id: "a b/c" })).toBe("a%20b%2Fc");
  });
});

describe("allowlist", () => {
  it.each([
    ["https://studio.youtube.com/channel/x", true],
    ["https://www.tiktok.com/upload", true],
    ["https://youtube.com.evil.example/", false],
    ["http://www.tiktok.com/", false],
    ["https://example.com/", false],
    ["javascript:alert(1)", false],
  ])("%s → %s", (url, ok) => expect(hostAllowed(url)).toBe(ok));
});
