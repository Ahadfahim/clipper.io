// Runs recipe steps inside the page. Pure DOM code (tested with jsdom): no chrome.* calls here.
//
// Boundaries (PLAN §5): this only does what a person could do by hand in their own logged-in
// tab. On a CAPTCHA, "verify it's you" or login screen it stops and reports the challenge;
// it never tries to solve or bypass one.
import type { Challenge, FieldSpec, OpenEach, Step, StepOutcome } from "../shared/protocol";

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

/** The text of an element: the value of a field, an attribute, or "innerText" (rendered text with
 * line breaks, no script/style; jsdom has no innerText, so it falls back to textContent there). */
function rawValue(el: Element, attr?: string): string | null {
  if (attr === "innerText") return (el as HTMLElement).innerText ?? el.textContent;
  if (attr) return el.getAttribute(attr);
  return (el as HTMLInputElement).value !== undefined && el.matches("input, textarea") ? (el as HTMLInputElement).value : el.textContent;
}

function readValue(el: Element, spec: { attr?: string; regex?: string }): string | null {
  let v = rawValue(el, spec.attr);
  if (spec.attr === "href" && v) {
    try {
      v = new URL(v, el.ownerDocument.location?.href ?? undefined).href;
    } catch {
      /* keep as is */
    }
  }
  v = (v ?? "").replace(/\s+/g, " ").trim();
  if (spec.regex) {
    const m = new RegExp(spec.regex, "i").exec(v);
    return m ? (m[1] ?? m[0]) : null;
  }
  return v;
}

/** `all`: every match. With a regex, every capture across them ("tiktok, youtube"); without, their
 * texts joined with " | ". */
function readAll(els: Element[], f: FieldSpec): string | null {
  const texts = els.map((e) => readValue(e, { attr: f.attr })).filter((t): t is string => Boolean(t));
  if (!f.regex) return texts.length ? texts.join(" | ") : null;
  const re = new RegExp(f.regex, "gi");
  const hits = texts.flatMap((t) => [...t.matchAll(re)].map((m) => m[1] ?? m[0]));
  return hits.length ? [...new Set(hits)].join(", ") : null;
}

function extract(el: Element | Document, fields: Record<string, FieldSpec>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [key, f] of Object.entries(fields)) {
    if (f.all) {
      out[key] = readAll(f.selector ? [...el.querySelectorAll(f.selector)] : el instanceof Element ? [el] : [], f);
      continue;
    }
    const target = f.selector ? el.querySelector(f.selector) : el instanceof Element ? el : null;
    out[key] = target ? readValue(target, f) : null;
  }
  return out;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function until(test: () => boolean, timeoutMs: number, pollMs = 100): Promise<boolean> {
  for (const end = Date.now() + timeoutMs; Date.now() < end; await sleep(pollMs)) if (test()) return true;
  return test();
}

/** query + open_each: for each match, open it (click), wait for its panel, read the panel and the
 * URL, close it again (Escape, a close button, or "history.back" for items that open a page), then
 * move on. For lists whose items aren't links: Vyro's cards open a dialog and put the campaign id in
 * the URL; Whop's open the campaign's page. Read-only: it only opens and closes detail views. */
