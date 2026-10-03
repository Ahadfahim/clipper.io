// Content script: injected on demand into the Clipper tab by the service worker. Receives one
// step at a time; files arrive in base64 chunks (the page can't fetch from 127.0.0.1 itself).
import type { Step, StepOutcome } from "../shared/protocol";
import { detectChallenge, runStep, simplifiedDom } from "./engine";

type Msg =
  | { type: "clipper.step"; step: Step; fileId?: string }
  | { type: "clipper.check" }
  | { type: "clipper.dom" }
  | { type: "clipper.file-chunk"; id: string; index: number; total: number; name: string; mime: string; data: string }
  | { type: "clipper.file-drop"; id: string };

const w = window as unknown as { __clipperCompanion?: boolean };
const files = new Map<string, { chunks: string[]; name: string; mime: string }>();

function toFile(id: string): File | undefined {
  const f = files.get(id);
  if (!f || f.chunks.some((c) => c === undefined)) return undefined;
  const parts = f.chunks.map((b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
  return new File(parts, f.name, { type: f.mime });
}

export function handle(msg: Msg, respond: (r: StepOutcome) => void): boolean {
  switch (msg.type) {
    case "clipper.file-chunk": {
      const f = files.get(msg.id) ?? { chunks: new Array<string>(msg.total), name: msg.name, mime: msg.mime };
      f.chunks[msg.index] = msg.data;
      files.set(msg.id, f);
      respond({ ok: true });
      return false;
    }
    case "clipper.file-drop":
      files.delete(msg.id);
      respond({ ok: true });
      return false;
    case "clipper.check":
      respond({ ok: true, challenge: detectChallenge(document), data: { url: location.href, title: document.title } });
      return false;
    case "clipper.dom":
      respond({ ok: true, dom: simplifiedDom(document) });
      return false;
    case "clipper.step": {
      const file = msg.fileId ? toFile(msg.fileId) : undefined;
      void runStep(document, msg.step, file)
        // a thrown error (e.g. an invalid selector in a recipe) must still answer, or the service
        // worker only hears "message channel closed" once Chrome gives up on the reply
        .catch((e: unknown): StepOutcome => ({ ok: false, error: `${msg.step.action} failed: ${e instanceof Error ? e.message : String(e)}` }))
        .then((out) => {
          respond(out.ok ? out : { ...out, dom: out.dom ?? simplifiedDom(document) });
          if (msg.fileId) files.delete(msg.fileId);
        });
      return true; // async response
    }
  }
}

if (typeof chrome !== "undefined" && chrome.runtime?.onMessage && !w.__clipperCompanion) {
  w.__clipperCompanion = true;
  chrome.runtime.onMessage.addListener((msg: Msg, _sender, sendResponse) => handle(msg, sendResponse));
}
