import { describe, expect, it } from "vitest";
import { runOne, runRecipe, type TabDriver } from "../src/background/runner";
import type { Step, StepOutcome } from "../src/shared/protocol";
import type { Recipe } from "../src/shared/recipe";
import { RECIPES } from "../src/background/recipes";

class FakeDriver implements TabDriver {
  url: string | null = "https://studio.youtube.com/";
  steps: Step[] = [];
  navigations: string[] = [];
  files: { id: string; name: string; size: number }[] = [];
  fetched: string[] = [];
  sleeps: number[] = [];
  respond: (s: Step) => StepOutcome = (s) => (s.action === "read_text" ? { ok: true, data: { value: "https://youtube.com/shorts/Abc123def45" } } : { ok: true });
  challengeAfterNavigate: StepOutcome["challenge"] = null;

  async navigate(url: string) {
    this.navigations.push(url);
    this.url = url;
  }
  async currentUrl() {
    return this.url;
  }
  async step(step: Step) {
    this.steps.push(step);
    return this.respond(step);
  }
  async check() {
    return { ok: true, challenge: this.challengeAfterNavigate };
  }
  async dom() {
    return "<main/>";
  }
  async screenshot() {
    return "data:image/png;base64,AAAA";
  }
  async sendFile(id: string, bytes: Uint8Array, name: string) {
    this.files.push({ id, name, size: bytes.length });
  }
  async fetchFile(url: string) {
    this.fetched.push(url);
    return { bytes: new Uint8Array(1234), mime: "video/mp4" };
  }
  async sleep(ms: number) {
    this.sleeps.push(ms);
  }
}

const params = {
  file_url: "http://127.0.0.1:8765/api/files/clip/7/final",
  file_name: "clip_7.mp4",
  title: "He thought it was a prank",
  caption: "wait for it",
  hashtags: ["mrbeast"],
  schedule_at: null,
  handle: "@beastmoments",
};

describe("runRecipe", () => {
  it("uploads: navigates, fetches the clip from the core, fills fields, reads the URL, paces steps", async () => {
    const d = new FakeDriver();
    const res = await runRecipe(d, RECIPES["youtube.upload_short"]!, params, false, () => 0.5);
    expect(res.ok).toBe(true);
    expect(res.data["post_url"]).toBe("https://youtube.com/shorts/Abc123def45");
    expect(res.data["recipe_status"]).toBe("UNVERIFIED");
    expect(d.navigations).toEqual(["https://studio.youtube.com/"]);
    expect(d.fetched).toEqual(["http://127.0.0.1:8765/api/files/clip/7/final"]);
    expect(d.files[0]).toMatchObject({ name: "clip_7.mp4", size: 1234 });
    const typed = d.steps.filter((s) => s.action === "type").map((s) => s.value);
    expect(typed).toContain("He thought it was a prank");
    expect(typed).toContain("wait for it #mrbeast");
    expect(d.steps.some((s) => s.when === "schedule_at")).toBe(false); // skipped: no schedule
    expect(d.steps.some((s) => s.final)).toBe(true);
    expect(new Set(d.sleeps)).toEqual(new Set([1400])); // 600 + (2200-600) * 0.5
  });

  it("dry run stops before the publish click and never fetches or attaches the clip", async () => {
    const d = new FakeDriver();
    const res = await runRecipe(d, RECIPES["youtube.upload_short"]!, params, true);
    expect(res).toMatchObject({ ok: true, data: { dry_run: true } });
    expect(d.steps.some((s) => s.final)).toBe(false);
    expect(d.fetched).toEqual([]);
    expect(d.files).toEqual([]);
  });

  it("a failing step returns its index, a screenshot and the simplified DOM", async () => {
    const d = new FakeDriver();
    d.respond = (s) => (s.action === "click" && s.selector === "#create-icon" ? { ok: false, error: "nothing to click: #create-icon", dom: "<header/>" } : { ok: true });
    const res = await runRecipe(d, RECIPES["youtube.upload_short"]!, params, false);
    expect(res).toMatchObject({ ok: false, step: 1, error: "nothing to click: #create-icon", screenshot: "data:image/png;base64,AAAA", dom: "<header/>" });
  });

  it("stops on a challenge and reports it (the core pauses the account)", async () => {
    const d = new FakeDriver();
    d.challengeAfterNavigate = "verification";
    const res = await runRecipe(d, RECIPES["tiktok.upload"]!, params, false);
    expect(res).toMatchObject({ ok: false, step: 0, challenge: "verification" });
    expect(d.steps).toEqual([]); // nothing was touched on the challenge page
    const d2 = new FakeDriver();
    d2.respond = (s) => (s.action === "type" ? { ok: false, challenge: "captcha", error: "captcha screen" } : { ok: true });
    const res2 = await runRecipe(d2, RECIPES["tiktok.upload"]!, params, false);
    expect(res2.challenge).toBe("captcha");
  });

  it("refuses missing params, non-local files and tabs that left the allowlist", async () => {
    expect((await runRecipe(new FakeDriver(), RECIPES["tiktok.upload"]!, { ...params, handle: "" }, false)).error).toBe("missing params: handle");
    const r = await runRecipe(new FakeDriver(), RECIPES["youtube.upload_short"]!, { ...params, file_url: "https://evil.example/clip.mp4" }, false);
    expect(r.error).toMatch(/only takes clips served by the local core/);
    const d = new FakeDriver();
    d.url = "https://accounts.google.com.evil.example/";
    const one = await runOne(d, { action: "click", selector: "#x" }, 0, false);
    expect(one.ok).toBe(false);
    expect(one.error).toMatch(/left the allowlist/);
    const nav = await runOne(new FakeDriver(), { action: "navigate", url: "https://example.com/" }, 0, false);
    expect(nav.error).toMatch(/not on the site allowlist/);
  });

  it("missing return value fails the run", async () => {
    const d = new FakeDriver();
    d.respond = () => ({ ok: true });
    const res = await runRecipe(d, RECIPES["instagram.upload_reel"]!, params, false);
    expect(res).toMatchObject({ ok: false, error: "finished but post_url was not found" });
  });

  it("optional steps may be missing", async () => {
    const recipe: Recipe = {
      name: "x.test",
      version: 1,
      site: "x",
      status: "UNVERIFIED",
      description: "",
      params: {},
      returns: [],
      steps: [
        { action: "click", text: "OK", optional: true },
        { action: "click", text: "Next" },
      ],
    };
    const d = new FakeDriver();
    d.url = "https://x.com/";
    d.respond = (s) => (s.text === "OK" ? { ok: false, error: "nothing to click" } : { ok: true });
    expect((await runRecipe(d, recipe, {}, false)).ok).toBe(true);
  });
});