async function openEach(doc: Document, selector: string, rows: Record<string, unknown>[], spec: OpenEach): Promise<string | null> {
  const timeout = spec.timeout_ms ?? 10_000;
  const shown = () => findAll(doc, spec.wait_for).length > 0;
  for (let i = 0; i < rows.length; i++) {
    // a panel can already be open: sites restore the last one (Vyro keeps ?c= across reloads)
    if (shown() && !(await closePanel())) return `a panel was already open and didn't close`;
    // after going back, the list renders again before it can be clicked
    if (!(await until(() => findAll(doc, selector).length > i, timeout))) return `item ${i + 1} is gone (the list changed while reading it)`;
    const before = doc.location?.href ?? "";
    const opened = () => shown() && (doc.location?.href ?? "") !== before;
    let target: Element | null = null;
    // A page can render its list before its scripts attach the click handlers (hydration), and a
    // click in that window does nothing: try again while nothing has opened.
    for (let attempt = 0; attempt < 3 && !opened(); attempt++) {
      if (!shown()) {
        // nothing open yet (a panel that's showing but hasn't updated the URL is just slow: wait)
        const item = findAll(doc, selector)[i]; // fresh: the list may have re-rendered
        if (!item) return `item ${i + 1} is gone (the list changed while reading it)`;
        // responsive layouts render some text twice and hide one copy: click the visible one
        target = spec.click ? ([...item.querySelectorAll(spec.click)].find(isVisible) ?? item) : item;
        click(target);
      }
      await until(opened, attempt < 2 ? Math.min(4000, timeout) : timeout);
    }
    if (!opened()) {
      const what = target ? `${target.tagName.toLowerCase()} "${norm(target.textContent).slice(0, 40)}"` : "nothing";
      return `item ${i + 1} didn't open: clicked ${what}; ${shown() ? "panel shown" : `no ${spec.wait_for}`}; url ${doc.location?.href ?? "?"}`;
    }
    await sleep(spec.settle_ms ?? 300); // let the panel finish rendering its details
    const row = rows[i]!;
    const url = doc.location?.href ?? "";
    row["opened_url"] = url;
    for (const [key, re] of Object.entries(spec.url_fields ?? {})) row[key] = new RegExp(re, "i").exec(url)?.[1] ?? null;
    Object.assign(row, extract(doc, spec.fields ?? {}));
    if (!(await closePanel())) return `item ${i + 1} didn't close`;
    await sleep(250 + Math.round(Math.random() * 500)); // one person clicking through a list
  }
  return null;

  async function closePanel(): Promise<boolean> {
    if (spec.close === "history.back") {
      doc.defaultView?.history.back();
      return until(() => !shown(), timeout);
    }
    const closer = spec.close ? findElement(doc, { selector: spec.close }) : null;
    if (closer) click(closer);
    else (doc.activeElement ?? doc.body).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true, cancelable: true }));
    return until(() => !shown(), timeout);
  }
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
const NO_TEXT = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG"]);

/** The page's readable text, without inline script/style payloads. `body.textContent` includes
 * those, and on sites that inline their state as JSON (Instagram) the real text starts past any
 * sensible cut-off, while words like "two-factor" inside the JSON look like a verification screen. */
export function pageText(doc: Document, max = 20_000): string {
  if (!doc.body) return "";
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.nodeType === Node.ELEMENT_NODE && (NO_TEXT.has((n as Element).tagName.toUpperCase()) || (n as HTMLElement).hidden)
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  let out = "";
  for (let n = walker.nextNode(); n && out.length < max; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) out += ` ${n.nodeValue ?? ""}`;
  }
  return norm(out).slice(0, max);
}

/** A CAPTCHA widget someone has to deal with: visible and widget-sized. Sites load invisible
 * Turnstile/reCAPTCHA frames and show reCAPTCHA's "protected by" badge on ordinary pages; those
 * aren't challenges, and treating them as one pauses the account for nothing. */
function captchaWidget(el: Element): boolean {
  if (!isVisible(el) || el.closest(".grecaptcha-badge")) return false;
  const cs = el.ownerDocument.defaultView?.getComputedStyle(el);
  const w = parseFloat(cs?.width ?? ""),
    h = parseFloat(cs?.height ?? "");
  return !(w < 30 || h < 30); // NaN (no layout to measure) counts as a widget
}

export type ChallengeHit = { challenge: Challenge; reason: string };

/** Detects a CAPTCHA, "verify it's you" or login wall, and says what gave it away. Never interacts with it. */
export function findChallenge(doc: Document, url: string = doc.location?.href ?? ""): ChallengeHit | null {
  for (const f of doc.querySelectorAll("iframe")) {
    const src = (f.getAttribute("src") ?? "").toLowerCase();
    const kind = CAPTCHA_FRAMES.find((k) => src.includes(k));
    if (kind && !src.includes("size=invisible") && captchaWidget(f)) return { challenge: "captcha", reason: `${kind} frame` };
  }
  for (const s of CAPTCHA_SELECTORS) {
    if (findAll(doc, s).some(captchaWidget)) return { challenge: "captcha", reason: s };
  }
  const text = pageText(doc);
  let path = "";
  try {
    path = new URL(url).pathname;
  } catch {
    /* about:blank */
  }
  if (CHALLENGE_URL.test(path)) return { challenge: "verification", reason: `address ${path}` };
  const said = VERIFY_TEXT.find((t) => text.includes(t));
  if (said) return { challenge: "verification", reason: `"${said}" on the page` };
  if (LOGIN_URL.test(path)) return { challenge: "login", reason: `address ${path}` };
  if (findAll(doc, "input[type=password]").length > 0 && /log in|sign in|password/.test(text)) return { challenge: "login", reason: "a password field" };
  return null;
}

