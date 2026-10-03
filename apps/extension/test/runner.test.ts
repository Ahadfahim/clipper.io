import { describe, expect, it } from "vitest";
import { runOne, runRecipe, SETTLE_CHECKS_MS, type TabDriver } from "../src/background/runner";
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
    // pacing between steps is 600 + (2200-600) * 0.5; the rest are the page-settle checks after navigate
    const settle = new Set(SETTLE_CHECKS_MS.slice(1).map((at, i) => at - SETTLE_CHECKS_MS[i]!));
    expect(new Set(d.sleeps.filter((ms) => !settle.has(ms)))).toEqual(new Set([1400]));
  });

  it("catches a login wall that appears after the page loaded", async () => {
    const d = new FakeDriver();
    let checks = 0;
    d.check = async () => ({ ok: true, challenge: ++checks >= 3 ? ("login" as const) : null }); // the SPA redirects late
    const res = await runOne(d, { action: "navigate", url: "https://www.tiktok.com/tiktokstudio" }, 0, false);
    expect(res).toMatchObject({ ok: false, challenge: "login" });
    expect(checks).toBe(3);
    expect(d.steps).toEqual([]); // nothing on the page was touched
  });

  it("dry run stops at the file (attaching starts the upload) once the file input is there", async () => {
    const d = new FakeDriver();
    const res = await runRecipe(d, RECIPES["youtube.upload_short"]!, params, true);
    expect(res).toMatchObject({ ok: true, data: { dry_run: true, stopped_before_step: 3, reason: "attaching the file starts the upload" } });
    // Create, Upload videos, then only a check that the file input is there
    expect(d.steps.map((s) => [s.action, s.check_only ?? false])).toEqual([["click", false], ["click", false], ["attach_file", true]]);
    expect(d.steps.some((s) => s.final)).toBe(false);
    expect(d.fetched).toEqual([]);
    expect(d.files).toEqual([]);

    const missing = new FakeDriver();
    missing.respond = (s) => (s.action === "attach_file" ? { ok: false, error: "no file input: input[type=file][name=Filedata]" } : { ok: true });
    expect(await runRecipe(missing, RECIPES["youtube.upload_short"]!, params, true)).toMatchObject({ ok: false, step: 3, error: expect.stringMatching(/no file input/) });
  });

  it("`unless` skips a step when its param is set (Private instead of Public)", async () => {
    const visibility = async (extra: Record<string, unknown>) => {
      const d = new FakeDriver();
      await runRecipe(d, RECIPES["youtube.upload_short"]!, { ...params, ...extra }, false);
      return d.steps.filter((s) => /name=(PUBLIC|PRIVATE)/.test(s.selector ?? "")).map((s) => s.selector);
    };
    expect(await visibility({})).toEqual(["tp-yt-paper-radio-button[name=PUBLIC]"]);
    expect(await visibility({ private: true })).toEqual(["tp-yt-paper-radio-button[name=PRIVATE]"]);
  });

  it("a failing step returns its index, a screenshot and the simplified DOM", async () => {
    const d = new FakeDriver();
    d.respond = (s) => (s.action === "click" && s.selector?.includes("aria-label=Create") ? { ok: false, error: "nothing to click: Create", dom: "<header/>" } : { ok: true });
    const res = await runRecipe(d, RECIPES["youtube.upload_short"]!, params, false);
    expect(res).toMatchObject({ ok: false, step: 1, error: "nothing to click: Create", screenshot: "data:image/png;base64,AAAA", dom: "<header/>" });
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

describe("a page that navigates in the middle of a step", () => {
  const gone = () => {
    throw new Error("A listener indicated an asynchronous response by returning true, but the message channel closed before a response was received");
  };

  it("reports the login wall it redirected to", async () => {
    const d = new FakeDriver();
    d.url = "https://www.tiktok.com/tiktokstudio/upload";
    d.respond = gone;
    d.challengeAfterNavigate = "login";
    const res = await runOne(d, { action: "wait_for", selector: "input[type=file]" }, 0, false);
    expect(res).toMatchObject({ ok: false, challenge: "login" });
    expect(d.steps).toHaveLength(1);
  });

  it("retries a read-only step once on the new page", async () => {
    const d = new FakeDriver();
    let calls = 0;
    d.respond = () => (++calls === 1 ? gone() : { ok: true });
    expect((await runOne(d, { action: "wait_for", selector: "main" }, 0, false)).ok).toBe(true);
    expect(d.steps).toHaveLength(2);
  });

  it("never repeats a click", async () => {
    const d = new FakeDriver();
    d.respond = gone;
    const res = await runOne(d, { action: "click", selector: "#post" }, 0, false);
    expect(res).toMatchObject({ ok: false, error: expect.stringMatching(/not repeating it/) });
    expect(d.steps).toHaveLength(1);
  });

  it("still surfaces other errors", async () => {
    const d = new FakeDriver();
    d.respond = () => {
      throw new Error("Cannot access contents of the page");
    };
    await expect(runOne(d, { action: "query", selector: "a" }, 0, false)).rejects.toThrow(/Cannot access/);
  });
});
