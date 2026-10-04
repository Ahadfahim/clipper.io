# HANDOFF — cloud → local

## 1. Snapshot
- Branch / PR: `claude/affectionate-davinci-f3xmlm` / https://github.com/Ahadfahim/clipper.io/pull/1 (draft)
- Last commit: `66869c0` fix(tauri): remember one pop-out position for every Review batch (commits after it only touch this file)
- Work packages:
  - WP0 ✅ Repo scaffold: uv + pnpm workspaces, ruff/pyright (strict on core)/pytest, eslint/tsc/vitest/Playwright, settings example, justfile, CI (lint, tests, builds, screenshots, `cargo check` for Linux and Windows)
  - WP1 ✅ Data layer: 30 SQLModel tables (PLAN §9 + additions), Alembic 0001, SQLite WAL, single writer queue, outbox event bus, leases, atomic posting-cap check
  - WP2 ✅ Guardrails: 15 pure PreToolUse rules + SDK hook adapters, 71 table-driven cases, DB-backed context, blocked calls logged to the console
  - WP3 ✅ MCP tools: 13 servers + `clipper` umbrella (93 tools), typed args, `readOnlyHint`, guard in every call path, adapters with fakes, durable job queue, stdio entry
  - WP4 ✅ EDL engine: schema, 13 pure ops, ffmpeg renderer (crop/split/fit/zoom, progress bar, two-pass loudnorm), ASS captions with safe zones and face avoidance, QA checks, undo by replay, golden renders
  - WP5 ✅ Supervisor + agents: P0–P3 slot pool, event routing with merging, wakeups, watchdog, triggers, kill switch, rate-limit pause/resume; agent definitions on the plan login (billing env blanked); real prompts; SDK runner + fake runner; end-to-end dry-run test
  - WP6 ✅ API: FastAPI REST + WebSocket `/api/ws` on 127.0.0.1 (Host/Origin checks), fixture mode, OpenAPI → typed TS client, static fixture export for the UI
  - WP7 ✅ Desktop UI: utility-style shell and every screen from UI.md on fixture data, live WebSocket updates, Settings dialog, setup wizard, /dev/gallery, 70 screenshots; Tauri v2 shell (native menu, tray, toasts, autostart, pop-outs, Mica, sidecar) compiles for Windows
  - WP8 ✅ Discord bot: persistent buttons/selects/modals on stable custom_ids, campaign cards, forum review batches, ask_user, `/clipper toggle|status`, #control → Director, core event relay with restart catch-up
  - WP9 ✅ Companion extension (MV3): WebSocket bridge with pairing token, recipe engine, challenge detection (stop and report, never solve), 9 recipes (all UNVERIFIED), options page
- Test status (Linux cloud container: Python 3.12.3, Node 22, ffmpeg 6.1 on PATH):
  - `uv run pytest -q` → 319 passed, 10 skipped (9 opt-in LOCAL-VERIFY checks in `tests/local/`, 1 needs mediapipe)
  - `uv run ruff check . && uv run ruff format --check . && uv run pyright` → clean
  - `pnpm -r run lint && pnpm -r run typecheck` → clean
  - `pnpm -r run test` → desktop 26 passed, extension 41 passed
  - `pnpm --filter @clipper/desktop exec playwright test --project=e2e` → 10 passed (fixture build, no Python)
  - `just screenshots` → 70 passed (17 screens × dark/light × 1280×800/1920×1080 + the portrait Review pop-out) into `docs/screenshots/`
  - `cargo check --locked` in `apps/desktop/src-tauri` → clean on Linux and for `--target x86_64-pc-windows-msvc` (CI writes placeholder sidecar files first)
  - `just local-verify` (Windows only) → not run yet

## 2. How to run (on Windows)
PowerShell, from `D:\Clipper.io`. uv, Node 24, Rust, ffmpeg 8.1 (`C:\ffmpeg\bin`), yt-dlp and Chrome are already installed (docs/ENVIRONMENT.md).
```powershell
# 0. Once
git fetch; git checkout claude/affectionate-davinci-f3xmlm
uv tool install rust-just                                   # the `just` task runner
corepack enable                                             # pnpm 10.28 (package.json "packageManager")
Copy-Item config\settings.example.toml config\settings.toml # then review [paths]; the file is gitignored

# 1. Install (uv sync --all-packages --all-extras + pnpm install --frozen-lockfile)
just setup
just doctor                     # environment checks; WARN rows say what is missing

# 2. Migrate (creates D:\Clipper.io\data\clipper.sqlite)
just migrate

# 3. Seed base switches/platforms. NOT `just seed fixtures`: demo data in the real database gets picked up
#    by the real workers (it now refuses unless CLIPPER_DATA_DIR points at a scratch folder).
#    The demo has its own database: `just dev-api-fixtures`.
just seed

# 4. Run the API in fixture mode (own demo DB under <data_dir>\fixture, no agents)   [terminal 1]
just dev-api-fixtures           # http://127.0.0.1:8765/api/health

# 5. Run the UI in fixture mode (static export in apps/desktop/public/fixtures; needs no API) [terminal 2]
just dev-ui-fixtures            # http://127.0.0.1:1420

# 6. Tests
just lint
just test
pnpm --filter @clipper/desktop exec playwright test --project=e2e
just screenshots                # optional: rewrites docs/screenshots

# 7. LOCAL-VERIFY checks (section 4)
just gpu-setup                  # once: the isolated CUDA WhisperX env
$env:CLIPPER_SPEECH_SAMPLE = "C:\path\to\short-speech-clip.mp4"
just local-verify
```
Beyond fixtures:
```powershell
just dev-api                    # the real core: agents, workers, Companion bridge (ws 127.0.0.1:8766)
just dev-ui                     # Vite against the real API
just dev-app                    # Tauri desktop app (dev build; it doesn't start the core, run dev-api)
just dev-bot                    # Discord bot (core running + token in Settings → Discord)
just gen-api                    # after changing an API route: openapi.json + UI fixtures + TS client
just build                      # desktop web build + extension into apps/extension/dist
```