export function detectChallenge(doc: Document, url?: string): Challenge | null {
  return findChallenge(doc, url)?.challenge ?? null;
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

const OUTLINE_ATTRS = new Set(["id", "href", "role", "type", "name", "src", "datetime", "title", "alt", "placeholder"]);

/** One element's subtree as tags, a few classes, ids, data-/aria- attributes and own text. Probes
 * use it to write selectors for cards and forms the simplified DOM leaves out. */
export function outline(root: Element, max = 12_000): string {
  const lines: string[] = [];
  let size = 0;
  const walk = (el: Element, depth: number) => {
    if (size > max) return;
    const bits = [el.tagName.toLowerCase()];
    const cls = (el.getAttribute("class") ?? "").trim().split(/\s+/).filter(Boolean);
    if (cls.length) bits.push(`.${cls.slice(0, 4).join(".")}${cls.length > 4 ? "…" : ""}`);
    for (const a of el.attributes) {
      if (OUTLINE_ATTRS.has(a.name) || a.name.startsWith("data-") || a.name.startsWith("aria-")) bits.push(`[${a.name}=${a.value.slice(0, 70)}]`);
    }
    const skip = NO_TEXT.has(el.tagName.toUpperCase());
    const own = skip ? "" : norm([...el.childNodes].filter((c) => c.nodeType === Node.TEXT_NODE).map((c) => c.nodeValue).join(" ")).slice(0, 80);
    const line = `${"  ".repeat(Math.min(depth, 12))}${bits.join("")}${own ? ` "${own}"` : ""}`;
    lines.push(line);
    size += line.length + 1;
    if (skip) return;
    for (const child of el.children) walk(child, depth + 1);
  };
  walk(root, 0);
  return size > max ? `${lines.join("\n").slice(0, max)}\n…` : lines.join("\n");
}

// ---------------------------------------------------------------- steps

/** Runs one already-templated step. `file` is set for attach_file (sent over by the service worker). */
export async function runStep(doc: Document, step: Step, file?: File): Promise<StepOutcome> {
  const hit = findChallenge(doc);
  if (hit) return { ok: false, challenge: hit.challenge, error: `${hit.challenge} screen (${hit.reason}): stopped (handle it by hand, then resume the account)` };
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
      // file inputs are usually hidden behind a styled button: don't require visibility
      const el = doc.querySelector(step.selector ?? "input[type=file]");
      if (step.check_only) return el ? { ok: true, data: { file_input: true } } : { ok: false, error: `no file input: ${step.selector}` };
      if (!file) return { ok: false, error: "no file was sent for attach_file" };
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
        const els = findAll(doc, step.selector ?? "*");
        if (step.open_each) {
          const rows: Record<string, unknown>[] = els.map((el) => extract(el, step.fields ?? {}));
          const problem = await openEach(doc, step.selector ?? "*", rows, step.open_each);
          if (problem) return { ok: false, error: `open_each: ${problem}` };
          return { ok: true, data: { value: rows, count: rows.length } };
        }
        const items = els.map((el) => (step.fields ? extract(el, step.fields) : readValue(el, step)));
        return { ok: true, data: { value: items, count: items.length } };
      }
      const el = findElement(doc, target);
      if (step.exists) return { ok: true, data: { value: Boolean(el), count: el ? 1 : 0 } };
      return { ok: true, data: { value: el ? (step.fields ? extract(el, step.fields) : readValue(el, step)) : null, count: el ? 1 : 0 } };
    }
    case "snapshot":
      return { ok: true, data: { url: doc.location?.href ?? null }, dom: simplifiedDom(doc) };
    case "outline": {
      const pool = findAll(doc, step.selector ?? "body");
      const want = norm(step.text);
      let el = (want ? pool.find((e) => norm(e.textContent).includes(want)) : pool[0]) ?? null;
      if (!el) return { ok: false, error: `nothing to outline: ${step.selector ?? ""} ${step.text ?? ""}`.trim() };
      for (let i = 0; i < (step.up ?? 0) && el.parentElement; i++) el = el.parentElement;
      return { ok: true, data: { count: pool.length }, dom: outline(el) };
    }
    default:
      return { ok: false, error: `${step.action} runs in the service worker` };
  }
}
