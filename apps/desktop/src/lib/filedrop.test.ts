import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanPath, fileName, handleDrag, isVideoPath, pickVideo, registerDropZone, zoneAt, type DropZone } from "./filedrop";

function zone(left: number, top: number, right: number, bottom: number): DropZone & { hover: ReturnType<typeof vi.fn>; drop: ReturnType<typeof vi.fn> } {
  const hover = vi.fn();
  const drop = vi.fn();
  const el = { getBoundingClientRect: () => ({ left, top, right, bottom }) } as unknown as HTMLElement;
  return { el: () => el, onHover: hover, onDrop: drop, hover, drop };
}

describe("file paths", () => {
  it("names a file from a Windows or a plain path", () => {
    expect(fileName("C:\\Users\\you\\Downloads\\episode 212.mp4")).toBe("episode 212.mp4");
    expect(fileName("D:/Clipper.io/data/a.mov")).toBe("a.mov");
  });
  it("knows a video by its extension, whatever the case", () => {
    expect(["a.mp4", "B.MOV", "c.mkv", "d.webm", "e.m4v", "f.avi"].every(isVideoPath)).toBe(true);
    expect(["notes.txt", "clip", "folder.mp4/readme", "a.mp4.part"].some(isVideoPath)).toBe(false);
  });
  it("drops the quotes Explorer puts around a copied path", () => {
    expect(cleanPath('  "C:\\v\\a.mp4" ')).toBe("C:\\v\\a.mp4");
    expect(cleanPath("C:\\v\\a.mp4")).toBe("C:\\v\\a.mp4");
  });
});

describe("pickVideo", () => {
  it("takes the first video and says how many other files came with it", () => {
    expect(pickVideo(["C:\\v\\notes.txt", "C:\\v\\a.mov", "C:\\v\\b.mp4"])).toEqual({ path: "C:\\v\\a.mov", extra: 2 });
    expect(pickVideo(["C:\\v\\a.mp4"])).toEqual({ path: "C:\\v\\a.mp4", extra: 0 });
  });
  it("explains why a drop can't be used", () => {
    expect(pickVideo(["C:\\v\\notes.txt"])).toEqual({ error: "notes.txt isn't a video. Drop an mp4, mov, mkv, webm, m4v or avi file." });
    expect(pickVideo([])).toEqual({ error: "Nothing was dropped." });
  });
});

describe("drop zones", () => {
  const stops: (() => void)[] = [];
  const add = (z: DropZone) => {
    const stop = registerDropZone(z);
    stops.push(stop);
    return z;
  };
  afterEach(() => {
    stops.splice(0).forEach((s) => s());
    handleDrag({ type: "leave" });
  });

  it("finds the zone under the pointer, converting the pixels Tauri reports", () => {
    const a = add(zone(0, 0, 100, 100));
    const b = add(zone(200, 0, 300, 100));
    expect(zoneAt(50, 50, 1)).toBe(a);
    expect(zoneAt(250, 50, 1)).toBe(b);
    expect(zoneAt(250, 50, 2)).toBeUndefined(); // at 200% scale that point is (125, 25) on screen: between the zones
    expect(zoneAt(100, 100, 2)).toBe(a);
    expect(zoneAt(500, 100, 2)).toBe(b);
    expect(zoneAt(150, 50, 1)).toBeUndefined();
  });

  it("highlights the zone you hover and hands the files to the one you release on", () => {
    const a = add(zone(0, 0, 100, 100)) as ReturnType<typeof zone>;
    const b = add(zone(200, 0, 300, 100)) as ReturnType<typeof zone>;
    handleDrag({ type: "enter", position: { x: 20, y: 20 } });
    expect(a.hover).toHaveBeenLastCalledWith(true);
    handleDrag({ type: "over", position: { x: 250, y: 20 } });
    expect(a.hover).toHaveBeenLastCalledWith(false);
    expect(b.hover).toHaveBeenLastCalledWith(true);
    handleDrag({ type: "drop", position: { x: 250, y: 20 }, paths: ["C:\\v\\a.mp4"] });
    expect(b.drop).toHaveBeenCalledWith(["C:\\v\\a.mp4"]);
    expect(a.drop).not.toHaveBeenCalled();
    expect(b.hover).toHaveBeenLastCalledWith(false);
  });

  it("ignores a drop on empty space and a leave clears the highlight", () => {
    const a = add(zone(0, 0, 100, 100)) as ReturnType<typeof zone>;
    handleDrag({ type: "over", position: { x: 10, y: 10 } });
    handleDrag({ type: "leave" });
    expect(a.hover).toHaveBeenLastCalledWith(false);
    handleDrag({ type: "drop", position: { x: 900, y: 900 }, paths: ["C:\\v\\a.mp4"] });
    expect(a.drop).not.toHaveBeenCalled();
  });

  it("lets tests drop on the newest zone", () => {
    const a = add(zone(0, 0, 10, 10)) as ReturnType<typeof zone>;
    const b = add(zone(0, 0, 10, 10)) as ReturnType<typeof zone>;
    expect(window.__clipperTestDrop?.(["C:\\v\\a.mp4"])).toBe(true);
    expect(b.drop).toHaveBeenCalled();
    expect(a.drop).not.toHaveBeenCalled();
  });
});
