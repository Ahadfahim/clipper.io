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
    // Park the tab on a blank page first. A late redirect of the previous page (TikTok sending the
    // tab to its login after load) fires "complete" too, and used to be taken for the new page.
    await this.load(tabId, "about:blank", (t) => t.url === "about:blank", 5_000);
    await this.load(tabId, url, (t) => t.url !== "about:blank", 60_000);
  }

  private load(tabId: number, url: string, arrived: (tab: chrome.tabs.Tab) => boolean, timeoutMs: number): Promise<void> {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(done, timeoutMs);
      function done() {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
      function listener(id: number, info: chrome.tabs.OnUpdatedInfo, tab: chrome.tabs.Tab) {
        if (id === tabId && info.status === "complete" && arrived(tab)) done();
      }
      chrome.tabs.onUpdated.addListener(listener);
      void chrome.tabs.update(tabId, { url, active: true });
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
      // JPEG: a PNG of a busy page on a big window runs to many MB, and the result travels back to the
      // core in one WebSocket message
      return await chrome.tabs.captureVisibleTab(t.windowId, { format: "jpeg", quality: 60 });
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
