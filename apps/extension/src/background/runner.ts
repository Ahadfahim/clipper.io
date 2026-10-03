// Runs a recipe step by step against one tab. All chrome.* access sits behind `TabDriver`
// (driver.ts), so the runner is tested with a fake driver.
import { hostAllowed, isLocalFileUrl } from "../shared/allowlist";
import type { Challenge, Step, StepOutcome } from "../shared/protocol";
import { fill, missingParams, type Recipe } from "../shared/recipe";

export interface TabDriver {
  navigate(url: string): Promise<void>;
  currentUrl(): Promise<string | null>;
  step(step: Step, fileId?: string): Promise<StepOutcome>;
  check(): Promise<StepOutcome>;
  dom(): Promise<string>;
  screenshot(): Promise<string | null>;
  sendFile(id: string, bytes: Uint8Array, name: string, mime: string): Promise<void>;
  fetchFile(url: string): Promise<{ bytes: Uint8Array; mime: string }>;
  sleep(ms: number): Promise<void>;
}

export type RunResult = {
  ok: boolean;
  data: Record<string, unknown>;
  error?: string;
  step?: number;
  screenshot?: string | null;
  dom?: string | null;
  challenge?: Challenge | null;
};

const DEFAULT_DELAY: [number, number] = [600, 2200];

function delayFor(params: Record<string, unknown>, rand: () => number): number {
  const d = params["step_delay_ms"];
  const [lo, hi] = Array.isArray(d) && d.length === 2 ? [Number(d[0]), Number(d[1])] : DEFAULT_DELAY;
  return Math.round(lo + (hi - lo) * rand());
}

function templated(step: Step, params: Record<string, unknown>): Step {
  return { ...step, url: fill(step.url, params), value: fill(step.value, params), file: fill(step.file, params), name: fill(step.name, params), text: fill(step.text, params), selector: fill(step.selector, params) };
}

async function failure(driver: TabDriver, step: number, error: string, challenge: Challenge | null = null, dom?: string): Promise<RunResult> {
  return { ok: false, data: {}, step, error, challenge, screenshot: await driver.screenshot().catch(() => null), dom: dom ?? (await driver.dom().catch(() => null)) };
}

/** When to check a freshly opened page for a login/CAPTCHA/verification screen (ms after load). */
export const SETTLE_CHECKS_MS = [0, 700, 1500, 3000];

/** Single-page apps redirect to a login wall or render it after "load" (TikTok, Instagram), so look
 * again while the page settles instead of only once. */
async function settledChallenge(driver: TabDriver): Promise<{ challenge: Challenge; what: string } | null> {
  let waited = 0;
  for (const at of SETTLE_CHECKS_MS) {
    if (at > waited) await driver.sleep(at - waited);
    waited = at;
    const check = await driver.check().catch(() => null); // the page may still be swapping documents
    if (check?.challenge) {
      const reason = check.data?.["reason"];
      return { challenge: check.challenge, what: `${check.challenge} screen${typeof reason === "string" ? ` (${reason})` : ""}` };
    }
  }
  return null;
}

// what chrome.tabs.sendMessage throws when the page navigated while the content script was working
const NAVIGATED = /message channel closed|receiving end does not exist|back\/forward cache|no frame with id|frame .* removed/i;
const READ_ONLY: ReadonlySet<Step["action"]> = new Set(["wait_for", "query", "read_text", "outline"]);

/** Runs a step; if the page navigates underneath it (a redirect to a login wall, an SPA reload),
 * reports the wall, retries a read-only step once on the new page, and never repeats a click/type. */
async function stepThroughNavigation(driver: TabDriver, step: Step, fileId?: string): Promise<StepOutcome> {
  try {
    return await driver.step(step, fileId);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (!NAVIGATED.test(message)) throw e;
    const hit = await settledChallenge(driver);
    if (hit) return { ok: false, challenge: hit.challenge, error: `${hit.what}: the page redirected to it` };
    if (!READ_ONLY.has(step.action)) return { ok: false, error: `the page navigated away during ${step.action}; not repeating it` };
    return driver.step(step, fileId);
  }
}