## 3. What was built
### WP0
- `pyproject.toml`: uv workspace root (members `core`, `apps/bot`), ruff and pyright config (strict on `core/clipper`), pytest markers `ffmpeg`, `slow`, `local`.
- `core/clipper/settings.py`: typed settings from `config/settings.toml` (lookup: `CLIPPER_SETTINGS`, then `config/settings.toml`, then defaults). `config/settings.example.toml` is test-enforced to mention every key.
- `core/clipper/agents/env.py`: billing env scrubbing for agent subprocesses (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, ... blanked). `core/clipper/secrets.py`: Windows Credential Manager via `keyring`.
- `core/clipper/doctor.py` + `clipper doctor` (Python, no API key, data dir, DB revision, ffmpeg/NVENC, yt-dlp, face model, secrets, Claude login, GPU env).
- `apps/desktop`: Vite + React 19 + TS strict + Tailwind 4 + vitest + Playwright. `apps/extension`: MV3 TS package with esbuild.
- `justfile`, `.github/workflows/ci.yml` (Python lint/tests, JS lint/typecheck/tests/builds, generated-file drift, Playwright e2e + screenshots, `tauri-check` job).

### WP1
- `core/clipper/db/models.py`: every PLAN §9 table plus `review_batch`, `kv`, `discord_ref`, `recipe_run`.
- `core/clipper/db/engine.py`: `Database` (WAL, foreign keys, busy timeout), `WriterQueue` (one thread, one transaction at a time; `db.write(fn)` / `await db.awrite(fn)`), `WriteTx.publish(event)` (outbox: events persist in the same transaction, dispatch after commit), `db.read()`, `db.readonly()`.
- `core/clipper/db/migrate.py` + `migrations/versions/0001_initial.py` (render_as_batch). A test asserts models and migration don't drift.
- `core/clipper/events/types.py` (typed payloads) and `events/bus.py` (`EventBus`: publish, async `subscribe(types)` with `prefix.*`, `since(id)`, `latest(limit, types)`).
- `core/clipper/leases.py` (`LeaseManager`), `rules/caps.py` (warm-up/daily cap/min gap in `triggers.timezone`), `services/posting.py` (`schedule_post_tx`: check + insert in one writer job, `BEGIN IMMEDIATE`, tested with two writers on one file), `services/control.py` (dry run / pause / kill switch / slots).

### WP2
- `core/clipper/agents/access.py`: tool catalog and per-agent access matrix (PLAN §16.3), max 25 tools per agent, subagents per role.
- `core/clipper/agents/hooks.py`: `ToolCall`, `Verdict`, `GuardContext`; rules `kill_switch`, `paused`, `max_turns`, `access`, `campaign_scope`, `marketplace_switch` (with "finish" mode), `account_switch`, `social_switch`, `approval` (human review; opt-in auto tier), `posting_caps` (incl. warm-up), `min_gap`, `source_whitelist`, `domain_allowlist`, `submit_own_post`, `edit_lock`; dry-run annotation. `Guard.check()`, `make_pre_tool_use_hook()`, `make_post_tool_use_hook()`. Subagent calls are checked against the subagent's own access.
- `core/clipper/agents/guard_context.py` (`DbGuardContext`, `make_block_logger()`), `rules/urls.py` (canonical video ids, lookalike-safe domain matching), `rules/spec.py` (`ClipSpec`).

### WP3
- `core/clipper/core.py`: `Core` (settings, DB, bus, guard, adapters, services, jobs). `Core.create(settings, fakes=True)` for tests/fixtures; `Adapters.real(settings)` wires the Windows adapters.
- `core/clipper/tools/base.py`: `@tool(server, name, description, ArgsModel)`, `ToolContext`, `call_tool()` (validate → guard → handler → small JSON result; frames as images), `sdk_server()` (in-process Agent SDK server with `readOnlyHint`).
- Servers in `core/clipper/tools/`: `state`, `market` (server `marketplace`), `media`, `review`, `publish`, `browser`, `supervisor`, `notify`, `memory`, `trends`, `insights`, `edit` (generated from the EDL op registry), `agenda`, `clipper_server` (umbrella `clipper`). `tools/stdio.py`: `clipper mcp <server>` (`CLIPPER_FAKES=1` for fakes).
- Services (`core/clipper/services/`): campaigns, media, review, publishing (schedule under the cap lock, due-post runner, challenge → pause account + alert), market (fenced untrusted pages), toggles (PLAN §15.2 effects), notify (alerts, ask_user, ntfy), memory, agenda + notes, wakeups, usage, insights, trends.
- Adapters: `marketplaces/{base,fake,browser}.py`, `publishing/{base,fake,browser}.py`, `browser/{protocol,bridge,launch}.py` (`CompanionBridge` WS server: pairing token, origin check, one action per profile, timeouts), `media/{transcribe,download,faces,ocr}.py` (+ `media/gpu_scripts/whisperx_transcribe.py`), `trends/source.py`.
- `core/clipper/worker/{jobs,handlers}.py`: durable job queue (recover on start, per-resource limits) and handlers `download`, `analyze`, `render_preview`, `render_final`.

