"""Regenerate the synthetic test media (`just fixtures`). Needs ffmpeg with drawtext.

talk_16x9.mp4         10 s 960x540 testsrc2, burned-in "SAMPLE WATERMARK", 220 Hz tone bursts
                      (1.4 s on, 0.6 s off) standing in for speech with pauses.
talk_16x9.words.json  fake word timings aligned to the bursts (what the FakeTranscriber returns).
qa_bad.mp4            4 s: 1 s picture, 1.5 s black, 1.5 s frozen frame; clipped square-wave audio.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent / "media"

SENTENCES = [
    "Nobody tells you this",
    "um the money is",
    "in the edit",
    "really really fast",
    "watch what happens",
]


def run(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def talk() -> None:
    audio = "aevalsrc='0.35*sin(2*PI*220*t)*lt(mod(t\\,2)\\,1.4)':s=48000:d=10"
    text = "drawtext=text='SAMPLE WATERMARK':x=24:y=h-60:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.6"
    video_codec = ["-c:v", "libx264", "-preset", "veryslow", "-crf", "34", "-pix_fmt", "yuv420p", "-g", "60"]
    audio_codec = ["-c:a", "aac", "-b:a", "64k", "-ac", "2"]
    inputs = ["-f", "lavfi", "-i", "testsrc2=s=960x540:r=30:d=10", "-f", "lavfi", "-i", audio]
    run([*inputs, "-vf", text, *video_codec, *audio_codec, "-shortest", str(HERE / "talk_16x9.mp4")])
    words: list[dict[str, object]] = []
    for i, sentence in enumerate(SENTENCES):
        start = i * 2.0 + 0.2
        tokens = sentence.split()
        step = 1.1 / len(tokens)
        for j, tok in enumerate(tokens):
            words.append(
                {
                    "text": tok,
                    "start": round(start + j * step, 3),
                    "end": round(start + (j + 0.85) * step, 3),
                    "speaker": "S1",
                }
            )
    (HERE / "talk_16x9.words.json").write_text(
        json.dumps({"language": "en", "words": words}, indent=1) + "\n"
    )


def qa_bad() -> None:
    inputs = [
        *("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1"),
        *("-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=1.5"),
        *("-f", "lavfi", "-i", "color=c=0x4060a0:s=320x180:r=30:d=1.5"),
        *("-f", "lavfi", "-i", "aevalsrc='1.0*sgn(sin(2*PI*440*t))':s=48000:d=4"),
    ]
    graph = "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]"
    codecs = ["-c:v", "libx264", "-crf", "35", "-c:a", "aac", "-b:a", "48k"]
    run(
        [
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "3:a",
            *codecs,
            "-shortest",
            str(HERE / "qa_bad.mp4"),
        ]
    )


if __name__ == "__main__":
    HERE.mkdir(parents=True, exist_ok=True)
    talk()
    qa_bad()
    for f in sorted(HERE.iterdir()):
        print(f"{f.name:28s} {f.stat().st_size / 1024:8.1f} KB")
