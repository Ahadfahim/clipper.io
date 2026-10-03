import { describe, expect, it } from "vitest";
import { CompanionBridge, type SocketLike } from "../src/background/bridge";
import type { TabDriver } from "../src/background/runner";
import { RECIPES } from "../src/background/recipes";
import { PROTOCOL_VERSION } from "../src/shared/protocol";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: { code: number; reason: string }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  constructor(public url: string) {}
  send(data: string) {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(code = 1000, reason = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason });
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

function driver(log: string[]): TabDriver {
  return {
    navigate: async (u) => void log.push(`nav ${u}`),
    currentUrl: async () => "https://vyro.com/campaigns",
    step: async (s) => {
      log.push(`start ${s.action}`);
      await new Promise((r) => setTimeout(r, 5));
      log.push(`end ${s.action}`);
      return s.action === "query" ? { ok: true, data: { value: [{ id: "42", title: "MrBeast" }] } } : { ok: true };
    },
    check: async () => ({ ok: true, challenge: null }),
    dom: async () => "<main/>",
    screenshot: async () => "data:image/png;base64,AA",
    sendFile: async () => undefined,
    fetchFile: async () => ({ bytes: new Uint8Array(1), mime: "video/mp4" }),
    sleep: async () => undefined,
  };
}

const settle = () => new Promise((r) => setTimeout(r, 60));

describe("CompanionBridge", () => {
  it("pairs with hello + token, runs recipes one at a time, answers pings", async () => {
    const sockets: FakeSocket[] = [];
    const log: string[] = [];
    const states: string[] = [];
    const b = new CompanionBridge({
      url: "ws://127.0.0.1:8766",
      profile: "main",
      token: "secret-token",
      recipes: RECIPES,
      driver: driver(log),
      makeSocket: (u) => {
        const s = new FakeSocket(u);
        sockets.push(s);
        return s;
      },
      onState: (s) => states.push(s),
    });
    b.start();
    const ws = sockets[0]!;
    ws.open();
    expect(ws.sent[0]).toMatchObject({ type: "hello", profile: "main", token: "secret-token", protocol: PROTOCOL_VERSION });
    ws.receive({ type: "welcome", profile: "main", protocol: PROTOCOL_VERSION });
    expect(b.state).toBe("connected");
    ws.receive({ type: "ping" });
    expect(ws.sent.at(-1)).toEqual({ type: "pong" });

    ws.receive({ type: "run", id: "r1", recipe: "vyro.list_campaigns", params: {}, dry_run: false });
    ws.receive({ type: "action", id: "a1", action: { kind: "click", selector: "#x" } });
    await settle();
    // the second request waited for the first to finish
    expect(log.indexOf("start click")).toBeGreaterThan(log.indexOf("end query"));
    const results = ws.sent.filter((m) => m["type"] === "result");
    expect(results[0]).toMatchObject({ id: "r1", ok: true, data: { campaigns: [{ id: "42", title: "MrBeast" }] } });
    expect(results[1]).toMatchObject({ id: "a1", ok: true });

    ws.receive({ type: "run", id: "r2", recipe: "nope.recipe", params: {}, dry_run: false });
    await settle();
    expect(ws.sent.at(-1)).toMatchObject({ id: "r2", ok: false, error: "unknown recipe nope.recipe" });

    ws.receive({ type: "action", id: "s1", action: { kind: "snapshot" } });
    await settle();
    expect(ws.sent.at(-1)).toMatchObject({ id: "s1", ok: true, screenshot: "data:image/png;base64,AA", dom: "<main/>" });
  });

  it("reconnects with backoff, but stops on a refused token", () => {
    const sockets: FakeSocket[] = [];
    const delays: number[] = [];
    const b = new CompanionBridge({
      url: "ws://127.0.0.1:8766",
      profile: "main",
      token: "t",
      recipes: RECIPES,
      driver: driver([]),
      makeSocket: (u) => {
        const s = new FakeSocket(u);
        sockets.push(s);
        return s;
      },
      schedule: (fn, ms) => {
        delays.push(ms);
        fn();
      },
    });
    b.start();
    sockets[0]!.close(1006, "lost");
    sockets[1]!.close(1006, "lost");
    expect(delays).toEqual([2000, 4000]);
    sockets[2]!.close(4401, "bad pairing token");
    expect(b.state).toBe("bad-token");
    expect(sockets).toHaveLength(3);
  });

  it("only ever connects to the local core", () => {
    expect(() => new CompanionBridge({ url: "wss://evil.example:8766", profile: "m", token: "t", recipes: {}, driver: driver([]), makeSocket: (u) => new FakeSocket(u) })).toThrow(/local core/);
  });
});
