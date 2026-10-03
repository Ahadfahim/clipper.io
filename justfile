# Clipper.io task runner. Install just with `uv tool install rust-just` (or `winget install Casey.Just`).
# Recipes work on Windows (PowerShell) and Linux/macOS (sh).

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := false

gpu_env := if os() == "windows" { 'C:\ClipperData\envs\gpu' } else { env_var_or_default("HOME", "/tmp") + "/.clipper/envs/gpu" }

default:
    @just --list

# Install Python (uv) and JS (pnpm) dependencies.
setup:
    uv sync --all-packages
    pnpm install --frozen-lockfile

# Ruff, pyright, eslint and tsc.
lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright
    pnpm -r run lint
    pnpm -r run typecheck

# Auto-fix formatting and lint issues.
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Python tests + JS unit tests.
test:
    uv run pytest -q
    pnpm -r run test

# Playwright screenshot tests of every screen (dark/light x 1280x800/1920x1080) into docs/screenshots.
screenshots:
    pnpm --filter @clipper/desktop run build
    pnpm --filter @clipper/desktop exec playwright test --project=screenshots

# Everything CI runs.
ci: lint test build screenshots

# Build the desktop web layer and the Companion extension.
build:
    pnpm --filter @clipper/desktop run build
    pnpm --filter @clipper/extension run build

# Create/upgrade the database.
migrate:
    uv run clipper migrate

# Seed switches/platforms; `just seed fixtures` also adds demo data.
seed mode="":
    uv run clipper seed {{ if mode == "fixtures" { "--fixtures" } else { "" } }}

# FastAPI + supervisor on 127.0.0.1:8765.
dev-api:
    uv run clipper api

# FastAPI with seeded fixture data and no agents (for UI work).
dev-api-fixtures:
    uv run clipper api --fixtures

# Vite dev server for the dashboard (talks to dev-api on 127.0.0.1:8765).
dev-ui:
    pnpm --filter @clipper/desktop run dev

# Vite dev server against in-browser fixtures (no API needed).
dev-ui-fixtures:
    pnpm --filter @clipper/desktop run dev:fixtures

# Tauri desktop app (Windows; needs Rust + WebView2).
dev-app:
    pnpm --filter @clipper/desktop exec tauri dev

# Discord bot (token comes from Windows Credential Manager).
dev-bot:
    uv run clipper-bot

# Environment and health checks.
doctor:
    uv run clipper doctor

# Regenerate the typed TS API client from the FastAPI schema.
gen-api:
    uv run clipper openapi core/clipper/api/openapi.json
    pnpm --filter @clipper/desktop run gen:api

# Create the isolated CUDA env for WhisperX (versions verified on the RTX 5080, docs/LOCAL_CHECKS.md).
[windows]
gpu-setup:
    uv venv '{{gpu_env}}' --python 3.12
    uv pip install --python '{{gpu_env}}\Scripts\python.exe' "torch==2.8.0+cu128" "torchaudio==2.8.0+cu128" "torchvision==0.23.0+cu128" "whisperx==3.8.6" "faster-whisper==1.2.1" "ctranslate2==4.8.2" "pyannote-audio==4.0.7" --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
    & '{{gpu_env}}\Scripts\python.exe' -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Regenerate the synthetic test media in tests/fixtures (needs ffmpeg).
fixtures:
    uv run python tests/fixtures/make_fixtures.py
