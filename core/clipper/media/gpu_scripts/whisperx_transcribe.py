"""Run WhisperX inside the isolated CUDA env (C:\\ClipperData\\envs\\gpu). LOCAL-VERIFY.

Called by ``clipper.media.transcribe.WhisperXTranscriber`` as a subprocess, so torch/CUDA never load in
the core process. Standalone on purpose: no clipper imports.

    python whisperx_transcribe.py AUDIO.wav OUT.json --model large-v3 --models-dir C:\\ClipperData\\models
        [--language en] [--diarize]  (HF token for diarization comes from the HF_TOKEN env var)

Windows notes (docs/LOCAL_CHECKS.md): models are downloaded into --models-dir (no symlinks needed), and
pyannote gets an in-memory waveform (DiarizationPipeline does this when given an array), never a path,
because torchcodec 0.7 does not support ffmpeg 8.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("out")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--models-dir", required=True)
    p.add_argument("--language", default=None)
    p.add_argument("--diarize", action="store_true")
    p.add_argument("--batch-size", type=int, default=16)
    args = p.parse_args()

    os.environ.setdefault("HF_HOME", os.path.join(args.models_dir, "hf"))
    os.environ.setdefault("TORCH_HOME", os.path.join(args.models_dir, "torch"))
    import torch
    import whisperx

    if not torch.cuda.is_available():
        print("CUDA is not available in this env (need torch cu128 for the RTX 5080)", file=sys.stderr)
        return 3
    device = "cuda"
    t0 = time.time()
    audio = whisperx.load_audio(args.audio)
    model = whisperx.load_model(
        args.model,
        device,
        compute_type="float16",
        language=args.language,
        download_root=os.path.join(args.models_dir, "whisper"),
    )
    result = model.transcribe(audio, batch_size=args.batch_size, language=args.language)
    language = result.get("language") or args.language or "en"
    align_model, metadata = whisperx.load_align_model(
        language_code=language, device=device, model_dir=os.path.join(args.models_dir, "align")
    )
    aligned = whisperx.align(
        result["segments"], align_model, metadata, audio, device, return_char_alignments=False
    )
    if args.diarize and os.environ.get("HF_TOKEN"):
        from whisperx.diarize import DiarizationPipeline

        diarizer = DiarizationPipeline(
            token=os.environ["HF_TOKEN"], device=device, cache_dir=os.path.join(args.models_dir, "pyannote")
        )
        diarized = diarizer(audio)  # ndarray -> in-memory waveform
        aligned = whisperx.assign_word_speakers(diarized, aligned)
    words = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            if "start" in w and "end" in w:
                words.append(
                    {
                        "text": w["word"],
                        "start": round(float(w["start"]), 3),
                        "end": round(float(w["end"]), 3),
                        "speaker": w.get("speaker"),
                    }
                )
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"language": language, "words": words, "seconds": round(time.time() - t0, 2)}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