### WP4
- `core/clipper/media/edl/schema.py`: `Edl` (segments/camera/captions in source time, overlays in output time), `new_edl()`.
- `core/clipper/media/edl/ops.py`: pure ops `trim`, `split`, `delete_range`, `remove_silences`, `remove_fillers`, `set_layout`, `set_camera_keyframes`, `set_caption_style`, `edit_caption_words`, `emphasize`, `set_hook`, `add_overlay`, `set_audio`; `apply_op()`, `replay()`, `OPS`.
- `core/clipper/media/edl/render.py`: `build_render_plan()` (deterministic ffmpeg args), `render_edl()`, `thumbnail()`, `encode_to_size()` (Discord 2-pass).
- `core/clipper/media/edl/captions.py` (`build_ass()`; styles `bold-pop`, `clean`, `boxed`, `karaoke`; platform safe zones; face avoidance; profanity mask), `qa.py` (speech start, length, face in frame, caption safe zone/face, black/frozen frames, clipping, silence ratio), `service.py` (`EdlService`: apply/undo/redo/history/take_over/hand_back/variants).
- `core/clipper/media/encode.py` (`Encoder`, `X264Encoder`, `NvencEncoder`, profiles), `reframe.py`, `ffmpeg.py`. Fixtures: `tests/fixtures/make_fixtures.py` → `tests/fixtures/media/*`.

### WP5
- `core/clipper/agents/definitions.py`: `build_options(SessionSpec, settings, guard=, tool_ctx=, record_builtin=)` → `ClaudeAgentOptions` (`setting_sources=[]`, only needed built-ins, `allowed_tools` + `permission_mode="dontAsk"`, in-process MCP servers limited to the session, role + subagent `AgentDefinition`s, `extra_args={"agent": role}`, hooks, billing env blanked, no `max_budget_usd`).
- `core/clipper/agents/prompts/`: `shared.md` + `scout.md`, `campaign.md`, `analyst.md`, `director.md`, `subagents/{brief-reader,research,editor,cutter,qa-checker,copywriter,browser-fixer}.md`.
- `core/clipper/agents/runner.py`: `AgentRunner` protocol, `SdkAgentRunner` (ClaudeSDKClient; records messages/tool calls/thinking to `agent_event`; rate limits; interrupt), `FakeAgentRunner` (scripted steps through the same hook and tool wrapper).
- `core/clipper/supervisor/`: `router.route()`, `pool.pick()`, `messages.build_prompt()`, `supervisor.Supervisor` (inbox with DB catch-up cursor, one session per campaign resumed via `resume=`, persistent Director, fresh Scout/Analyst, leases, triggers, wakeups, watchdog, due posts, question timeouts, kill switch, bump/cancel, `run_until_idle()`).
- `core/clipper/evaluation.py` + `tests/golden/`: `clipper eval` scoring (pure, tested).

