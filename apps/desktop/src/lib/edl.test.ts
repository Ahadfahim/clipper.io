import { describe, expect, it } from "vitest";
import { asEdl, cameraAt, cameraSpans, captionAt, captionSpans, outputDuration, outputSegments, outToSrc, srcRangeToOut, srcToOut } from "./edl";

const edl = asEdl({
  segments: [
    { start: 0, end: 2, kind: "main" },
    { start: 3, end: 6, kind: "main" },
  ],
  camera: [
    { t: 0, layout: "crop", focus_x: 0.5, focus_y: 0.5, zoom: 1, focus2_x: null },
    { t: 4, layout: "split", focus_x: 0.3, focus_y: 0.5, zoom: 1, focus2_x: 0.7 },
  ],
  captions: {
    enabled: true,
    style: "bold-pop",
    safe_zone: "tiktok",
    max_words_per_line: 2,
    words: [
      { t: 0.2, end: 0.6, text: "Nobody", emphasis: false, speaker: null },
      { t: 0.7, end: 1.1, text: "tells", emphasis: true, speaker: null },
      { t: 2.2, end: 2.6, text: "um", emphasis: false, speaker: null }, // cut
      { t: 3.2, end: 3.6, text: "you", emphasis: false, speaker: null },
      { t: 3.7, end: 3.9, text: "", emphasis: false, speaker: null }, // hidden
    ],
  },
  overlays: [],
});

describe("edl timeline math", () => {
  it("maps kept source time to output time", () => {
    expect(outputSegments(edl).map((s) => [s.outStart, s.outEnd])).toEqual([
      [0, 2],
      [2, 5],
    ]);
    expect(outputDuration(edl)).toBe(5);
    expect(srcToOut(edl, 3.5)).toBe(2.5);
    expect(srcToOut(edl, 2.5)).toBeNull(); // in the cut
    expect(outToSrc(edl, 2.5)).toBe(3.5);
  });
  it("clips an agent range to what survives", () => {
    expect(srcRangeToOut(edl, 1, 4)).toEqual([1, 3]);
    expect(srcRangeToOut(edl, 2.1, 2.9)).toBeNull();
  });
  it("camera spans and the key at a time", () => {
    expect(cameraSpans(edl).map((s) => [s.from, s.to, s.data.layout])).toEqual([
      [0, 3, "crop"],
      [3, 5, "split"],
    ]);
    expect(cameraAt(edl, 4)?.layout).toBe("split");
  });
  it("captions skip cut and hidden words and group by line", () => {
    expect(captionSpans(edl).map((s) => [s.data.text, s.data.index])).toEqual([
      ["Nobody", 0],
      ["tells", 1],
      ["you", 3],
    ]);
    const at = captionAt(edl, 0.8);
    expect(at?.words.map((w) => w.text)).toEqual(["Nobody", "tells"]);
    expect(at?.active).toBe(1);
    expect(captionAt(edl, 1.5)).toBeNull();
  });
});
