// Typed API client (generated types in ./schema.d.ts; regenerate with `just gen-api`).
// In fixture mode (`vite --mode fixtures`) requests are answered from /fixtures (exported by
// `clipper fixtures-export`), so the UI runs without the Python core.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

export const FIXTURE_MODE = import.meta.env.MODE === "fixtures";
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8765";

type Manifest = { generated_at: string; paths: string[]; files: Record<string, string> };
let manifestPromise: Promise<Manifest> | null = null;

export function fixtureManifest(): Promise<Manifest> {
  manifestPromise ??= fetch("/fixtures/manifest.json").then((r) => r.json() as Promise<Manifest>);
  return manifestPromise;
}

export function fixtureFileName(url: URL): string {
  const base = url.pathname.replace(/^\/+/, "");
  const query = url.searchParams.toString();
  return query ? `${base}__${query}.json` : `${base}.json`;
}

async function fixtureFetch(input: Request): Promise<Response> {
  const url = new URL(input.url);
  if (input.method !== "GET") {
    return new Response(JSON.stringify({ ok: true, id: null, detail: "fixture mode: not saved" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }
  const manifest = await fixtureManifest();
  const exact = fixtureFileName(url);
  const name = manifest.paths.includes(exact) ? exact : `${url.pathname.replace(/^\/+/, "")}.json`;
  if (!manifest.paths.includes(name)) {
    return new Response(JSON.stringify({ detail: `no fixture for ${url.pathname}` }), { status: 404 });
  }
  return fetch(`/fixtures/${name}`);
}

export const api = createClient<paths>({
  baseUrl: FIXTURE_MODE ? window.location.origin : API_BASE,
  fetch: FIXTURE_MODE ? fixtureFetch : undefined,
});

/** URL for a file the API serves (thumbs, previews); fixture mode maps to the exported copies. */
export function fileUrl(path: string | null | undefined, manifest?: Manifest | null): string | undefined {
  if (!path) return undefined;
  if (FIXTURE_MODE) {
    const mapped = manifest?.files[path];
    return mapped ? `/fixtures/${mapped}` : undefined;
  }
  return `${API_BASE}${path}`;
}

/** Unwraps an openapi-fetch result or throws with the API's error detail. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || data === undefined) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new Error(typeof detail === "string" ? detail : `request failed (${response.status})`);
  }
  return data;
}