### WP6
- `core/clipper/api/app.py`: `create_app(fixture_mode=, start_background=, core=, settings=)`. Normal mode starts the `CompanionBridge` and the `Supervisor` with `SdkAgentRunner`; fixture mode seeds `<data_dir>/fixture/fixture.sqlite` and starts nothing. `LoopbackGuard` (DNS rebinding), CORS only for Tauri/Vite origins, extension origin may only read `/api/files/...`. WebSocket `/api/ws?after=<id>&types=a,b.*` replays then streams; bad origin → close 4403.
- `core/clipper/api/routes.py`: routers `system`, `agents`, `campaigns`, `library`, `review`, `edit`, `publishing`, `earnings`, `settings`, `files`, `discord`. Every mutation goes through the same services and guards the agents use, with `actor="user"`. Extras for the UI: `GET /api/events?latest=true`, `POST /api/agents/trigger/{scout|analyst}`, `POST /api/agents/events/{id}/replay` (re-checks today's guard rules; executes read-only tools only), `POST /api/browser/profiles/{name}/open`.
- `core/clipper/api/views.py` (read models), `schemas.py` (response/request models), `settings_file.py` (validated `settings.toml` patches; billing keys and paths are not writable from the app).
- `core/clipper/fixtures/seed.py` (`seed_demo()`), `fixtures/export.py` + `clipper fixtures-export <dir>` (static export of every GET the UI makes). `tests/api/test_generated.py` fails when the export or `openapi.json` is stale.
- `apps/desktop/src/api/schema.d.ts` (openapi-typescript) and `client.ts` (openapi-fetch; in `--mode fixtures` a fetch adapter serves the export).

### WP7
- Tokens: `apps/desktop/src/styles/tokens.css` (light/dark, `data-theme`, `data-accent`, `data-density`) mapped in `styles/index.css`. Segoe UI Variable 12px, Cascadia Mono numbers.
- Data: `src/api/queries.ts`, `actions.ts` (optimistic where the screen should move first), `live.ts` (WebSocket, output ring buffer, `keysFor(event)`, toasts), `describe.ts`.
- Shell (`src/shell/`): `AppShell`, `commands.ts` (one registry for menus, Ctrl+K, shortcuts and native menu ids), `MenuBar` (browser build only), `MainToolbar`, `NavTree`, `OutputPanel`, `StatusBar`, `CommandBox` (`>` = Director chat), `StopAllDialog`.
- Screens (`src/screens/`): Overview, Agents, Campaigns, Library, Clip detail, Review (+ portrait pop-out `/popout/review/:id`), Edit, Publishing, Earnings, Settings dialog (12 sections), setup wizard, `/dev/gallery`.
- Tests: `src/**/*.test.ts(x)`, `e2e/app.e2e.ts` (10 flows), `e2e/screens.shots.ts` (screenshots).
- Tauri (`apps/desktop/src-tauri/`): `tauri.conf.json` (native decorations, Mica, min 1200×760, CSP limited to 127.0.0.1:8765, MSI + NSIS, sidecar `binaries/clipper-core`), `src/lib.rs` (single-instance, window-state, notification, autostart, opener, shell; close → tray), `menu.rs`, `tray.rs`, `commands.rs` (`accent_color`, `pop_out`, `notify`, `open_url`, `open_path`, `sync_tray`, `autostart_get/set`, `quit`), `sidecar.rs`.

### WP8
- `apps/bot/clipper_bot/`: `config.py` (settings from `GET /api/settings`; token from Credential Manager `clipper.io/discord_bot_token` or `CLIPPER_DISCORD_TOKEN`), `core_client.py` (httpx client, every write with `via="discord"`, WebSocket stream with reconnect), `ids.py` (`clipper:<scope>:<action>:<id>[:<extra>]`), `actions.py` (role check, take/skip, approve, reject with reason, platforms, captions, re-cut ±5 s, approve all ≥ N, reject rest, ship, answer, toggle, chat), `render.py`, `components.py` (`DynamicItem` per button/select, caption and re-cut modals), `relay.py` (core events → Discord; `catch_up()` re-posts open batches, suggested campaigns and open questions idempotently), `gateway.py` (discord.py calls, first-run channel/forum creation), `bot.py` (`ClipperBot`: streams from the newest event, `/clipper toggle|status`, #control relay, heartbeat), `run.py`.
- Tests: `tests/bot/` against the real core API in-process (`httpx.ASGITransport`), mocked interactions, fake gateway.

### WP9
- `apps/extension/`: `manifest.json` (storage/tabs/scripting/alarms; hosts only 127.0.0.1 and the allowlisted sites), `options.html` + `src/options/options.ts`.
- `src/shared/protocol.ts` (mirror of `core/clipper/browser/protocol.py`, `PROTOCOL_VERSION = 1`), `recipe.ts` (format, validation, `{{param|filter}}`), `allowlist.ts` (same allowlist as the core).
- `src/background/bridge.ts` (hello with token → welcome; one action at a time; ping/pong; backoff 2 s → 30 s; stops on 4401), `runner.ts` (`runRecipe`: dry run stops before the `final` step, pacing 600–2200 ms, allowlist on every step, failure → step + screenshot + simplified DOM, challenge → stop), `driver.ts` (`ChromeTabDriver`: dedicated tab, `chrome.scripting`, `captureVisibleTab`, clip sent to the page in 4 MB chunks), `recipes.ts`, `service_worker.ts`.
- `src/content/engine.ts` (find by selector/text, click, type with framework events, attach via DataTransfer or drop, read/query, `detectChallenge`, `simplifiedDom`), `content.ts`.
- `recipes/`: `schema.json` + `youtube.upload_short`, `tiktok.upload`, `instagram.upload_reel`, `vyro.{list_campaigns,submit_url,session_check}`, `whop.{list_campaigns,submit_url,session_check}`, all `"status": "UNVERIFIED"`. `tests/test_extension_contract.py` keeps core and extension in sync.

### After WP9
- Bot restart fix: it used to stream from event 0 and re-post every old alert; now it starts at the newest event and runs `Relay.catch_up()`.
- `MediaPipeFaceDetector` ported to the mediapipe Tasks API (mediapipe 1.0 removed `mp.solutions`); mediapipe is the `faces` extra.
- `tests/local/test_local_verify.py` + `just local-verify`: the LOCAL-VERIFY checks as opt-in tests (`CLIPPER_LOCAL=1`).
- Settings → Media and captions saves the Hugging Face token (`hf_token` had no input anywhere); the doctor hint names the section for each secret.
- Tauri: every Review pop-out shares one remembered window position (`map_label` in `lib.rs`), so batches keep opening on the portrait monitor; `cargo fmt` over the crate.

## 4. LOCAL-VERIFY list
`just local-verify` covers the rows marked (T). Run it first; then do the manual rows.

| file:line | what | how to verify | expected result |
|---|---|---|---|
| `justfile:93` (`gpu-setup`), `core/clipper/media/transcribe.py:83`, `core/clipper/media/gpu_scripts/whisperx_transcribe.py:1` | CUDA env + WhisperX large-v3 with alignment (+ diarization with the HF token) (T) | `just gpu-setup`; save the Hugging Face token in Settings → Media and captions; set `CLIPPER_SPEECH_SAMPLE`; `just local-verify` (`test_whisperx_transcribes_speech`) | gpu-setup prints `2.8.0+cu128 True NVIDIA GeForce RTX 5080`; ≥ 10 words with monotone timestamps; speakers set when diarizing |
| `core/clipper/media/encode.py:95` (`NvencEncoder.video_args`) | h264_nvenc final render (T) | `just local-verify` (`test_ffmpeg_has_nvenc_and_libass`, `test_nvenc_final_render`) | 1080×1920 H.264 file, `h264_nvenc` in the plan args |
| `core/clipper/api/views.py:156` (`gpu_util`) | GPU % in the status bar (T) | `just local-verify` (`test_gpu_utilization_reads`) | a value in 0..1 |
| `core/clipper/media/faces.py:64` (`MediaPipeFaceDetector.track`) | MediaPipe Tasks face tracks (T) | download the model (`clipper doctor` prints the URL) to `paths.models_dir`; `just local-verify` (`test_mediapipe_face_detector_loads`); then a real podcast clip through `analyze` | test returns `[]` on the test pattern; real clip gives boxes on the speakers |
| `core/clipper/media/ocr.py:29` (`TesseractOcr.read`) | watermark/caption OCR (T) | `winget install UB-Mannheim.TesseractOCR`; `just local-verify` (`test_tesseract_reads_the_burned_in_watermark`) | text contains `WATERMARK` |
| `core/clipper/secrets.py:19` | Windows Credential Manager (T) | `just local-verify` (`test_credential_manager_round_trip`); then save the Discord token in Settings → Discord | round trip passes; secret visible under `clipper.io` in Credential Manager |
| `core/clipper/agents/runner.py:115` (`SdkAgentRunner`), `core/clipper/agents/definitions.py:153` (`--agent` main thread), `core/clipper/agents/env.py:40` | Claude plan login + one real agent turn (T) | `claude` logged in, no `ANTHROPIC_API_KEY` set; `just local-verify` (`test_real_director_turn`); compare with `tests/agents/test_definitions.py:69` (env strip test) | outcome without error, an SDK session id, a `get_usage` tool call, no blocked rows |
| `core/clipper/browser/launch.py:5` | open a Clipper Chrome profile (T for the path) | `just local-verify` (`test_chrome_and_profiles_folder`); Publishing → Accounts → "Open Chrome window" | Chrome opens with its own `--user-data-dir` under `C:\ClipperData\chrome\<profile>` |
| `apps/desktop/src-tauri/src/lib.rs:5` | Tauri build and run on Windows 11 | `just dev-api` + `just dev-app`; later `pnpm --filter @clipper/desktop tauri build` | window opens on the live API; MSI/NSIS installers built |
| `apps/desktop/src-tauri/src/menu.rs:16` | native menu | click every menu item; check accelerators | each item runs the same command as Ctrl+K |
| `apps/desktop/src-tauri/src/tray.rs:17` | tray menu | close the window, use the tray | Open / Pause / Dry run / Quit work; Pause and Dry run checks match the toolbar |
| `apps/desktop/src-tauri/tauri.conf.json:26` | Mica backdrop | run on Windows 11 in light and dark | Mica visible behind the chrome, text readable |
| `apps/desktop/src-tauri/src/commands.rs:15` (`accent_impl`) | Windows accent color | change the accent in Windows Settings, restart the app | selection, focus ring and primary buttons use it |
| `apps/desktop/src-tauri/src/commands.rs:30` (`pop_out`), `apps/desktop/src-tauri/src/lib.rs:19` (`window_state_key`) | Review pop-out window | Review → Pop out; drag it to the portrait monitor; close; pop out another batch | tall window that fits 1080×1920; the next batch opens on the portrait monitor again |
| `apps/desktop/src-tauri/src/commands.rs:64` (`notify`) | Windows toasts | trigger an error alert (e.g. pause an account from Publishing) | a toast with the alert text appears |
| `apps/desktop/src-tauri/src/commands.rs:108` (`autostart_set`) | start with Windows | Settings → General → "Start with Windows (minimized to the tray)"; sign out and in | app starts minimized to the tray |
| `apps/desktop/src/components/domain/edit.tsx:65` (`EdlPreview`) | H.264 playback in WebView2 | open Edit on a real clip | the canvas preview plays the source proxy (headless Chromium in CI falls back to the thumbnail) |
| `apps/desktop/src-tauri/src/sidecar.rs:5`, `apps/desktop/src-tauri/binaries/README.md:7` | Python core sidecar packaging | build `binaries/clipper-core-x86_64-pc-windows-msvc.exe` (PyInstaller one-folder or a uv launcher), `tauri build`, install, run | installed app starts the core on 127.0.0.1:8765 and stops it on Quit |
| `core/clipper/api/app.py:108`, `core/clipper/browser/bridge.py:136`, `apps/extension/src/background/driver.ts:2` | extension in the Clipper Chrome profile + pairing | `just build`; load `apps/extension/dist` unpacked in the profile; Settings → Accounts and browser → Create token, paste it into the extension's options page | options page shows "Connected to Clipper."; the status bar shows the extension connected |
| `apps/extension/recipes/youtube.upload_short.json` | YouTube Studio upload selectors | Publishing → Recipes → "Test in dry-run" on the logged-in profile, then one real private upload | dry run reaches the final step; real run returns the post URL; set `"status": "VERIFIED"` |
| `apps/extension/recipes/tiktok.upload.json` | TikTok Studio upload selectors | same as above | same |
| `apps/extension/recipes/instagram.upload_reel.json` | Instagram Reel upload selectors | same as above | same |
| `apps/extension/recipes/vyro.session_check.json`, `vyro.list_campaigns.json`, `vyro.submit_url.json` | Vyro selectors | Test each recipe; compare scraped rows with the site | `logged_in: true`; campaign rows with id/title/CPM/budget/platforms; submit only on a real approved post |
| `apps/extension/recipes/whop.session_check.json`, `whop.list_campaigns.json`, `whop.submit_url.json` | Whop selectors | same as Vyro | same |
| `core/clipper/marketplaces/browser.py:123`–`:163` | recipe-backed marketplace adapter | after the recipes work: Campaigns → refresh with the marketplace switch on, in dry run | campaigns appear with `card_from_row` fields filled |
| `core/clipper/publishing/browser.py:21` / `:50` / `:71` | upload, metrics via yt-dlp, account health | one dry-run publish, then one real private upload; wait for the metrics job | post URL saved; views/likes appear in Library; account health needs its recipe (section 5) |
| `core/clipper/media/download.py:103` / `:131` | yt-dlp download + comments | add a whitelisted source on a test campaign | ≤ 1080p file, subtitles and heatmap saved under `sources_dir` |
| `core/clipper/trends/source.py:69` / `:97` | yt-dlp trend search | Analyst trigger or `clipper mcp trends` → `niche_trends` | titles/views/urls returned |
| `core/clipper/core.py:69` (`Adapters.real`) | wiring of all Windows adapters | `just dev-api` with a real config | starts without errors; doctor all OK/WARN |
| `apps/bot/clipper_bot/run.py:37`, `apps/bot/clipper_bot/gateway.py:91`, `apps/bot/clipper_bot/bot.py:42` | live Discord bot | enable the Message Content intent in the Developer Portal; invite the bot; `just dev-bot` | channels/forum created once; review batch posts; buttons work after a bot restart; old alerts not re-posted |
| `core/clipper/evaluation.py:67` | `clipper eval` on real runs | needs the golden set and a picker (section 7) | score printed; exit 1 below baseline |

## 5. Known gaps and TODOs
1. Recipes the core calls that don't exist yet (`get_campaign` now exists for both): `vyro|whop.join_campaign`, `.submission_status`, `.earnings` (`core/clipper/marketplaces/browser.py:132`–`:163`), `<platform>.account_health` (`core/clipper/publishing/browser.py:71`) and `x.post_video` (`core/clipper/publishing/base.py:60`, phase 5). Calls fail with a clear `MarketplaceError` until they exist. All 9 shipped recipes are UNVERIFIED (`apps/extension/recipes/*.json`).
2. Retention and backups are settings only: nothing deletes old sources/screenshots/logs or writes nightly backups (`core/clipper/settings.py:255` `RetentionSettings`; Settings → Backups in `apps/desktop/src/screens/settings/SettingsDialog.tsx:563`). With ~79 GB free on D: and 1–3 GB per source, add this before running agents for long.
3. No real agent run yet: prompts, `--agent` main thread, subagent tool limits and rate-limit handling are tested only with the fake runner and a fake CLI (`core/clipper/agents/runner.py:115`).
4. `clipper eval` has no picker and `tests/golden/manifest.json` is empty, so Settings → Agents → Save saves prompts without evaluation (`core/clipper/api/routes.py:828`).
5. Core sidecar packaging not built (`apps/desktop/src-tauri/binaries/README.md`); the installer is untested.
6. Payout dates not tracked: Earnings shows the payout delay as unknown (`core/clipper/api/views.py:1309`) until an `earnings` recipe exists.
7. Discord `#published` posts once on `post.live` and is not updated with view counts (`apps/bot/clipper_bot/relay.py:101`).
8. Agents → Fork is disabled (`apps/desktop/src/screens/AgentsScreen.tsx:168`).
9. Active-speaker detection (PLAN §18.2) is not built; reframing uses the largest face (`core/clipper/media/faces.py`, `core/clipper/media/reframe.py`).
10. GPU time is not metered (only live utilization in the status bar).
11. Library grid is not virtualized (`apps/desktop/src/screens/LibraryScreen.tsx`); fine for a few thousand clips.

## 6. Decisions and deviations from PLAN.md / UI.md
- Job queue: a durable `job` table + in-process worker threads instead of Huey. Heavy work already runs in subprocesses (ffmpeg, yt-dlp, WhisperX), and in-process jobs reach the supervisor's event bus without cross-process plumbing. Limits as PLAN §17.3 (1 transcribe, 3 encodes, 2 downloads).
- Subagents: PLAN's *editor* is split into **editor** (picks moments) and **cutter** (EDL edits), plus a **browser-fixer** subagent with the browser fallback tools. Reason: the 25-tool limit and prompt-injection isolation (the agent that reads web pages has no publish/submit tools). Analyst web access goes through the *research* subagent.
- `state` gained `get_learning_examples` (PLAN §4) and `set_tuning`; the umbrella exposes `set_switch`/`set_paused` to the Director.
- Added tables `review_batch`, `kv`, `discord_ref`, `recipe_run`. The toggle change log is the `toggles.changed` events.
- WhisperX runs in a separate CUDA env as a subprocess (keeps torch out of the core env; matches the verified setup in docs/LOCAL_CHECKS.md).
- Python package at `core/clipper/` (import `clipper`) so editable installs and pyright work on Windows without symlinks.
- Face detection uses the MediaPipe Tasks BlazeFace short-range model (the legacy API is gone in mediapipe 1.0). Short range is tuned for faces close to the camera; podcast framing fits, wide stage shots may miss faces.
- Menu bar: native Windows menu in the app; the HTML menu bar renders only in the browser build. Both send the same command ids.
- KPI tiles are a one-row stat strip, not cards (UI.md §1 rules out dashboard tiles). "Stop everything" is a confirm dialog; `HoldButton` exists in the gallery only.
- Settings → Tools and MCP shows the access matrix read-only: who may call what is a safety rule kept in code (`core/clipper/agents/access.py`).
- "Replay in dry-run" re-checks a recorded call against today's rules and re-runs it only if the tool is read-only.
- Each Clipper Chrome profile is its own `--user-data-dir` under `paths.chrome_profiles_dir` (plain Chrome, no automation or fingerprint flags).
- Discord: persistent components use discord.py `DynamicItem` on stable custom_ids; the bot keeps no state (message ids live in `discord_ref`). Switching off from Discord uses the gentle defaults (finish active campaigns, keep scheduled posts); the app's dialog offers the other choices.
- UI fixture mode is a static export instead of a running fixture core, so Playwright and `dev:fixtures` need no Python.
- The bot does not replay history on restart: it starts at the newest event and re-posts only waiting work (open batches, suggested campaigns, open questions).

## 7. Interfaces the local side must implement or finish
- **Recipes** (`apps/extension/recipes/<name>.json`, format in `schema.json`; the runner returns the `returns` keys as `data`):
  - `<market>.get_campaign` params `{id}` → `{campaign: {id,title,brand,cpm,budget_left,platforms,deadline,join,url}, rules_text, sources: [url]}`
  - `<market>.join_campaign` params `{id}` → `{status: "joined"|"already"|"needs_user", detail}` (paid joins always `needs_user`)
  - `<market>.submission_status` params `{submission_id}` → `{status: "pending"|"approved"|"rejected"|"paid", reason}`
  - `<market>.earnings` params `{since}` (ISO date) → `{payouts: [{campaign_id, post_url, amount, views, date}]}`
  - `<platform>.account_health` params `{handle}` → `{followers, recent_views, warnings: [str]}` (runs in the `main` profile)
  - `x.post_video` same params as the other uploads (`file_url, file_name, title, caption, hashtags, schedule_at, handle`) → `{post_url}`
  - Plug-in: `core/clipper/marketplaces/browser.py` (`RecipeMarketplace`) and `core/clipper/publishing/browser.py` (`BrowserPublisher`) already call these names. Add each to `tests/test_extension_contract.py` when it ships.
- **Core sidecar**: an executable `apps/desktop/src-tauri/binaries/clipper-core-x86_64-pc-windows-msvc.exe` that accepts `api` and runs `clipper api` (FastAPI on 127.0.0.1:8765). Started by `sidecar::start` in release builds (`apps/desktop/src-tauri/src/sidecar.rs:15`).
- **Golden set**: `tests/golden/manifest.json` with `{baseline, sources: [{id, path, spec, approved: [[start,end]], rejected: [[start,end]]}]}` (format in `tests/golden/README.md`), and a picker `picker(source: dict) -> list[tuple[float, float]]` passed to `run_eval(picker)` (`core/clipper/evaluation.py:58`) that runs the editor subagent on the source; wire it into `clipper eval` (`core/clipper/cli.py:75`) and the prompt save route (`core/clipper/api/routes.py:814`).
- **Retention/backups**: a scheduled job using `RetentionSettings` (`core/clipper/settings.py:255`): delete source media `sources_days_after_end` days after a campaign ends, screenshots and logs after their days, and a nightly SQLite backup (`sqlite3` backup API, read-only connection) into `paths.backups_dir` keeping `backups_keep`. Register it with the supervisor triggers (`core/clipper/supervisor/supervisor.py`).
- **Adapter protocols** (swap or fix implementations here): `Transcriber` (`core/clipper/media/transcribe.py:49`), `Encoder` (`core/clipper/media/encode.py:40`), `FaceDetector` (`core/clipper/media/faces.py:16`), `OcrEngine` (`core/clipper/media/ocr.py:11`), `Downloader` (`core/clipper/media/download.py:36`), `TrendsSource` (`core/clipper/trends/source.py:31`), `BrowserBridge` (`core/clipper/browser/bridge.py:38`), `MarketplaceAdapter` (`core/clipper/marketplaces/base.py:79`), `PublishAdapter` (`core/clipper/publishing/base.py:50`), `AgentRunner` (`core/clipper/agents/runner.py:54`). Wiring: `Adapters.real` (`core/clipper/core.py:69`).

## 8. Ordered task list for the local session
1. Environment: run section 2 steps 0–6 and report failures before changing code.
   Done when `just doctor` has no FAIL rows and `just lint`, `just test` and the e2e run pass on Windows.
2. GPU: `just gpu-setup`, save the Hugging Face token (Settings → Media and captions, or `uv run keyring set clipper.io hf_token`), set `CLIPPER_SPEECH_SAMPLE`, then `just local-verify`.
   Done when the WhisperX, NVENC, GPU, OCR, faces, Chrome and Credential Manager checks pass (install Tesseract and the face model first).
3. Claude plan login: `test_real_director_turn` in `just local-verify`.
   Done when it passes with no `ANTHROPIC_API_KEY` in the environment and the Agents screen (with `just dev-api` + `just dev-ui`) shows the turn.
4. Tauri: `just dev-api` + `just dev-app`; check menu, tray, Mica, accent, toasts, pop-out on the portrait monitor, autostart (section 4 rows).
   Done when every Tauri row in section 4 matches its expected result; fix anything in `apps/desktop/src-tauri/src/`.
5. Visual check in WebView2: screenshot each screen in dark and light at the ultrawide size and compare with `docs/screenshots/` and UI.md.
   Done when no screen differs from UI.md beyond what section 6 lists.
6. Extension: `just build`, load `apps/extension/dist` in the Clipper Chrome profile, pair it.
   Done when the options page says "Connected to Clipper." and the status bar shows the extension.
7. Recipes, one site at a time (log in by hand first; dry run before any real action): `vyro.*`, `whop.*`, then `youtube.upload_short`, `tiktok.upload`, `instagram.upload_reel` (one private upload each).
   Done when each recipe passes its dry-run test and one real run, and its `status` is `VERIFIED`.
   Status (2026-10-03): the read side of both marketplaces is `verified` against the live sites in dry run: `vyro|whop.session_check`, `.list_campaigns` and the new `.get_campaign` (site notes: `docs/LOCAL_CHECKS.md`, "Marketplace sites"). `youtube.upload_short` is `verified` with a real run: `POST /api/publishing/recipes/youtube.upload_short/check-upload` `{"confirm": true}` uploads a synthetic test clip as Private (`services/recipe_check.py`) and returned the Short's link. Left: `vyro|whop.submit_url` (needs a real approved post), `tiktok.upload` and `instagram.upload_reel`. Those two need logging in in the Clipper browser and a private option before they can be check-uploaded.
8. Missing recipes from section 7 (`get_campaign`, `join_campaign`, `submission_status`, `earnings`, `account_health`).
   Done when each exists, is verified, and is listed in `tests/test_extension_contract.py`.
9. Retention and backups job (section 7).
   Done when a test with a fake clock deletes expired media and keeps `backups_keep` backups, and Settings → Backups shows the last backup.
10. Discord: create the bot, enable Message Content intent, save the token, `just dev-bot`.
    Done when a fixture review batch can be approved from Discord and a bot restart doesn't re-post old messages.
11. First supervised dry run: one real campaign in dry run end to end (scout → take → download → transcribe → pick → render → review in Discord → dry-run publish).
    Done when the clip reaches "posted (dry run)" with no blocked calls you didn't expect.
12. Golden set + `clipper eval` picker (section 7).
    Done when `clipper eval` prints a score for 10 sources and the prompt Save button refuses a worse prompt.
13. Sidecar packaging + `tauri build`.
    Done when the installed app starts the core by itself and stops it on Quit.

## 9. Risks and open questions for the user
- Platform terms: automated uploads through your own logged-in browser may still break YouTube/TikTok/Instagram rules. The build caps posts, paces steps, pauses on any challenge and never solves CAPTCHAs, but account risk stays with you. Start with low caps and warm-up on.
- Discord needs the privileged Message Content intent for the #control relay. Without it, only slash commands and buttons work. Enable it or accept that limit.
- Payout tracking: do Vyro and Whop show per-campaign payouts with dates on a page the extension can read? If not, payout delay stays unknown.
- Whop: does the clipping program have a usable public listing page, or only per-campaign links? This decides whether `whop.list_campaigns` can work at all.
- Auto-approve: it stays opt-in per campaign above a score threshold. Do you want it offered at all in the first weeks, or keep every clip human-reviewed?
- Recipe verification needs real logged-in accounts on each site. Which accounts (and which Chrome profile names) should be used for testing versus live posting?
- Disk: the data folder defaults to `D:\Clipper.io\data` (~79 GB free). Should sources go to `C:\ClipperData\sources` instead (`paths.sources_dir`)?