/** Runs one step (recipe or a single `action` from the core's browser tools). */
export async function runOne(driver: TabDriver, step: Step, index: number, dryRun: boolean): Promise<RunResult & { saved?: unknown }> {
  if (step.final && dryRun) return { ok: true, data: { dry_run: true, stopped_before: step.selector ?? step.text ?? step.action }, step: index };
  if (step.action === "navigate") {
    if (!step.url || !hostAllowed(step.url)) return failure(driver, index, `not allowed: ${step.url} is not on the site allowlist`);
    await driver.navigate(step.url);
    const hit = await settledChallenge(driver);
    if (hit) return failure(driver, index, `${hit.what} after opening the page`, hit.challenge);
    return { ok: true, data: { url: (await driver.currentUrl()) ?? step.url } };
  }
  const url = await driver.currentUrl();
  if (url && !hostAllowed(url)) return failure(driver, index, `the tab left the allowlist (${new URL(url).hostname}); stopped`);
  if (step.action === "screenshot") {
    const shot = await driver.screenshot();
    return { ok: Boolean(shot), data: {}, screenshot: shot, saved: shot };
  }
  let fileId: string | undefined;
  if (step.action === "attach_file") {
    if (!step.file || !isLocalFileUrl(step.file)) return failure(driver, index, "attach_file only takes clips served by the local core (127.0.0.1)");
    if (dryRun) return { ok: true, data: { dry_run: true, would_attach: step.name ?? step.file } };
    const { bytes, mime } = await driver.fetchFile(step.file);
    fileId = `f${Date.now().toString(36)}${index}`;
    await driver.sendFile(fileId, bytes, step.name || "clip.mp4", mime || "video/mp4");
  }
  const out = await stepThroughNavigation(driver, step, fileId);
  if (out.challenge) return failure(driver, index, out.error ?? `${out.challenge} screen`, out.challenge, out.dom);
  if (!out.ok) {
    if (step.optional) return { ok: true, data: { skipped: true } };
    return failure(driver, index, out.error ?? "step failed", null, out.dom);
  }
  return { ok: true, data: out.data ?? {}, dom: out.dom ?? null, saved: out.data?.["value"] };
}

export async function runRecipe(
  driver: TabDriver,
  recipe: Recipe,
  params: Record<string, unknown>,
  dryRun: boolean,
  rand: () => number = Math.random,
): Promise<RunResult> {
  const missing = missingParams(recipe, params);
  if (missing.length) return { ok: false, data: {}, error: `missing params: ${missing.join(", ")}`, step: 0 };
  const output: Record<string, unknown> = { recipe: recipe.name, recipe_status: recipe.status };
  for (let i = 0; i < recipe.steps.length; i++) {
    const raw = recipe.steps[i]!;
    if (raw.when && !params[raw.when]) continue;
    if (raw.final && dryRun) {
      return { ok: true, data: { ...output, dry_run: true, stopped_before_step: i, page_url: await driver.currentUrl() } };
    }
    const step = templated(raw, params);
    const res = await runOne(driver, step, i, dryRun);
    if (!res.ok) return { ...res, data: { ...output, ...res.data } };
    if (step.save_as && res.saved !== undefined) output[step.save_as] = res.saved;
    if (i < recipe.steps.length - 1) await driver.sleep(delayFor(params, rand)); // pacing: one person, one tab
  }
  for (const key of recipe.returns) if (output[key] === undefined || output[key] === null) return { ok: false, data: output, error: `finished but ${key} was not found`, step: recipe.steps.length - 1, screenshot: await driver.screenshot().catch(() => null), dom: await driver.dom().catch(() => null) };
  // where the run ended: the campaign's own URL after opening its card, the post after publishing
  return { ok: true, data: { ...output, page_url: await driver.currentUrl() } };
}
