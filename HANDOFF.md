# HANDOFF — cloud → local

## 1. Snapshot
- Branch / PR: `claude/affectionate-davinci-f3xmlm` / PR: none yet
- Last commit: see `git log -1` (WP0 scaffold)
- Work packages:
  - WP0 ✅ Repo scaffold: uv + pnpm workspaces, ruff/pyright(strict core)/pytest, eslint/tsc/vitest/Playwright, settings example, justfile, CI
  - WP1 ❌ Data layer and event bus
  - WP2 ❌ Guardrails
  - WP3 ❌ MCP tool servers
  - WP4 ❌ EDL editing engine
  - WP5 ❌ Supervisor and agent runtime
  - WP6 ❌ API
  - WP7 ❌ Desktop UI
  - WP8 ❌ Discord bot
  - WP9 ❌ Companion extension
- Test status:
  - `uv run pytest -q` → 8 passed
  - `uv run ruff check . && uv run pyright` → clean
  - `pnpm -r run lint && pnpm -r run typecheck && pnpm -r run test` → clean, 2 passed
  - `just screenshots` → 4 passed (placeholder shell)

## 2. How to run (on Windows)
```powershell
cd D:\Clipper.io
uv tool install rust-just          # once
just setup                         # uv sync --all-packages + pnpm install
just doctor                        # environment checks
just lint
just test
```

## 3. What was built
### WP0
- `pyproject.toml`: uv workspace root (members `core`, `apps/bot`), ruff and pyright config (strict on `core/clipper`).
- `core/clipper/settings.py`: typed settings from `config/settings.toml` (example: `config/settings.example.toml`, test-enforced to mention every key).
- `core/clipper/agents/env.py`: billing env scrubbing for agent subprocesses.
- `core/clipper/secrets.py`: Windows Credential Manager via `keyring`.
- `core/clipper/doctor.py` + `clipper doctor`.
- `apps/desktop`: Vite + React 19 + TS strict + Tailwind 4 + vitest + Playwright 1.56.1.
- `apps/extension`: MV3 TS package skeleton with esbuild bundling.
- `justfile`, `.github/workflows/ci.yml`.

## 4. LOCAL-VERIFY list
| file:line | what | how to verify | expected |
|---|---|---|---|
| `justfile` (gpu-setup) | CUDA WhisperX env | `just gpu-setup` | prints `2.8.0+cu128 True NVIDIA GeForce RTX 5080` |

## 5. Known gaps and TODOs
- Everything from WP1 on.

## 6. Decisions and deviations from PLAN.md / UI.md
- Python package lives at `core/clipper/` (import name `clipper`) instead of directly in `core/`, so the import name works with uv/hatch editable installs and pyright on Windows without symlinks.

## 7. Interfaces the local side must implement or finish
- (filled in by later work packages)

## 8. Ordered task list for the local session
1. Run section 2. Done when `just lint` and `just test` pass on Windows.

## 9. Risks and open questions for the user
- (filled in by later work packages)
