// The real TabDriver: one dedicated "Clipper" tab per Chrome profile, driven through
// chrome.tabs / chrome.scripting and the content script. LOCAL-VERIFY in Chrome.
import type { Step, StepOutcome } from "../shared/protocol";
import type { TabDriver } from "./runner";

const CHUNK = 4 * 1024 * 1024; // bytes per message (base64 grows it by a third)

function toBase64(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export class ChromeTabDriver implements TabDriver {
  private tabId: number | null = null;

  private async tab(): Promise<number> {
    if (this.tabId !== null) {
      try {
        await chrome.tabs.get(this.tabId);
        return this.tabId;
      } catch {
        this.tabId = null;
      }
    }
    const stored = (await chrome.storage.session.get("clipperTab"))["clipperTab"] as number | undefined;
    if (stored !== undefined) {
      try {
        await chrome.tabs.get(stored);
        this.tabId = stored;
        return stored;
      } catch {
        /* closed */
      }
    }
    const t = await chrome.tabs.create({ url: "about:blank", active: true });
    this.tabId = t.id ?? null;
    await chrome.storage.session.set({ clipperTab: this.tabId });
    if (this.tabId === null) throw new Error("couldn't open a tab");
    return this.tabId;
  }

  private async inject(): Promise<number> {
    const tabId = await this.tab();
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    return tabId;
  }

  private async send<T>(msg: unknown): Promise<T> {
    const tabId = await this.inject();
    return (await chrome.tabs.sendMessage(tabId, msg)) as T;
  }

  async navigate(url: string): Promise<void> {
    const tabId = await this.tab();
    await chrome.tabs.update(tabId, { url, active: true });
    await new Promise<void>((resolve) => {
      const timer = setTimeout(done, 60_000);
      function done() {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
      function listener(id: number, info: chrome.tabs.OnUpdatedInfo) {
        if (id === tabId && info.status === "complete") done();
      }
      chrome.tabs.onUpdated.addListener(listener);
    });
  }

  async currentUrl(): Promise<string | null> {
    const t = await chrome.tabs.get(await this.tab());
    return t.url ?? null;
  }

  step(step: Step, fileId?: string): Promise<StepOutcome> {
    return this.send<StepOutcome>({ type: "clipper.step", step, fileId });
  }

  check(): Promise<StepOutcome> {
    return this.send<StepOutcome>({ type: "clipper.check" });
  }

  async dom(): Promise<string> {
    return (await this.send<StepOutcome>({ type: "clipper.dom" })).dom ?? "";
  }

  async screenshot(): Promise<string | null> {
    const t = await chrome.tabs.get(await this.tab());
    try {
      return await chrome.tabs.captureVisibleTab(t.windowId, { format: "png" });
    } catch {
      return null; // window minimized or another tab in front
    }
  }

  async sendFile(id: string, bytes: Uint8Array, name: string, mime: string): Promise<void> {
    const total = Math.max(1, Math.ceil(bytes.length / CHUNK));
    for (let i = 0; i < total; i++) {
      await this.send({ type: "clipper.file-chunk", id, index: i, total, name, mime, data: toBase64(bytes.subarray(i * CHUNK, (i + 1) * CHUNK)) });
    }
  }

  async fetchFile(url: string): Promise<{ bytes: Uint8Array; mime: string }> {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`couldn't get the clip from the core (${res.status})`);
    return { bytes: new Uint8Array(await res.arrayBuffer()), mime: res.headers.get("content-type") ?? "video/mp4" };
  }

  sleep(ms: number): Promise<void> {
    return new Promise((r) => setTimeout(r, ms));
  }
}
