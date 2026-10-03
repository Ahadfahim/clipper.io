# Local checks on the target machine (2026-10-03)

Run on the user's PC (see ENVIRONMENT.md). These results are **verified**; build against them.

## NVENC (ffmpeg 8.1 at `C:\ffmpeg\bin`)
| Check | Result |
|---|---|
| Encoders available | `h264_nvenc`, `hevc_nvenc`, `av1_nvenc`, `libx264` |
| Filters available | `ass`, `subtitles` (libass), `loudnorm` |
| 20s 1080×1920 30fps, `h264_nvenc -preset p5 -b:v 14M` | 2.1s, OK |
| **4 concurrent** NVENC encodes (30s each) | 4.9s total, all OK, no session limit hit |

The plan's limit of 3 concurrent encodes (PLAN §17.3) is safe; 4 also works.

## CUDA PyTorch + WhisperX
Isolated test environment: `C:\ClipperData\envs\gpucheck` (uv, Python 3.12.14).

**Known-good versions (pin these):**
- `torch==2.8.0+cu128`, `torchaudio==2.8.0+cu128`, `torchvision==0.23.0+cu128` from `https://download.pytorch.org/whl/cu128`
- `whisperx==3.8.6`, `faster-whisper==1.2.1`, `ctranslate2==4.8.2`, `pyannote-audio==4.0.7`

Install command that worked:
```
uv pip install whisperx torch torchaudio --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
```

**Results:**
| Check | Result |
|---|---|
| Device | NVIDIA GeForce RTX 5080, compute capability (12, 0), cuDNN 9.10 |
| fp16 matmul | ~78 TFLOPS |
| large-v3 load (float16) | 12.1s (first load) |
| Transcribe 13.8s of speech | **1.39s**, word-perfect |
| Word alignment (wav2vec2, incl. first download) | 6.5s; word timestamps OK (`Nobody@0.175, tells@0.596, …`) |
| Torch VRAM peak | 0.7 GB (CTranslate2 memory is extra; large-v3 fp16 ≈ 3–4 GB total) |

## Windows gotchas found (the build must handle these)
1. **No symlink privilege**: Hugging Face's cache fails with `WinError 1314`. Always download models with `snapshot_download(repo, local_dir=...)` into `C:\ClipperData\models\<name>` and load from that folder (or the user enables Windows Developer Mode). Set `HF_HOME` and `TORCH_HOME` under `C:\ClipperData\models`.
2. **torchcodec 0.7 doesn't support ffmpeg 8** (it supports 4–7). pyannote uses it to decode files, so **pass audio to pyannote as an in-memory waveform** (`{"waveform": tensor, "sample_rate": 16000}`) decoded by our own ffmpeg call, never a file path.
3. **pyannote diarization models are gated**: the user needs a Hugging Face account, must accept the model terms, and must provide a read token (stored in Windows Credential Manager). This is a setup-wizard step.
4. `uv python install` couldn't create its version-link junction from the agent sandbox; using the interpreter's full path worked. Probably sandbox-only, but `clipper doctor` should check for it.
5. Models and environments live on **C:** (`C:\ClipperData`), because D: has only ~79 GB free.
