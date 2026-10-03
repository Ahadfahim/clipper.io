// Recipe format: a versioned JSON list of steps per site/action (recipes/*.json, schema in
// recipes/schema.json). Every shipped recipe is status "UNVERIFIED" until it has been run against
// the real site on the user's machine.
import type { ActionKind, Step } from "./protocol";

export type ParamSpec = { type: "string" | "number" | "boolean" | "array"; required?: boolean; description?: string };

export type Recipe = {
  name: string; // "<site>.<action>"
  version: number;
  site: string;
  status: "UNVERIFIED" | "verified";
  description: string;
  start_url?: string;
  params: Record<string, ParamSpec>;
  steps: Step[];
  returns: string[];
};

const ACTIONS: ActionKind[] = ["navigate", "wait_for", "query", "click", "type", "attach_file", "read_text", "screenshot", "snapshot"];

/** Returns a list of problems (empty = valid). Kept dependency-free so the service worker can use it. */
export function validateRecipe(r: unknown): string[] {
  const errs: string[] = [];
  if (!r || typeof r !== "object") return ["recipe must be an object"];
  const x = r as Partial<Recipe>;
  if (typeof x.name !== "string" || !/^[a-z]+\.[a-z_]+$/.test(x.name)) errs.push("name must look like site.action");
  if (typeof x.version !== "number" || x.version < 1) errs.push("version must be >= 1");
  if (typeof x.site !== "string" || (x.name && !x.name.startsWith(`${x.site}.`))) errs.push("site must match the name prefix");
  if (x.status !== "UNVERIFIED" && x.status !== "verified") errs.push("status must be UNVERIFIED or verified");
  if (!Array.isArray(x.steps) || x.steps.length === 0) errs.push("steps must be a non-empty list");
  if (!Array.isArray(x.returns)) errs.push("returns must be a list");
  const params = x.params ?? {};
  (x.steps ?? []).forEach((s, i) => {
    if (!ACTIONS.includes(s.action)) errs.push(`step ${i}: unknown action ${String(s.action)}`);
    if (s.action === "navigate" && !s.url) errs.push(`step ${i}: navigate needs url`);
    if (["click", "wait_for", "read_text", "query"].includes(s.action) && !s.selector && !s.text) errs.push(`step ${i}: ${s.action} needs selector or text`);
    if (s.action === "type" && (!s.selector || s.value === undefined)) errs.push(`step ${i}: type needs selector and value`);
    if (s.action === "attach_file" && (!s.selector || !s.file)) errs.push(`step ${i}: attach_file needs selector and file`);
    for (const ref of templateRefs(JSON.stringify(s))) if (!(ref in params)) errs.push(`step ${i}: unknown param {{${ref}}}`);
    for (const f of templateFilters(JSON.stringify(s))) if (!KNOWN_FILTERS.includes(f)) errs.push(`step ${i}: unknown filter |${f}`);
    if (s.when && !(s.when in params)) errs.push(`step ${i}: when refers to unknown param ${s.when}`);
    if (s.unless && !(s.unless in params)) errs.push(`step ${i}: unless refers to unknown param ${s.unless}`);
  });
  const saved = new Set((x.steps ?? []).map((s) => s.save_as).filter(Boolean));
  for (const key of x.returns ?? []) if (!saved.has(key)) errs.push(`returns ${key} but no step saves it`);
  return errs;
}

const TEMPLATE = /\{\{\s*([a-z_]+)\s*(?:\|\s*([a-z_]+)\s*)?\}\}/g;

/** Filters usable in templates: {{handle|noat}} drops a leading @, {{hashtags|tags}} adds # to each. */
const FILTERS: Record<string, (v: string) => string> = {
  noat: (v) => v.replace(/^@/, ""),
  tags: (v) =>
    v
      .split(/\s+/)
      .filter(Boolean)
      .map((t) => (t.startsWith("#") ? t : `#${t}`))
      .join(" "),
  url: (v) => encodeURIComponent(v),
};

export function templateRefs(text: string): string[] {
  return [...text.matchAll(TEMPLATE)].map((m) => m[1]!);
}

export function templateFilters(text: string): string[] {
  return [...text.matchAll(TEMPLATE)].map((m) => m[2]).filter((f): f is string => Boolean(f));
}

/** Fills {{param}} / {{param|filter}} placeholders; arrays join with spaces (hashtags). */
export function fill(template: string | undefined, params: Record<string, unknown>): string | undefined {
  if (template === undefined) return undefined;
  return template.replace(TEMPLATE, (_m, k: string, f: string | undefined) => {
    const v = params[k];
    const s = v === undefined || v === null ? "" : Array.isArray(v) ? v.join(" ") : String(v);
    return f ? (FILTERS[f]?.(s) ?? s) : s;
  });
}

export const KNOWN_FILTERS = Object.keys(FILTERS);

export function missingParams(recipe: Recipe, params: Record<string, unknown>): string[] {
  return Object.entries(recipe.params)
    .filter(([k, spec]) => spec.required && (params[k] === undefined || params[k] === null || params[k] === ""))
    .map(([k]) => k);
}
