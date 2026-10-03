# HANDOFF — cloud → local

## 1. Snapshot
- Branch / PR: `claude/affectionate-davinci-f3xmlm` / PR: none yet
- Last commit: see `git log -1` (WP0 scaffold)
- Work packages:
  - WP0 ✅ Repo scaffold: uv + pnpm workspaces, ruff/pyright(strict core)/pytest, eslint/tsc/vitest/Playwright, settings example, justfile, CI
  - WP1 ✅ Data layer: 30 SQLModel tables (PLAN §9 + additions), Alembic 0001, WAL, single writer queue, typed event bus, leases, atomic cap check
  - WP2 ✅ Guardrails: 15 pure PreToolUse rules + SDK hook adapters, 71 table-driven cases, DB context, blocked calls logged
  - WP3 ❌ MCP tool servers
  - WP4 ✅ EDL engine: schema, 13 pure ops, renderer (eased crop/split/fit/zoom/progress bar/two-pass loudnorm), ASS captions with safe zones + face avoidance, QA checks, EdlService (edit_op log, undo by replay, locks, variants), golden renders
  - WP5 ❌ Supervisor and agent runtime
  - WP6 ❌ API
  - WP7 ❌ Desktop UI
  - WP8 ❌ Discord bot
  - WP9 ❌ Companion extension
- Test status:
  - `uv run pytest -q` → 150 passed (golden renders need ffmpeg on PATH)
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

### WP1
- `core/clipper/db/models.py`: every PLAN §9 table (snake_case names) plus `review_batch`, `kv`, `discord_ref`, `recipe_run`.
- `core/clipper/db/engine.py`: `Database` (engine with WAL/foreign keys/busy timeout), `WriterQueue` (one thread, one transaction at a time; `db.write(fn)` / `await db.awrite(fn)`), `WriteTx.publish(event)` (outbox: events persist in the same transaction, dispatch after commit), `db.read()` sessions, `db.readonly()` (query_only sqlite3 connection).
- `core/clipper/db/migrate.py` + `migrations/versions/0001_initial.py` (render_as_batch for SQLite). Test asserts models and migration don't drift.
- `core/clipper/events/types.py`: typed payloads (`job.done`, `review.shipped`, `post.live`, `campaign.taken`, `toggles.changed`, `note.added`, `user.chat`, `question.answered`, `edit.op`, `agenda.updated`, `alert`, ...). `core/clipper/events/bus.py`: `EventBus` (publish, async `subscribe(types)` with `prefix.*` wildcards, sync listeners, `since(id)` history).
- `core/clipper/leases.py`: `LeaseManager` (acquire/renew/release/holder/sweep with expiry).
- `core/clipper/rules/caps.py` (pure warm-up/daily cap/min-gap rules, local-day boundaries in `triggers.timezone`) and `core/clipper/services/posting.py` (`schedule_post_tx`: check + insert in one writer job).
- `core/clipper/services/control.py`: dry run / pause / kill switch / slots in `kv`.

### WP2
- `core/clipper/agents/access.py`: tool catalog (server → tool → read-only) and the per-agent access matrix (PLAN §16.3), max 25 tools per agent, subagents per role.
- `core/clipper/agents/hooks.py`: `ToolCall`, `Verdict`, `GuardContext` protocol, rules `kill_switch`, `paused`, `max_turns`, `access`, `campaign_scope`, `marketplace_switch` (with "finish" mode for live posts), `account_switch`, `social_switch`, `approval` (human review; opt-in auto tier), `posting_caps` (incl. warm-up), `min_gap`, `source_whitelist`, `domain_allowlist`, `submit_own_post`, `edit_lock`; dry-run annotation. `Guard.check()`; `make_pre_tool_use_hook()` / `make_post_tool_use_hook()` for `ClaudeAgentOptions.hooks`. Subagent calls are checked against the subagent's own access (hook input `agent_type`).
- `core/clipper/agents/guard_context.py`: `DbGuardContext` (facts from SQLite) and `make_block_logger()` (agent_event `blocked` + `agent.event`).
- `core/clipper/rules/urls.py` (YouTube/TikTok canonical ids, lookalike-safe domain matching), `core/clipper/rules/spec.py` (`ClipSpec`).

### WP4 (built before WP3: the `edit` tools sit on it)
- `core/clipper/media/edl/schema.py`: `Edl` (segments/camera/captions in source time, overlays in output time), `new_edl()`.
- `core/clipper/media/edl/ops.py`: pure ops `trim`, `split`, `delete_range`, `remove_silences`, `remove_fillers`, `set_layout`, `set_camera_keyframes`, `set_caption_style`, `edit_caption_words`, `emphasize`, `set_hook` (cold open teaser / hook text / none), `add_overlay`, `set_audio`; `apply_op()`, `replay()`, `OPS` registry.
- `core/clipper/media/edl/render.py`: `build_render_plan()` (deterministic ffmpeg args) and `render_edl()`; single seeked input, per-segment trim + layout, concat, ASS, progress bar, denoise/gain, loudnorm (2-pass for finals), fades at every cut; `thumbnail()`, `encode_to_size()` (Discord 2-pass).
- `core/clipper/media/edl/captions.py`: `build_ass()`; styles `bold-pop`, `clean`, `boxed`, `karaoke`; safe zones for TikTok/Shorts/Reels; face avoidance; profanity mask; hook and brand text.
- `core/clipper/media/edl/qa.py`: `check_speech_start`, `check_length`, `check_face_in_frame`, `check_captions_safe_zone`, `check_captions_face`, `check_black_frames`, `check_frozen_frames`, `check_clipping`, `check_silence_ratio`, `measure()`, `qa_report()`.
- `core/clipper/media/edl/service.py`: `EdlService` (init/apply/undo-redo/history/take_over/hand_back/status/make_variant).
- `core/clipper/media/encode.py`: `Encoder` protocol, `X264Encoder` (tested), `NvencEncoder` (LOCAL-VERIFY), profiles.
- `core/clipper/media/reframe.py`: `auto_camera_keys()` (dead zone + min hold). `core/clipper/media/ffmpeg.py`: probe + measurement parsers.
- Fixtures: `tests/fixtures/make_fixtures.py` → `tests/fixtures/media/*` (~580 KB).

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
