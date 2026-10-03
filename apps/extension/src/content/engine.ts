// Runs recipe steps inside the page. Pure DOM code (tested with jsdom): no chrome.* calls here.
//
// Boundaries (PLAN §5): this only does what a person could do by hand in their own logged-in
// tab. On a CAPTCHA, "verify it's you" or login screen it stops and reports the challenge;
// it never tries to solve or bypass one.
import type { Challenge, FieldSpec, Step, StepOutcome } from "../shared/protocol";

const norm = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim().toLowerCase();

export function isVisible(el: Element): boolean {
  if (!(el instanceof HTMLElement)) return true;
  if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
  const win = el.ownerDocument.defaultView;
  for (let n: HTMLElement | null = el; n; n = n.parentElement) {
    const cs = win?.getComputedStyle(n);
    if (cs && (cs.display === "none" || cs.visibility === "hidden")) return false;
  }
  return true;
}

const CLICKABLE = "button, a, [role=button], [role=menuitem], [role=option], [role=tab], label, input[type=submit], input[type=button], summary";

/** Finds one element by selector and/or visible text. Text matches exactly first, then by prefix. */
export function findElement(doc: Document, spec: { selector?: string; text?: string }): Element | null {
  const want = norm(spec.text);
  let pool: Element[];
  try {
    pool = [...doc.querySelectorAll(spec.selector ?? CLICKABLE)];
  } catch {
    return null; // invalid selector
  }
  pool = pool.filter(isVisible);
  if (!want) return pool[0] ?? null;
  const label = (el: Element) => norm(el.getAttribute("aria-label")) || norm(el.textContent) || norm((el as HTMLInputElement).value);
  return pool.find((el) => label(el) === want) ?? pool.find((el) => label(el).startsWith(want)) ?? null;
}

export function findAll(doc: Document, selector: string): Element[] {
  try {
    return [...doc.querySelectorAll(selector)].filter(isVisible);
  } catch {
    return [];
  }
}

export async function waitFor(doc: Document, spec: { selector?: string; text?: string }, timeoutMs = 15_000, pollMs = 100): Promise<Element | null> {
  const end = Date.now() + timeoutMs;
  for (;;) {
    const el = findElement(doc, spec);
    if (el) return el;
    if (Date.now() >= end) return null;
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

export function click(el: Element): void {
  (el as HTMLElement).scrollIntoView?.({ block: "center" });
  const view = el.ownerDocument.defaultView as (Window & typeof globalThis) | null;
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
    const Ctor = type.startsWith("pointer") && view?.PointerEvent ? view.PointerEvent : (view?.MouseEvent ?? MouseEvent);
    el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true }));
  }
  (el as HTMLElement).click();
}

