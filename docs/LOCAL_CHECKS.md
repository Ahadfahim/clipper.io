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

## yt-dlp needs Deno (2026-10-03)
yt-dlp 2026.x needs a JavaScript runtime for YouTube extraction (Deno by default). Installed with `winget install DenoLand.Deno` (2.9.7); it goes on the user PATH, so start Clipper from a new terminal after installing. `clipper doctor` warns when `deno` isn't found.


## Companion extension: Chrome keeps a stale service worker (2026-10-03)
Chrome kept running an old build of the Companion's service worker across rebuilds **and** browser restarts (it serves it from `<profile>\Default\Service Worker\ScriptCache`). Restarting Chrome didn't refresh it, and neither did a manifest version change. The content script did update, because it's injected from disk each time, which made this confusing.
- Normal flow: `just build` in `apps/extension`, then `POST /api/browser/profiles/main/extension/reload`. The extension calls `chrome.runtime.reload()`, which re-registers the worker from disk. Each build has its own version (`0.1.<day>.<slot>`, from `build.mjs`), and the core log prints it on connect (`Companion main connected (extension 0.1.275.35140)`): check it after every reload.
- If the log still shows the old build (only possible with a build older than the reload handler): close the Clipper Chrome, rename `C:\ClipperData\chrome\main\Default\Service Worker` aside, and let Clipper relaunch Chrome. Logins (cookies) are untouched. Or click ↻ on Clipper Companion in `chrome://extensions`.
- Clipper's Chrome ignores a plain close request (`taskkill` without `/F`) while its windows are hidden. Show it first.
- Two Companions connected as the same profile replace each other on every retry (core log: `disconnected (code 4409 ...)` every 2 s), and each replacement drops the running request. The worker now starts one bridge only, and a replaced bridge stops retrying.

## Marketplace sites (2026-10-03)
How the live sites are built, which the recipes depend on. Probe with `POST /api/browser/profiles/main/probe` (read-only steps; `outline` shows a subtree's structure) and dry-run with `POST /api/publishing/recipes/<name>/test` (body `{"params": {...}}`).
- **Vyro** is at `app.vyro.com` (`vyro.com/dashboard` is a 404). Campaign cards (`[data-slot=card]`) aren't links: clicking one opens a Radix dialog and sets `?c=<slug>`. The slug is the campaign's stable id. It comes from the campaign's first title and survives renames (e.g. "Eat Everything In A Grocery Store" has the slug `i-built-a-city-…`). `app.vyro.com/campaigns?c=<slug>` opens the dialog directly. The dialog shows end date (`aria-label` "October 17, 2026, 09:10:00", local time), CPM, "% paid out" (there's no dollar budget), allowed platforms (under "Post settings") and the source links. Click handlers attach after the cards render, so `open_each` retries the click.
- **Whop Content Rewards** is an app inside a community (here Clipping Culture: `whop.com/clippingculture/exp_zeADOv9rOOKk2x/app/`). It runs in a cross-origin iframe from `b4e0vdqv6zgqeqj4pfgm.apps.whop.com`, so the recipes open it full-page through Whop's launch URL (`whop.com/core/app/launch/?redirect=<app url>`). `/discover` lists campaigns as cards ("Preview <title>" buttons) showing used/total budget and CPM. A card opens `/campaigns/<uuid>`. The campaign page has per-platform rates, min/max payout, budget remaining and a "Submit clip" button (there's no join step). The real rules are a linked Google Doc, which the core reads (`marketplaces/docs.py`; a private doc is noted as unreadable). The launch URL is Clipping Culture's install, hardcoded in `whop.*.json`. Other communities will need it as a setting.
- The Whop app page loads an invisible Cloudflare Turnstile frame. CAPTCHA detection now counts only visible, widget-sized frames (and ignores reCAPTCHA's badge); before that change it paused on every Whop page.
