# HANDOFF — cloud → local

## 1. Snapshot
- Branch / PR: `claude/affectionate-davinci-f3xmlm` / PR: none yet
- Last commit: see `git log -1` (WP0 scaffold)
- Work packages:
  - WP0 ✅ Repo scaffold: uv + pnpm workspaces, ruff/pyright(strict core)/pytest, eslint/tsc/vitest/Playwright, settings example, justfile, CI
  - WP1 ✅ Data layer: 30 SQLModel tables (PLAN §9 + additions), Alembic 0001, WAL, single writer queue, typed event bus, leases, atomic cap check
  - WP2 ✅ Guardrails: 15 pure PreToolUse rules + SDK hook adapters, 71 table-driven cases, DB context, blocked calls logged
  - WP3 ✅ MCP tools: 13 servers + `clipper` umbrella (93 tools), typed args, readOnlyHint, guard in every call path, adapters with fakes (marketplace, publish, browser bridge, transcriber, encoder, downloader, faces, OCR, trends), durable job queue, stdio entry
  - WP4 ✅ EDL engine: schema, 13 pure ops, renderer (eased crop/split/fit/zoom/progress bar/two-pass loudnorm), ASS captions with safe zones + face avoidance, QA checks, EdlService (edit_op log, undo by replay, locks, variants), golden renders
  - WP5 ✅ Supervisor + agents: slot pool (P0-P3, P0 reserve, usage shrink, rate-limit pause/auto-resume, daily cap), event -> resume routing with merging, wakeups, watchdog, triggers, kill switch; agent definitions (setting_sources=[], dontAsk, per-role effort/max_turns, claude-opus-5-5); real prompts; SdkAgentRunner + FakeAgentRunner; end-to-end dry-run test
  - WP6 ✅ API: FastAPI REST (70 paths) + WebSocket `/api/ws` on 127.0.0.1 (Host/Origin checks), fixture mode with a seeded demo DB, OpenAPI → typed TS client, static fixture export for the UI
  - WP7 ✅ Desktop UI: utility-style shell (menu bar, toolbar with switch checkboxes, tree, resizable panes, docked output panel, status bar, Ctrl+K with `>` Director), all screens + Settings dialog + setup wizard + /dev/gallery on fixture data, live WebSocket updates, 26 vitest + 10 Playwright flows, 70 screenshots in docs/screenshots; Tauri v2 shell (native menu, tray, toasts, autostart, single instance, pop-outs, Mica, sidecar) `cargo check`ed for Linux and Windows
  - WP8 ✅ Discord bot: persistent DynamicItem components (stable custom_ids), campaign cards, forum review batches with pinned summary, reason picker, caption and re-cut modals, platform select, ask_user buttons, `/clipper toggle|status`, #control → Director threads, core event relay, first-run channel setup; 19 tests against the real core API with mocked interactions
  - WP9 ✅ Companion extension (MV3, TypeScript): WebSocket bridge with pairing token, reconnect and one-action-at-a-time queue; recipe engine (navigate, wait_for, query, click, type, attach_file via a file fetched from 127.0.0.1 and DataTransfer, read_text, screenshot, snapshot); failures return screenshot + simplified DOM; challenge detection stops and reports (never solved); 9 recipes, all UNVERIFIED; options page; 41 jsdom tests
- Test status:
  - `uv run pytest -q` → 314 passed (golden renders and the fixture-export check need ffmpeg on PATH)
  - `uv run ruff check . && uv run pyright` → clean
  - `pnpm -r run lint && pnpm -r run typecheck && pnpm -r run test` → clean; desktop 26 passed, extension 41 passed
  - `pnpm --filter @clipper/desktop exec playwright test --project=e2e` → 10 passed (fixture build, no Python)
  - `just screenshots` → 70 passed (17 screens × dark/light × 1280×800/1920×1080 + portrait Review pop-out)
  - `cargo check` in `apps/desktop/src-tauri` → clean on Linux and for `--target x86_64-pc-windows-msvc` (needs placeholder sidecar files, see CI)

