import "@testing-library/jest-dom/vitest";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => cleanup());

// Serve /fixtures/... from public/fixtures so screens render the exported fixture data.
const root = resolve(__dirname, "../../public");
const realFetch = globalThis.fetch;
vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const path = url.startsWith("/") ? url : new URL(url).pathname;
  if (path.startsWith("/fixtures/")) {
    try {
      const body = await readFile(resolve(root, `.${decodeURIComponent(path)}`), "utf-8");
      return new Response(body, { status: 200, headers: { "content-type": "application/json" } });
    } catch {
      return new Response("not found", { status: 404 });
    }
  }
  return realFetch(input, init);
});

// jsdom lacks these browser APIs used by panes, charts and the timeline
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", RO);
Object.defineProperty(window, "matchMedia", {
  value: (q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false }),
});
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;
Element.prototype.scrollIntoView = () => undefined;
Element.prototype.scrollTo = (() => undefined) as typeof Element.prototype.scrollTo;
window.scrollTo = (() => undefined) as typeof window.scrollTo;
