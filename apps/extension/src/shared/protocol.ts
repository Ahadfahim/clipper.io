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
export type Incoming = Welcome | RunMsg | ActionMsg | Ping;

export type ActionKind = "navigate" | "wait_for" | "query" | "click" | "type" | "attach_file" | "read_text" | "screenshot" | "snapshot";

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
  timeout_ms?: number;
  optional?: boolean; // a missing element skips the step instead of failing
  final?: boolean; // the irreversible click (publish/submit): skipped in dry run
  when?: string; // run only if this param is truthy
  note?: string;
  // single actions from the core's browser tools use these names
  kind?: ActionKind;
};

export type FieldSpec = { selector?: string; attr?: string; regex?: string; text?: boolean };

export type StepOutcome = {
  ok: boolean;
  data?: Record<string, unknown>;
  error?: string;
  challenge?: Challenge | null;
  dom?: string;
  skipped?: boolean;
};