## 2. How to run (on Windows)
```powershell
cd D:\Clipper.io
uv tool install rust-just          # once
just setup                         # uv sync --all-packages + pnpm install
just doctor                        # environment checks
just lint
just test
just dev-api-fixtures              # API on http://127.0.0.1:8765 with seeded demo data (no agents)
just dev-ui-fixtures               # UI on http://127.0.0.1:1420 reading the static fixture export (no Python)
just gen-api                       # after changing an API route: openapi.json + UI fixtures + TS client
just dev-api                       # the real core on 127.0.0.1:8765 (agents, workers, Companion bridge)
pnpm --filter @clipper/desktop tauri dev   # the desktop app (LOCAL-VERIFY: first Windows run)
just dev-bot                       # the Discord bot (needs the core running and a token in Settings → Discord)
just screenshots                   # Playwright screenshots of every screen into docs/screenshots
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

### WP3
- `core/clipper/core.py`: `Core` (settings, DB, bus, guard, adapters, services, jobs). `Core.create(settings, fakes=True)` for tests/fixtures; `Adapters.real(settings)` wires the Windows adapters (LOCAL-VERIFY).
- `core/clipper/tools/base.py`: `@tool(server, name, description, ArgsModel)`, `ToolContext`, `call_tool()` (validate -> guard -> handler -> small JSON result, images for frames -> `agent_event`), `sdk_server()` (in-process Agent SDK server with `readOnlyHint`), `ToolOutput`.
- Servers in `core/clipper/tools/`: `state`, `market` (server name `marketplace`), `media`, `review`, `publish`, `browser`, `supervisor`, `notify`, `memory`, `trends`, `insights`, `edit` (generated from the EDL op registry), `agenda`, `clipper_server` (umbrella `clipper`). Catalog + access matrix: `core/clipper/agents/access.py`.
- `core/clipper/tools/stdio.py`: `clipper mcp <server>` (umbrella for Claude Desktop/Code; dev servers for calling tools by hand). Set `CLIPPER_FAKES=1` to run against fakes.
- Services (`core/clipper/services/`): campaigns (upsert, take/skip, spec, budget run-out prediction), media (sources, paged transcript, signals, frames, contact sheet, OCR, moments, renders), review (batches, decisions, approve-all >= N, reject rest, ship, re-cut, captions, auto-approve offer), publishing (schedule under the cap lock, due-post runner, challenge -> pause account + alert, metrics), market (adapters, fenced untrusted pages, joins, submissions, earnings), toggles (PLAN §15.2 effects + switch-on checks), notify (alerts, ask_user, answers, ntfy), memory, agenda + notes, wakeups, usage, insights (read-only), trends.
- Adapters: `marketplaces/{base,fake,browser}.py`, `publishing/{base,fake,browser}.py`, `browser/{protocol,bridge}.py` (`CompanionBridge` WS server: pairing token, origin check, one action per profile, timeouts), `media/{transcribe,download,faces,ocr}.py` (+ `media/gpu_scripts/whisperx_transcribe.py`), `trends/source.py`.
- `core/clipper/worker/{jobs,handlers}.py`: durable job queue (`job` table, recover on start, per-resource limits) and handlers `download`, `analyze`, `render_preview` (review preview + QA + Discord size fit), `render_final`.
- Writes use `BEGIN IMMEDIATE`, so cap checks stay atomic across processes (tested with two writers on one file).

### WP5
- `core/clipper/agents/definitions.py`: `build_options(SessionSpec, settings, guard=, tool_ctx=, record_builtin=)` -> `ClaudeAgentOptions` (setting_sources=[], `tools` = only needed built-ins, `allowed_tools` + `permission_mode="dontAsk"`, in-process MCP servers limited to the session's tools, `agents` = role + subagent `AgentDefinition`s with their own tool lists/effort/maxTurns, `extra_args={"agent": role}`, hooks, `env` with billing keys blanked, no `max_budget_usd`).
- `core/clipper/agents/prompts/`: `shared.md` (untrusted-content and guard rules) + `scout.md`, `campaign.md`, `analyst.md`, `director.md`, `subagents/{brief-reader,research,editor,cutter,qa-checker,copywriter,browser-fixer}.md`.
- `core/clipper/agents/runner.py`: `AgentRunner` protocol; `SdkAgentRunner` (ClaudeSDKClient; records messages/tool calls/thinking summaries to `agent_event`; handles `RateLimitEvent`, `rate_limit` errors and 429s; interrupt); `FakeAgentRunner` (scripted `ToolStep`/`Say`/`RateLimited`, runs through the same PreToolUse hook and tool wrapper).
- `core/clipper/supervisor/`: `router.route()` (event -> priority/role/campaign; merging in `Supervisor.enqueue`), `pool.pick()` (pure scheduling), `messages.build_prompt()` (short resume messages with usage/dry-run/pinned notes), `supervisor.Supervisor` (inbox with DB catch-up cursor, dispatch, one session per campaign resumed via `resume=`, persistent Director, fresh Scout/Analyst, leases, triggers, wakeups, watchdog, due posts, question timeouts, kill switch, slot board, bump/cancel, `run_until_idle()` for tests).
- `CampaignService.update`: agents can take a campaign only in `auto` mode above the auto-take score (enforced in code).
- `core/clipper/evaluation.py` + `tests/golden/`: `clipper eval` scoring (pure, tested); the picker needs a real editor run.

### WP6
- `core/clipper/api/app.py`: `create_app(fixture_mode=, start_background=, core=, settings=)`. Lifespan builds `Core`; normal mode also starts the `CompanionBridge` WS server and the `Supervisor` with `SdkAgentRunner`; fixture mode seeds a fresh DB at `<data_dir>/fixture/fixture.sqlite` and starts nothing. `LoopbackGuard` rejects non-loopback `Host` headers (DNS rebinding); CORS only for the Tauri/Vite origins (`APP_ORIGINS`); the extension origin may only read `/api/files/...` (uploads). WebSocket `/api/ws?after=<event id>&types=a,b.*` replays the backlog then streams live events (`agent.event`, `job.progress`, `clip.updated`, `review.decided`, `post.status`, `alert`, `edit.op`, `agenda.updated`, ...), with pings; bad origin → close 4403.
- `core/clipper/api/routes.py`: routers `system` (status, health, doctor, switches + switch-off preview, control, events, jobs, notes, questions), `agents` (board, sessions, interrupt/nudge, bump/cancel requests, Director chat), `campaigns` (list/detail/take/skip/pause/spec/manual), `library` (clips), `review` (batches, decisions, caption, re-cut, approve-all >= N, reject rest, ship, auto-approve offer), `edit` (state, ops, undo, take-over/hand-back, preview), `publishing` (accounts, calendar, cancel/reschedule, recipes + test), `earnings`, `settings` (settings.toml patch, prompts, lessons, tools matrix, secrets → Credential Manager), `files` (clip previews/thumbs, recipe screenshots, upload files; root allowlist), `discord` (bot heartbeat, message refs, preview path). Every mutation goes through the same services (and guards) the agents use, with `actor="user"`.
- `core/clipper/api/views.py` (read models) and `schemas.py` (response/request models; the TS types come from these).
- `core/clipper/api/settings_file.py`: validated `settings.toml` patches (agent billing keys and paths are not writable from the app).
- `core/clipper/fixtures/seed.py`: `seed_demo()` (8 campaigns in every state, a 12-clip review batch, live/scheduled posts, 14 days of metrics, sessions/events/requests/jobs/questions/notes/lessons/recipe runs, usage; renders a real preview + thumbnails with ffmpeg). `clipper seed --fixtures`.
- `core/clipper/fixtures/export.py` + `clipper fixtures-export <dir>`: deterministic static export of every GET the UI makes (`apps/desktop/public/fixtures/api/*.json`, `manifest.json`, media in `files/`). `tests/api/test_generated.py` fails when it or `core/clipper/api/openapi.json` is stale.
- `apps/desktop/src/api/schema.d.ts` (generated by `openapi-typescript`) and `client.ts` (`openapi-fetch` client; in `--mode fixtures` a fetch adapter serves the static export, mutations return `{ok: true}`; `fileUrl()` maps media).

### WP7
- Design tokens: `apps/desktop/src/styles/tokens.css` (light/dark from the prototypes' Utility page, follows `prefers-color-scheme`, `data-theme` override, `data-accent` for the Windows accent, `data-density`), mapped to Tailwind in `styles/index.css`. Segoe UI Variable 12px with fallbacks, Cascadia Mono for numbers (`.num`).
- Data: `src/api/queries.ts` (TanStack Query hooks), `actions.ts` (every mutation, optimistic where the screen should move first: review decisions, switches, notes, bump/cancel), `live.ts` (WebSocket `/api/ws`, ring buffer for the output panel, `keysFor(event)` → which queries refresh, toasts), `describe.ts` (event → one-line text).
- Shell (`src/shell/`): `AppShell` (menu bar only in the browser build, toolbar, dry-run bar, tree | document panes, output panel, status bar; hotkeys; native menu events), `commands.ts` (one registry for menus, Ctrl+K, shortcuts and the native menu ids), `MainToolbar`, `NavTree`, `OutputPanel` (Activity · Agent output · Jobs · Problems), `StatusBar` (usage popover), `CommandBox` (cmdk; `>` = Director chat inline), `StopAllDialog` (kill switch behind a confirm).
- Screens (`src/screens/`): Overview (KPI strip, needs-you grid with inline actions, health, campaigns with stage stepper + budget burn bar, agent slots, agenda + pinned global notes, next-24h strip), Agents (slot board + P0–P3 queue with bump/cancel, sessions, live transcript with grouped tool calls/subagent blocks/blocked rows, filters, context with Interrupt/Nudge/Resume, Replay in dry-run, Director chat), Campaigns (tabs, marketplace/type filters, data grid with context menu, drawer: Overview/Brief(untrusted)/Spec form/Sources/Clips/Timeline/Money, paste URL), Library (9:16 cards, filters, sort, `/`), Clip detail (player with frame stepping, transcript sync, signal timeline, scores, QA, versions, posts), Review (queue, player, properties + per-platform captions, A/R(1–5)/E/C/Space/arrows/Shift+A, re-cut trim strip ±5s + layout, approve-all, reject-rest, ship, auto-approve offer, Discord sync labels, portrait pop-out at `/popout/review/:id`), Edit (live EDL preview drawn on a canvas from the source proxy, multi-track timeline with the violet agent range, history with undo, agenda + notes with scope, take over/hand back, manual tools I/O/S/Del/layout/captions/hook/word edit), Publishing (week calendar per account with drag + cap/min-gap checks, accounts grid with warm-up and Resume, recipes with dry-run test, queue), Earnings (stacked daily charts per marketplace, separate views chart, breakdown tables, top clips, unit numbers, table view), Settings dialog (12 sections incl. switch-off flows, change log, prompt editor with diff + quality test, pairing token, Discord token, caption style gallery, MCP stats, access matrix, memory browser, doctor), setup wizard (8 steps), `/dev/gallery`.
- Tests: `src/**/*.test.ts(x)` (format, EDL time mapping, transcript grouping, calendar rules, theme, hotkeys, live event mapping, prompt diff, DataGrid, SwitchOffDialog, Review keyboard flow on the real route tree) and `e2e/app.e2e.ts` (10 flows). `e2e/screens.shots.ts` writes `docs/screenshots/`.
- Tauri (`apps/desktop/src-tauri/`): `tauri.conf.json` (native decorations, Mica via `windowEffects`, min 1200×760, CSP limited to 127.0.0.1:8765, MSI + NSIS, sidecar `binaries/clipper-core`), `src/lib.rs` (plugins: single-instance, window-state, notification, autostart, opener, shell; close → hide to tray), `menu.rs` (native menu with the web command ids), `tray.rs` (Open · Pause/Resume · Dry run · today · Quit, synced from the UI), `commands.rs` (`accent_color` via WinRT UISettings, `pop_out`, `notify`, `open_url`, `open_path`, `sync_tray`, `autostart_get/set`, `quit`), `sidecar.rs` (starts `clipper-core api` in release builds).
- Core additions for the UI: `GET /api/events?latest=true`, `POST /api/agents/trigger/{scout|analyst}`, `POST /api/agents/events/{id}/replay` (re-checks today's guard rules; executes read-only tools only), `POST /api/browser/profiles/{name}/open` (`core/clipper/browser/launch.py`), your own messages in `GET /api/agents/director/messages`, honest earnings units (median find → post computed; payout delay unknown until payouts are tracked).

### WP8
- `apps/bot/clipper_bot/`: `config.py` (bot settings come from the core's `GET /api/settings`; token from Credential Manager `clipper.io/discord_bot_token`, or `CLIPPER_DISCORD_TOKEN` for development), `core_client.py` (async httpx client for the internal API, every write with `via="discord"`; WebSocket event stream with reconnect/resume), `ids.py` (stable `clipper:<scope>:<action>:<id>[:<extra>]` ids + templates), `actions.py` (role check by reviewer role id, else name; take/skip, approve, reject with reason, platforms, captions, re-cut with ±5 s validation, approve all ≥ threshold, reject rest, ship, answer, toggle, chat), `render.py` (embeds and component rows), `components.py` (one `DynamicItem` per button/select so clicks work after restarts; caption and re-cut modals), `relay.py` (core events → Discord: campaign cards, forum post per batch with one message per clip + pinned summary + tags pending/in review/shipped, re-render on any decision including dashboard ones, preview replacement, questions, alerts, publish log, Director replies into the #control thread), `gateway.py` (discord.py calls + first-run channel/forum creation saved back to settings), `bot.py` (`ClipperBot`: dynamic items, `/clipper toggle` and `/clipper status`, #control relay, heartbeat every 60 s), `run.py`.
- Core: the clip detail's `review` now includes `batch_id` (the relay finds the batch to re-render).
- Tests: `tests/bot/` (actions against the real core API in-process via `httpx.ASGITransport`, components with mocked interactions incl. role refusal and modals, relay with a fake gateway, #control relay).

### WP9
- `apps/extension/` (MV3, built with esbuild into `dist/`; load it unpacked): `manifest.json` (permissions storage/tabs/scripting/alarms; host permissions only for 127.0.0.1 and the allowlisted sites), `options.html` + `src/options/options.ts` (profile name, pairing token, port; connection status).
- `src/shared/protocol.ts` (mirror of `core/clipper/browser/protocol.py`, `PROTOCOL_VERSION = 1`), `recipe.ts` (format, validation, `{{param}}` / `{{param|noat|tags|url}}` templates), `allowlist.ts` (same domain allowlist as the core; lookalike-safe; files only from `127.0.0.1/api/files/`).
- `src/background/bridge.ts` (`CompanionBridge`: hello with token → welcome; `run` and `action` requests queued one at a time; ping/pong; backoff 2 s → 30 s; stops on 4401 bad token; local URLs only), `runner.ts` (`runRecipe`: required params, `when`, `optional`, dry run stops before the `final` step and never fetches the clip, pacing from `step_delay_ms` (600–2200 ms default), allowlist checks on every step, failure → step index + screenshot + simplified DOM, challenge → stop), `driver.ts` (`ChromeTabDriver`: one dedicated tab, `chrome.scripting` injection, `captureVisibleTab`, fetches the clip from the core and sends it to the page in 4 MB base64 chunks), `recipes.ts` (bundles the JSON recipes), `service_worker.ts` (config from storage, keepalive alarm, active-tab status for allowlisted sites only).
- `src/content/engine.ts` (find by selector and/or visible text, click, type into inputs/textareas/contenteditable with framework events, attach via DataTransfer or drop, read/query/extract, `detectChallenge` for reCAPTCHA/hCaptcha/Arkose/Turnstile/TikTok slider/"verify it's you"/checkpoint/login walls, `simplifiedDom`), `content.ts` (message handler, file reassembly).
- `recipes/`: `schema.json` + `youtube.upload_short`, `tiktok.upload`, `instagram.upload_reel`, `vyro.list_campaigns`, `vyro.submit_url`, `vyro.session_check`, `whop.list_campaigns`, `whop.submit_url`, `whop.session_check`. Every one is `"status": "UNVERIFIED"`.
- Core: `card_from_row` reads scraped platforms text ("YouTube, TikTok / Reels") and join labels ("Join free", "Joined", "$29"). `tests/test_extension_contract.py` checks the protocol version, that every recipe the core calls ships, and the upload params.
- Tests: `apps/extension/test/` (engine, challenges, simplified DOM, recipes + allowlist, runner incl. dry run and failures, bridge handshake/queue/backoff, content script file chunks).

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
- Job queue: a durable `job` table + in-process worker threads instead of Huey. Heavy work already runs in subprocesses (ffmpeg, yt-dlp, WhisperX in its own CUDA env), and an in-process queue lets `job.done` reach the supervisor's event bus without cross-process plumbing. Same limits as PLAN §17.3 (1 transcribe, 3 encodes, 2 downloads).
- Subagents: the PLAN's *editor* is split into **editor** (picks moments; PLAN §3 job, §16.3 editor row) and **cutter** (EDL edits; the "editor gets all edit ops except render_final + agenda" paragraph), and a **browser-fixer** subagent holds the browser fallback tools. Reason: the 25-tool limit (the Campaign agent alone would need 55) and prompt-injection isolation (browser pages are untrusted; the agent that reads them has no publish/submit tools).
- Analyst web access goes through the *research* subagent (Agent tool) to stay at 25 tools.
- `state` gained `get_learning_examples` (PLAN §4) and `set_tuning` (Analyst weights); `clipper` umbrella exposes `set_switch`/`set_paused` to the Director ("read + controls").
- Added tables: `review_batch`, `kv` (dry run/pause/kill switch/slots), `discord_ref` (bot message ids), `recipe_run` (Recipes tab). Toggle change log = `toggles.changed` events.
- WhisperX runs in a separate CUDA env as a subprocess (keeps torch out of the core env; matches the verified `C:\ClipperData\envs\gpucheck` setup).
- Python package lives at `core/clipper/` (import name `clipper`) instead of directly in `core/`, so the import name works with uv/hatch editable installs and pyright on Windows without symlinks.
- UI menu bar: the desktop app uses the native Windows menu (`src-tauri/src/menu.rs`); the HTML menu bar renders only in the browser build (dev, fixtures, screenshots). Both send the same command ids.
- UI.md's KPI tiles are a one-row stat strip (label, value, change, sparkline), not cards: UI.md §1 rules out dashboard tiles.
- "Stop everything" is a confirm dialog (UI.md §2); `HoldButton` exists in the gallery only.
- Settings → Tools and MCP shows the access matrix read-only: which agent may call which tool is a safety rule and stays in code (`core/clipper/agents/access.py`), reviewed like code.
- "Replay in dry-run" re-checks a recorded call against today's guard rules and re-runs it only if the tool is read-only; state-changing tools are never executed from the replay button.
- Each Clipper Chrome profile is its own `--user-data-dir` under `paths.chrome_profiles_dir` (plain Chrome, no automation or fingerprint flags).
- Earnings: payout delay shows "—" until payout dates are tracked (it was a hard-coded guess before).
- Discord: persistent components use discord.py `DynamicItem` templates on stable custom_ids instead of storing views; the bot keeps no state (message ids live in the core's `discord_ref` table). Switching something off from Discord uses the gentle defaults (finish active campaigns, keep scheduled posts); the app's dialog offers the other choices.
- Fixture mode for the UI is a static export (`clipper fixtures-export`) instead of a running fixture core, so Playwright and `dev:fixtures` need no Python.

## 7. Interfaces the local side must implement or finish
- (filled in by later work packages)

## 8. Ordered task list for the local session
1. Run section 2. Done when `just lint` and `just test` pass on Windows.

## 9. Risks and open questions for the user
- (filled in by later work packages)
