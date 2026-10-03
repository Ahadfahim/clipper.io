// Wire protocol between clipper-core and the Companion (JSON over WebSocket).
// Mirrors core/clipper/browser/protocol.py; keep PROTOCOL_VERSION in sync.

export const PROTOCOL_VERSION = 1;

export type Challenge = "login" | "captcha" | "verification";

// extension -> core
export type Hello = { type: "hello"; profile: string; token: string; version: string; protocol: number; url: string | null };
export type ResultMsg = {
  type: "result";
  id: string;
  ok: boolean;
  data: Record<string, unknown>;
  error?: string | null;
  step?: number | null;
  screenshot?: string | null;
  dom?: string | null;
  challenge?: Challenge | null;
};
export type StatusMsg = { type: "status"; url: string | null; title: string | null };
export type Pong = { type: "pong" };

// core -> extension
export type Welcome = { type: "welcome"; profile: string; protocol: number };
export type RunMsg = { type: "run"; id: string; recipe: string; params: Record<string, unknown>; dry_run: boolean };
export type ActionMsg = { type: "action"; id: string; action: Step };
export type Ping = { type: "ping" };
export type ReloadMsg = { type: "reload" }; // reload the extension (after the core rebuilt it)
export type Incoming = Welcome | RunMsg | ActionMsg | Ping | ReloadMsg;

export type ActionKind = "navigate" | "wait_for" | "query" | "click" | "type" | "attach_file" | "read_text" | "screenshot" | "snapshot" | "outline";

/** One recipe step (also used for single `action` requests from the browser tools). */
export type Step = {
  action: ActionKind;
  selector?: string;
  text?: string; // match an element by its visible text instead of (or together with) a selector
  value?: string; // type: what to type (templated)
  url?: string; // navigate
  file?: string; // attach_file: URL of the clip on 127.0.0.1 (templated)
  name?: string; // attach_file: file name
  clear?: boolean;
  attr?: string; // read_text/query: read an attribute instead of text
  all?: boolean; // query: every match
  exists?: boolean; // query: true/false instead of the element's text
  fields?: Record<string, FieldSpec>; // query: structured extraction per match
  save_as?: string; // put the result in the recipe output under this key
  regex?: string; // read_text: keep the first capture group
  up?: number; // outline (probes only): climb this many parents from the match
  open_each?: OpenEach; // query + all: open each match (click), read its panel and URL, close it
  timeout_ms?: number;
  optional?: boolean; // a missing element skips the step instead of failing
  final?: boolean; // the irreversible click (publish/submit): skipped in dry run
  when?: string; // run only if this param is truthy
  unless?: string; // skip if this param is truthy
  check_only?: boolean; // attach_file in a dry run: only check the file input is there
  note?: string;
  // single actions from the core's browser tools use these names
  kind?: ActionKind;
};

export type FieldSpec = { selector?: string; attr?: string; regex?: string; text?: boolean; all?: boolean };

/** query + all + open_each: for lists whose items open a panel instead of linking somewhere. */
export type OpenEach = {
  click?: string; // what to click inside each match (default: the match)
  wait_for: string; // what shows once it's open
  fields?: Record<string, FieldSpec>; // read from the page while it's open
  url_fields?: Record<string, string>; // name -> regex on the URL while it's open (first group)
  close?: string; // a close button, or "history.back" when the item opened a page; default: press Escape
  settle_ms?: number;
  timeout_ms?: number;
};

export type StepOutcome = {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: string;
  challenge?: Challenge | null;
  dom?: string;
  skipped?: boolean;
};
