import { beforeEach, describe, expect, it, vi } from "vitest";
import { attachFile, click, detectChallenge, findElement, runStep, simplifiedDom, typeInto } from "../src/content/engine";

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("engine actions", () => {
  it("finds by selector, by visible text, and skips hidden elements", () => {
    document.body.innerHTML = `
      <button id="a" style="display:none">Upload videos</button>
      <div role="menuitem" id="b">Upload videos</div>
      <button id="c" aria-label="Create">+</button>
      <button id="d">Upload videos later</button>`;
    expect(findElement(document, { text: "upload videos" })?.id).toBe("b");
    expect(findElement(document, { text: "Create" })?.id).toBe("c");
    expect(findElement(document, { selector: "#d", text: "upload" })?.id).toBe("d");
    expect(findElement(document, { selector: "##bad" })).toBeNull();
  });

  it("clicks, types into inputs and contenteditable, attaches a file", async () => {
    document.body.innerHTML = `<button id="b">Go</button><input id="t" value="old"><div id="e" contenteditable="true">x</div><input id="f" type="file">`;
    const onClick = vi.fn();
    document.getElementById("b")!.addEventListener("click", onClick);
    click(document.getElementById("b")!);
    expect(onClick).toHaveBeenCalledOnce();
    const input = document.getElementById("t") as HTMLInputElement;
    const onInput = vi.fn();
    input.addEventListener("input", onInput);
    typeInto(input, "New title");
    expect(input.value).toBe("New title");
    expect(onInput).toHaveBeenCalled();
    typeInto(input, " more", false);
    expect(input.value).toBe("New title more");
    typeInto(document.getElementById("e")!, "caption #tag");
    expect(document.getElementById("e")!.textContent).toBe("caption #tag");
    const file = new File([new Uint8Array([1, 2, 3])], "clip.mp4", { type: "video/mp4" });
    const fileInput = document.getElementById("f") as HTMLInputElement;
    const onChange = vi.fn();
    fileInput.addEventListener("change", onChange);
    attachFile(fileInput, file);
    expect(fileInput.files?.[0]?.name).toBe("clip.mp4");
    expect(onChange).toHaveBeenCalled();
  });

  it("runs steps: wait_for, read_text with attr + regex, structured query, exists", async () => {
    document.body.innerHTML = `
      <a class="ytcp-video-info" href="https://youtube.com/shorts/Abc123def45">link</a>
      <div class="card" data-id="c1"><a href="/campaigns/42"><h3>MrBeast #42</h3></a><span class="cpm">$3.00 CPM</span></div>
      <div class="card" data-id="c2"><a href="/campaigns/43"><h3>Ali Abdaal</h3></a><span class="cpm">$2.50 CPM</span></div>`;
    expect(await runStep(document, { action: "wait_for", selector: ".card", timeout_ms: 50 })).toEqual({ ok: true });
    expect((await runStep(document, { action: "read_text", selector: "a.ytcp-video-info", attr: "href" })).data?.["value"]).toBe("https://youtube.com/shorts/Abc123def45");
    const q = await runStep(document, {
      action: "query",
      selector: ".card",
      all: true,
      fields: { id: { selector: "a", attr: "href", regex: "/campaigns/(\\d+)" }, title: { selector: "h3" }, cpm: { selector: ".cpm", regex: "\\$([\\d.]+)" } },
    });
    expect(q.data?.["value"]).toEqual([
      { id: "42", title: "MrBeast #42", cpm: "3.00" },
      { id: "43", title: "Ali Abdaal", cpm: "2.50" },
    ]);
    expect((await runStep(document, { action: "query", selector: ".nope", exists: true })).data?.["value"]).toBe(false);
    const miss = await runStep(document, { action: "click", selector: "#missing", timeout_ms: 30 });
    expect(miss.ok).toBe(false);
  });
});

describe("challenge detection (never solved)", () => {
  it.each([
    [`<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>`, "captcha"],
    [`<div id="captcha_container">Drag the slider</div>`, "captcha"],
    [`<h1>Verify it's you</h1><p>To continue, confirm</p>`, "verification"],
    [`<form><input type="password"><button>Log in</button></form>`, "login"],
    [`<main><h1>Upload videos</h1></main>`, null],
  ])("%s → %s", (html, want) => {
    document.body.innerHTML = html;
    expect(detectChallenge(document, "https://studio.youtube.com/")).toBe(want);
  });

  it("reads the page's text, not inline script payloads", () => {
    // Instagram inlines megabytes of JSON before the login form; it also mentions two_factor/"two-factor"
    const state = `<script type="application/json">${JSON.stringify({ blob: "x".repeat(30_000), flow: "two-factor" })}</script>`;
    document.body.innerHTML = `${state}<form><input type="password" name="pass"><div role="button">Log in</div></form>`;
    expect(detectChallenge(document, "https://www.instagram.com/")).toBe("login");
    document.body.innerHTML = `${state}<main><h1>Home</h1></main><template><p>Verify it's you</p></template>`;
    expect(detectChallenge(document, "https://www.instagram.com/")).toBeNull();
  });

  it("uses the URL too, and a step refuses to run on a challenge page", async () => {
    document.body.innerHTML = `<main>Hi</main>`;
    expect(detectChallenge(document, "https://www.instagram.com/challenge/abc/")).toBe("verification");
    expect(detectChallenge(document, "https://www.tiktok.com/login?redirect=x")).toBe("login");
    document.body.innerHTML = `<iframe src="https://hcaptcha.com/x"></iframe><button id="b">Post</button>`;
    const out = await runStep(document, { action: "click", selector: "#b" });
    expect(out).toMatchObject({ ok: false, challenge: "captcha" });
  });
});

describe("simplified DOM", () => {
  it("lists interactive elements with ids, labels and text", () => {
    document.body.innerHTML = `<div><button id="create-icon" aria-label="Create">+</button><input type="file" name="Filedata"><p>prose is dropped</p><a href="/x">Link</a></div>`;
    const dom = simplifiedDom(document);
    expect(dom).toContain(`button#create-icon[aria-label=Create] "+"`);
    expect(dom).toContain("input[type=file][name=Filedata]");
    expect(dom).toContain(`a[href=/x] "link"`);
    expect(dom).not.toContain("prose");
  });
});
