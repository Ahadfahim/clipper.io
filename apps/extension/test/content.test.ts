import { describe, expect, it, vi } from "vitest";
import { handle } from "../src/content/content";

describe("content script messages", () => {
  it("reassembles a chunked file and attaches it", async () => {
    document.body.innerHTML = `<input id="f" type="file">`;
    const bytes = new Uint8Array([104, 101, 108, 108, 111, 33]);
    const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u));
    const respond = vi.fn();
    handle({ type: "clipper.file-chunk", id: "x", index: 1, total: 2, name: "clip.mp4", mime: "video/mp4", data: b64(bytes.subarray(3)) }, respond);
    handle({ type: "clipper.file-chunk", id: "x", index: 0, total: 2, name: "clip.mp4", mime: "video/mp4", data: b64(bytes.subarray(0, 3)) }, respond);
    const done = new Promise<unknown>((resolve) => handle({ type: "clipper.step", step: { action: "attach_file", selector: "#f", file: "x" }, fileId: "x" }, resolve));
    expect(await done).toMatchObject({ ok: true, data: { attached: "clip.mp4", bytes: 6 } });
    const file = (document.getElementById("f") as HTMLInputElement).files?.[0];
    const text = await new Promise<string>((resolve) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result));
      r.readAsText(file!);
    });
    expect(text).toBe("hello!");
  });

  it("reports challenges and the simplified DOM on failure", async () => {
    document.body.innerHTML = `<h1>Verify it's you</h1>`;
    const out = await new Promise<{ ok: boolean; challenge?: string | null; dom?: string }>((resolve) => handle({ type: "clipper.step", step: { action: "click", selector: "#post" } }, resolve));
    expect(out.ok).toBe(false);
    expect(out.challenge).toBe("verification");
    expect(out.dom).toContain("h1");
  });
});