/** Types into inputs, textareas and contenteditable editors, firing the events frameworks listen to. */
export function typeInto(el: Element, value: string, clear = true): void {
  const view = el.ownerDocument.defaultView;
  (el as HTMLElement).focus?.();
  if (el instanceof (view?.HTMLInputElement ?? HTMLInputElement) || el instanceof (view?.HTMLTextAreaElement ?? HTMLTextAreaElement)) {
    const proto = el instanceof (view?.HTMLTextAreaElement ?? HTMLTextAreaElement) ? (view?.HTMLTextAreaElement ?? HTMLTextAreaElement).prototype : (view?.HTMLInputElement ?? HTMLInputElement).prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    const next = clear ? value : (el as HTMLInputElement).value + value;
    if (setter) setter.call(el, next);
    else (el as HTMLInputElement).value = next;
  } else {
    if (clear) el.textContent = "";
    el.textContent = (el.textContent ?? "") + value;
  }
  el.dispatchEvent(new (view?.InputEvent ?? Event)("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/** Puts a File on an <input type=file> (or drops it on a drop zone) the way a user's pick would. */
export function attachFile(el: Element, file: File): void {
  const view = el.ownerDocument.defaultView as (Window & typeof globalThis) | null;
  const DT = view?.DataTransfer ?? (globalThis as { DataTransfer?: typeof DataTransfer }).DataTransfer;
  if (!DT) throw new Error("DataTransfer is not available");
  const dt = new DT();
  dt.items.add(file);
  if (el instanceof (view?.HTMLInputElement ?? HTMLInputElement) && (el as HTMLInputElement).type === "file") {
    (el as HTMLInputElement).files = dt.files;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  for (const type of ["dragenter", "dragover", "drop"]) {
    const ev = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(ev, "dataTransfer", { value: dt });
    el.dispatchEvent(ev);
  }
}

function readValue(el: Element, spec: { attr?: string; regex?: string }): string | null {
  let v = spec.attr ? el.getAttribute(spec.attr) : (el as HTMLInputElement).value !== undefined && el.matches("input, textarea") ? (el as HTMLInputElement).value : el.textContent;
  if (spec.attr === "href" && v) {
    try {
      v = new URL(v, el.ownerDocument.location?.href ?? undefined).href;
    } catch {
      /* keep as is */
    }
  }
  v = (v ?? "").replace(/\s+/g, " ").trim();
  if (spec.regex) {
    const m = new RegExp(spec.regex).exec(v);
    return m ? (m[1] ?? m[0]) : null;
  }
  return v;
}

function extract(el: Element, fields: Record<string, FieldSpec>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [key, f] of Object.entries(fields)) {
    const target = f.selector ? el.querySelector(f.selector) : el;
    out[key] = target ? readValue(target, f) : null;
  }
  return out;
}

// ---------------------------------------------------------------- challenges

const CAPTCHA_FRAMES = ["recaptcha", "hcaptcha", "arkoselabs", "funcaptcha", "captcha-delivery", "challenges.cloudflare.com", "turnstile"];
const CAPTCHA_SELECTORS = [
  ".g-recaptcha",
  ".h-captcha",
  "#captcha_container",
  ".captcha_verify_container",
  "[id*=captcha i]",
  "[class*=captcha i]",
  "[data-testid*=captcha i]",
  ".cf-turnstile",
];
const VERIFY_TEXT = [
  "verify it's you",
  "verify it’s you",
  "confirm it's you",
  "confirm it’s you",
  "verify you are human",
  "verify you're human",
  "security check",
  "suspicious activity",
  "unusual activity",
  "help us confirm",
  "enter the code we sent",
  "two-factor",
  "2-step verification",
  "drag the slider",
  "slide to verify",
];
const LOGIN_URL = /\/(login|signin|sign-in|accounts\/login|i\/flow\/login|ServiceLogin)\b/i;
const CHALLENGE_URL = /\/(challenge|checkpoint|captcha)\b/i;

/** Detects a CAPTCHA, "verify it's you" or login wall. Never interacts with it. */
export function detectChallenge(doc: Document, url: string = doc.location?.href ?? ""): Challenge | null {
  const frames = [...doc.querySelectorAll("iframe")].map((f) => (f.getAttribute("src") ?? "").toLowerCase());
  if (frames.some((src) => CAPTCHA_FRAMES.some((k) => src.includes(k)))) return "captcha";
  if (CAPTCHA_SELECTORS.some((s) => findAll(doc, s).length > 0)) return "captcha";
  const text = norm(doc.body?.textContent).slice(0, 20_000);
  let path = "";
  try {
    path = new URL(url).pathname;
  } catch {
    /* about:blank */
  }
  if (CHALLENGE_URL.test(path) || VERIFY_TEXT.some((t) => text.includes(t))) return "verification";
  const password = findAll(doc, "input[type=password]").length > 0;
  if (LOGIN_URL.test(path) || (password && /log in|sign in|password/.test(text))) return "login";
  return null;
}

// ---------------------------------------------------------------- simplified DOM (for failures)

const KEEP = new Set(["A", "BUTTON", "INPUT", "TEXTAREA", "SELECT", "LABEL", "H1", "H2", "H3", "IMG", "VIDEO", "IFRAME", "DIALOG", "FORM"]);

/** A compact outline of what's on screen: interactive elements and headings with ids, roles and text. */
export function simplifiedDom(doc: Document, max = 6000): string {
  const lines: string[] = [];
  const walk = (el: Element, depth: number) => {
    if (!isVisible(el)) return;
    const role = el.getAttribute("role");
    const editable = el.getAttribute("contenteditable") === "true";
    if (KEEP.has(el.tagName) || role || editable) {
      const bits = [el.tagName.toLowerCase()];
      if (el.id) bits.push(`#${el.id}`);
      for (const a of ["type", "name", "role", "aria-label", "placeholder", "href", "data-testid", "data-e2e", "src"]) {
        const v = el.getAttribute(a);
        if (v) bits.push(`[${a}=${v.slice(0, 80)}]`);
      }
      if (editable) bits.push("[contenteditable]");
      const text = norm(el.textContent).slice(0, 80);
      lines.push(`${"  ".repeat(Math.min(depth, 6))}${bits.join("")}${text ? ` "${text}"` : ""}`);
    }
    for (const child of el.children) walk(child, depth + (KEEP.has(el.tagName) ? 1 : 0));
  };
  if (doc.body) walk(doc.body, 0);
  const out = lines.join("\n");
  return out.length > max ? `${out.slice(0, max)}\n…` : out;
}

// ---------------------------------------------------------------- steps

/** Runs one already-templated step. `file` is set for attach_file (sent over by the service worker). */
export async function runStep(doc: Document, step: Step, file?: File): Promise<StepOutcome> {
  const challenge = detectChallenge(doc);
  if (challenge) return { ok: false, challenge, error: `${challenge} screen: stopped (handle it by hand, then resume the account)` };
  const timeout = step.timeout_ms ?? 15_000;
  const target = { selector: step.selector, text: step.text };
  switch (step.action) {
    case "wait_for": {
      const el = await waitFor(doc, target, timeout);
      return el ? { ok: true } : { ok: false, error: `not found within ${timeout} ms: ${step.selector ?? step.text}` };
    }
    case "click": {
      const el = await waitFor(doc, target, timeout);
      if (!el) return { ok: false, error: `nothing to click: ${step.selector ?? step.text}` };
      click(el);
      return { ok: true };
    }
    case "type": {
      const el = await waitFor(doc, target, timeout);
      if (!el) return { ok: false, error: `no field: ${step.selector}` };
      typeInto(el, step.value ?? "", step.clear !== false);
      return { ok: true };
    }
    case "attach_file": {
      if (!file) return { ok: false, error: "no file was sent for attach_file" };
      // file inputs are usually hidden behind a styled button: don't require visibility
      const el = doc.querySelector(step.selector ?? "input[type=file]");
      if (!el) return { ok: false, error: `no file input: ${step.selector}` };
      attachFile(el, file);
      return { ok: true, data: { attached: file.name, bytes: file.size } };
    }
    case "read_text": {
      const el = await waitFor(doc, target, timeout);
      if (!el) return { ok: false, error: `nothing to read: ${step.selector ?? step.text}` };
      const value = readValue(el, step);
      return value === null || value === "" ? { ok: false, error: "the element had no matching text" } : { ok: true, data: { value } };
    }
    case "query": {
      if (step.all) {
        await waitFor(doc, target, timeout);
        const items = findAll(doc, step.selector ?? "*").map((el) => (step.fields ? extract(el, step.fields) : readValue(el, step)));
        return { ok: true, data: { value: items, count: items.length } };
      }
      const el = findElement(doc, target);
      if (step.exists) return { ok: true, data: { value: Boolean(el), count: el ? 1 : 0 } };
      return { ok: true, data: { value: el ? (step.fields ? extract(el, step.fields) : readValue(el, step)) : null, count: el ? 1 : 0 } };
    }
    case "snapshot":
      return { ok: true, data: { url: doc.location?.href ?? null }, dom: simplifiedDom(doc) };
    default:
      return { ok: false, error: `${step.action} runs in the service worker` };
  }
}
