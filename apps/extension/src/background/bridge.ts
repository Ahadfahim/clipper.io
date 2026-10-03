// WebSocket link to clipper-core (127.0.0.1 only, pairing token). One request runs at a time per
// profile; results go back with screenshot + simplified DOM on failure. Reconnects with backoff.
import { EXTENSION_VERSION } from "../version";
import { PROTOCOL_VERSION, type Incoming, type ResultMsg, type Step } from "../shared/protocol";
import type { Recipe } from "../shared/recipe";
import { runOne, runRecipe, type RunResult, type TabDriver } from "./runner";

export type SocketLike = {
  readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
};

export type BridgeState = "idle" | "connecting" | "connected" | "bad-token" | "replaced" | "protocol";

export type BridgeOptions = {
  url: string; // ws://127.0.0.1:8766
  profile: string;
  token: string;
  recipes: Record<string, Recipe>;
  driver: TabDriver;
  makeSocket: (url: string) => SocketLike;
  onState?: (s: BridgeState, detail?: string) => void;
  schedule?: (fn: () => void, ms: number) => unknown;
};

const OPEN = 1;

export class CompanionBridge {
  private socket: SocketLike | null = null;
  private chain: Promise<void> = Promise.resolve();
  private attempt = 0;
  private stopped = false;
  state: BridgeState = "idle";

  constructor(private readonly o: BridgeOptions) {
    if (!/^wss?:\/\/(127\.0\.0\.1|localhost)(:\d+)?(\/|$)/.test(o.url)) throw new Error("the Companion only connects to the local core");
  }

  private set(s: BridgeState, detail?: string) {
    this.state = s;
    this.o.onState?.(s, detail);
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.socket?.close(1000, "stopped");
  }

  private connect(): void {
    if (this.stopped) return;
    this.set("connecting");
    const ws = this.o.makeSocket(this.o.url);
    this.socket = ws;
    ws.onopen = () => {
      this.attempt = 0;
      ws.send(JSON.stringify({ type: "hello", profile: this.o.profile, token: this.o.token, version: EXTENSION_VERSION, protocol: PROTOCOL_VERSION, url: null }));
    };
    ws.onmessage = (ev) => {
      let msg: Incoming;
      try {
        msg = JSON.parse(String(ev.data)) as Incoming;
      } catch {
        return;
      }
      this.onMessage(msg);
    };
    ws.onclose = (ev) => {
      if (this.socket !== ws) return;
      this.socket = null;
      if (ev.code === 4401) return this.set("bad-token", "The pairing token was refused. Paste the token from Clipper → Settings → Accounts and browser.");
      if (ev.code === 4426) return this.set("protocol", ev.reason);
      if (ev.code === 4409) this.set("replaced", "Another window of this profile connected.");
      else this.set("idle");
      this.retry();
    };
    ws.onerror = () => undefined;
  }

  private retry(): void {
    if (this.stopped) return;
    this.attempt += 1;
    const delay = Math.min(30_000, 1000 * 2 ** Math.min(this.attempt, 5));
    (this.o.schedule ?? setTimeout)(() => this.connect(), delay);
  }

  private reply(msg: ResultMsg): void {
    if (this.socket && this.socket.readyState === OPEN) this.socket.send(JSON.stringify(msg));
  }

  sendStatus(url: string | null, title: string | null): void {
    if (this.socket && this.socket.readyState === OPEN) this.socket.send(JSON.stringify({ type: "status", url, title }));
  }

  private onMessage(msg: Incoming): void {
    switch (msg.type) {
      case "welcome":
        this.set("connected");
        return;
      case "ping":
        this.socket?.send(JSON.stringify({ type: "pong" }));
        return;
      case "run":
      case "action":
        // one action at a time per profile: queue behind whatever is running
        this.chain = this.chain.then(() => this.execute(msg)).catch(() => undefined);
        return;
    }
  }

  private async execute(msg: Extract<Incoming, { type: "run" | "action" }>): Promise<void> {
    let res: RunResult;
    try {
      if (msg.type === "run") {
        const recipe = this.o.recipes[msg.recipe];
        res = recipe ? await runRecipe(this.o.driver, recipe, msg.params ?? {}, Boolean(msg.dry_run)) : { ok: false, data: {}, error: `unknown recipe ${msg.recipe}` };
      } else {
        const a = msg.action as Step & { kind?: Step["action"] };
        const step: Step = { ...a, action: a.action ?? a.kind ?? "snapshot" };
        if (step.action === "snapshot") {
          const shot = await this.o.driver.screenshot();
          const dom = await this.o.driver.dom();
          res = { ok: true, data: { url: await this.o.driver.currentUrl() }, screenshot: shot, dom };
        } else {
          const one = await runOne(this.o.driver, step, 0, false);
          res = { ...one, data: { ...one.data, ...(one.saved !== undefined ? { value: one.saved } : {}), url: await this.o.driver.currentUrl() } };
        }
      }
    } catch (e) {
      res = { ok: false, data: {}, error: e instanceof Error ? e.message : String(e) };
    }
    this.reply({
      type: "result",
      id: msg.id,
      ok: res.ok,
      data: res.data,
      error: res.error ?? null,
      step: res.step ?? null,
      screenshot: res.screenshot ?? null,
      dom: res.dom ?? null,
      challenge: res.challenge ?? null,
    });
  }
}
