// Companion service worker: pairs with the local core over WebSocket and runs recipes in the
// dedicated Clipper tab. Settings (profile name, pairing token, port) live in chrome.storage.local
// and are set on the options page.
import { hostAllowed } from "../shared/allowlist";
import { CompanionBridge, type BridgeState, type SocketLike } from "./bridge";
import { ChromeTabDriver } from "./driver";
import { RECIPES } from "./recipes";

type Config = { profile: string; token: string; port: number };

let bridge: CompanionBridge | null = null;
let state: { state: BridgeState; detail?: string } = { state: "idle" };

async function loadConfig(): Promise<Config | null> {
  const c = (await chrome.storage.local.get(["profile", "token", "port"])) as Partial<Config>;
  if (!c.token) return null;
  return { profile: c.profile || "main", token: c.token, port: Number(c.port) || 8766 };
}

async function start(): Promise<void> {
  bridge?.stop();
  bridge = null;
  const cfg = await loadConfig();
  if (!cfg) {
    state = { state: "idle", detail: "Not paired yet: open the Companion options and paste the token." };
    return;
  }
  bridge = new CompanionBridge({
    url: `ws://127.0.0.1:${cfg.port}`,
    profile: cfg.profile,
    token: cfg.token,
    recipes: RECIPES,
    driver: new ChromeTabDriver(),
    makeSocket: (url) => new WebSocket(url) as unknown as SocketLike,
    onState: (s, detail) => {
      state = { state: s, detail };
      void chrome.action.setBadgeText({ text: s === "connected" ? "" : s === "bad-token" ? "!" : "…" });
    },
    onReload: () => chrome.runtime.reload(),
  });
  bridge.start();
}

// tell the core what the active tab shows (only for allowlisted sites), which also keeps the
// service worker's socket busy so Chrome doesn't suspend it
async function reportActiveTab(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const url = tab?.url && hostAllowed(tab.url) ? tab.url : null;
  bridge?.sendStatus(url, url ? (tab?.title ?? null) : null);
}

chrome.runtime.onInstalled.addListener(() => void chrome.alarms.create("clipper-keepalive", { periodInMinutes: 0.5 }));
chrome.runtime.onStartup.addListener(() => void start());
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name !== "clipper-keepalive") return;
  if (!bridge || state.state === "idle") void start();
  else void reportActiveTab();
});
chrome.tabs.onActivated.addListener(() => void reportActiveTab());
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes["token"] || changes["profile"] || changes["port"])) void start();
});
chrome.runtime.onMessage.addListener((msg: { type?: string }, _sender, respond) => {
  if (msg.type === "clipper.status") {
    respond(state);
    return false;
  }
  return false;
});

void start();
