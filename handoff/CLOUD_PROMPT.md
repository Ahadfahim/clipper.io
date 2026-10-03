# Master prompt for the Claude Code cloud session

> Paste everything below the line into a Claude Code cloud session (claude.ai/code) opened on this repository.

---

You are building **Clipper.io** in a cloud session. A local Claude Code session on the user's Windows PC will take over from you afterwards. Your job is to build **everything that doesn't need the user's machine**, to a tested, working standard, and to leave a precise handoff so the local session can continue without asking questions.

## 0. Read first (in this order)
1. `CLAUDE.md`: project rules. **The "Rules that must never break" apply to you too.**
2. `PLAN.md`: architecture and source of truth. Pay special attention to §2–4 (architecture, agents, tools, guardrails), §9 (data model), §10 (repo layout), §15 (marketplaces + on/off switches), §16 (MCP servers + per-agent access), §17 (agent pool), §18 (EDL editing engine).
3. `UI.md`: the desktop UI in **Windows utility style**. Also study the prototypes: https://claude.ai/artifact/DdWqpUC3FyG5k77Ysiq1Qp ("Utility" page). If you can't open the link, UI.md §1–3 is enough.
4. `docs/ENVIRONMENT.md`: the target machine (Windows 11, RTX 5080, Python via uv, Node 24, Rust).

If PLAN.md and UI.md disagree, follow the later section and note it in the handoff.

## 1. Your environment and its limits
You're in a Linux container: **no GPU, no Windows, no user Chrome profile, no logins, no secrets, possibly restricted network.**
- **Never** call real external services: no YouTube/TikTok/Instagram/Vyro/Whop/Discord network calls, no yt-dlp downloads, no real Claude agent runs. Use fakes, fixtures and recorded data.
- Generate test media yourself with ffmpeg (`testsrc2` + `sine`, plus burned-in text for OCR tests), at most a few seconds each, committed under `tests/fixtures/` (keep the total under 5 MB).
- GPU/Windows-only code (WhisperX on CUDA, NVENC, Tauri build, Windows Credential Manager, Chrome extension in a real profile) must be written **behind interfaces** with a CPU or fake implementation you *can* test. Mark the GPU/Windows implementations `# LOCAL-VERIFY` and list them in the handoff.
- **Don't guess library APIs.** Use docs (context7 MCP if it's available, otherwise web docs if allowed, otherwise read the installed package's source and type stubs). This especially applies to `claude-agent-sdk` (Python), `mcp`/FastMCP, discord.py 2.x, Tauri v2, Chrome MV3 and TanStack.
- Agents must run on the user's **Claude plan login**: never add API-key billing, `$` cost tracking or `max_budget_usd`. Strip `ANTHROPIC_API_KEY` from agent subprocess environments, and test that it's stripped.

## 2. Work packages (in priority order; finish each with passing tests before starting the next)

Commit after every work package with a clear message. **Create `HANDOFF.md` right after WP0 and update it at the end of every work package**, so a valid handoff exists even if the session ends early.

### WP0 — Repo scaffold and CI
- Layout exactly as PLAN §10: `core/` (Python package `clipper`), `apps/desktop` (Tauri v2 + React 19 + Vite + TS), `apps/bot` (discord.py), `apps/extension` (Chrome MV3, TS), `config/`, `tests/`, `docs/`.
- Python: **uv** workspace, Python 3.12, ruff, pyright (strict on `core/`), pytest. JS: **pnpm** workspace, TypeScript strict, eslint, vitest, Playwright.
- `config/settings.example.toml` covering every setting PLAN mentions (slots, caps, switches, usage pacing, paths, Discord channel ids, retention).
- A `justfile` (or Makefile) with: `setup`, `lint`, `test`, `dev-api`, `dev-ui`, `dev-bot`, `doctor`.
- GitHub Actions CI on ubuntu: lint + typecheck + tests for Python and JS + UI build + Playwright screenshot tests.
- **Done when:** CI-equivalent commands pass locally in your container.

### WP1 — Data layer and event bus
- SQLModel models for **every table in PLAN §9** (including `edl`, `edit_op`, `agenda_item`, `note`, `agent_request`, `lease`, `wakeup`, `question`, `lesson`, `usage_window`, `marketplace`, `platform`), plus the first Alembic migration. SQLite in WAL mode.
- **Single writer queue** for all writes (PLAN §17.3), plus a read API.
- In-process **event bus** with persisted `event` rows and typed events (`job.done`, `review.shipped`, `post.live`, `campaign.taken`, `toggles.changed`, `note.added`, `user.chat`, …).
- Leases (campaign / clip / chrome-profile) with expiry, and posting-cap checks done atomically under the lock.
- **Done when:** tests cover migrations, the writer queue under concurrency, leases and the cap race.

### WP2 — Guardrails (do this before tools and agents)
- `core/agents/hooks.py`: `PreToolUse` guard checks as **pure, unit-tested functions**:
  - Publishing requires a human `approved` review
  - Posting caps per account, plus warm-up caps
  - Minimum gap between posts
  - Marketplace / social / account switches
  - Download source whitelist from the ClipSpec
  - Browser domain allowlist, limited to what's switched on
  - `submit_post_url` only for our own live posts
  - Dry-run mode (publish/submit tools return simulated success and log what they would have done)
  - Kill switch
  - `max_turns`
- Every rejection returns a clear reason and is logged to `agent_event` as `blocked`.
- **Done when:** there's a table-driven test for every rule, including the "a note can't override a rule" case.

### WP3 — MCP tool servers (in-process SDK servers + stdio entry points)
Implement the servers in PLAN §16.1: `state`, `supervisor`, `notify`, `memory`, `agenda`, `edit`, `media`, `review`, `publish`, `marketplace`, `browser`, `trends`, `insights`, plus the `clipper` umbrella server.
- Use typed input schemas, set `readOnlyHint` on read-only tools, and **keep results small** (IDs, paths, pages; transcripts paged).
- **Adapters behind interfaces, each with a fake:**
  - `MarketplaceAdapter` (Vyro, Whop; PLAN §15.1)
  - `PublishAdapter` (YouTube, TikTok, Instagram, X)
  - `BrowserBridge` (the Companion extension's WebSocket protocol)
  - `Transcriber` (WhisperX on CUDA = LOCAL-VERIFY; also a fake, and a tiny CPU path if one is practical)
  - `Encoder` (NVENC = LOCAL-VERIFY, libx264 = tested)
- `insights` runs on a **read-only** SQLite connection; test that writes fail.
- `notify.ask_user` creates a `question` row, emits an event, and the answer resumes the session (tested with the fake runner).
- Per-agent tool access exactly as PLAN §16.3, with **at most 25 tools per agent**. Write a test that asserts the matrix.

### WP4 — EDL editing engine (PLAN §18)
- Pydantic `EDL` schema; operations (`trim`, `split`, `delete_range`, `remove_silences`, `remove_fillers`, `set_layout`, `set_camera_keyframes`, caption ops, `emphasize`, `set_hook`, overlays, audio, `make_variant`, `undo`). Each operation is pure, recorded as an `edit_op`, and broadcast as an event.
- **Renderer:** EDL → ffmpeg filtergraph (cuts, crops with eased keyframes, split-screen, blurred-background fit, punch-in zoom, overlays, loudness normalization). Proxy and final profiles. Encoder is pluggable (libx264 here; NVENC flagged LOCAL-VERIFY).
- **Captions:** an ASS generator with word timing, emphasis styling, phrase line breaks, **platform safe zones** (TikTok, Shorts, Reels), and face-avoidance using a supplied face box.
- **Automatic QA** as pure functions: speech starts within 0.5s, face in frame, captions vs. safe zones, black/frozen frames, clipping, silence ratio, length vs. spec.
- **Done when:** golden tests render the synthetic fixtures through the CPU path and check durations, dimensions, loudness and caption files.

### WP5 — Supervisor and agent runtime (PLAN §3, §17)
- **Slot pool** (default 4) running agent sessions concurrently via `claude-agent-sdk` (`ClaudeSDKClient`).
  - Priority queue P0–P3, with one slot always reserved for P0.
  - The pool shrinks when usage is high (the usage source is an interface; the fake is driven by tests).
  - On rate-limit errors: pause, then auto-resume at the reset time.
- **Event → session resume** mapping (one session per campaign, `resume=<session_id>`). Events that arrive while a session is busy are merged.
- **Plumbing:** wakeups (`wake_me`), watchdog for stuck campaigns, kill switch, dry-run.
- **Agent definitions** for Scout, Campaign, Analyst and Director, plus subagents (brief-reader, research, editor, qa-checker, copywriter):
  - `setting_sources=[]`
  - Built-in tools off, so only our MCP tools are available
  - Per-role `effort` and `max_turns`
  - Model `claude-opus-5-5`
- **Write the real system prompts** in `core/agents/prompts/*.md`. They should be specific, grounded in the tools, include the untrusted-content rules, and be short enough to cache.
- **Testing:** use a `FakeAgentRunner` that replays scripted tool-call sequences. Write one end-to-end test: campaign taken → spec → download → analysis → moments → renders → review batch → shipped → schedule → post.live → submit, entirely on fakes and in dry-run.

### WP6 — API
- FastAPI REST + WebSocket event stream (`agent.event`, `job.progress`, `clip.updated`, `review.decided`, `post.status`, `alert`, `edit.op`, `agenda.updated`), bound to 127.0.0.1 only.
- Generate a typed TS client from OpenAPI into `apps/desktop/src/api/`.
- A **fixture mode** that serves realistic seeded data, so the UI can be developed without agents.

### WP7 — Desktop UI (web layer; must match UI.md and the Utility prototypes)
- `tokens.css` with the utility-style light and dark themes and the accent variable (UI.md §1). Segoe UI Variable falls back to the system font; use Cascadia Mono for numbers.
- **Shell:** menu bar, toolbar (switch checkboxes), tree navigation, resizable panes (`react-resizable-panels`), docked output panel with tabs, status bar, command box (`cmdk`, `>` for the Director).
- **Screens:** Overview, Agents (slot board + live transcript + Director chat), Campaigns (grid + detail), Library (grid + clip detail), **Review** (keyboard A/R/E/C/Space/arrows), **Edit** (live agent presence, timeline, history with undo, agenda + notes), Publishing (calendar lanes, accounts, recipes), Earnings, **Settings dialog** (with the switch-off confirmation flows from PLAN §15.2), first-run wizard, and a `/dev/gallery` route.
- Wired to the API with TanStack Query; live updates over WebSocket.
- **Playwright screenshot tests** of every screen in dark and light at 1280×800 and 1920×1080. Commit the screenshots under `docs/screenshots/`.
- **Tauri (`src-tauri/`):**
  - Write the full config and Rust code: native decorations, Mica (window-vibrancy), native menu bar, tray, notifications, autostart, single-instance, pop-out windows, Python sidecar launch.
  - Run `cargo check` if the Linux deps are available; otherwise mark it LOCAL-VERIFY.
  - Don't try to produce a Windows build.

### WP8 — Discord bot
- discord.py 2.x with persistent views (stable `custom_id`s):
  - Campaign cards (Take / Skip)
  - Forum batch posts with clip messages (Approve / Reject with reason / Edit caption modal / Re-cut modal / platform select)
  - Pinned batch summary (Ship approved / Approve all ≥ N / Reject rest)
  - `ask_user` questions
  - `/clipper toggle` command
  - `#control` relay to the Director
- Restricted to the `@Clipper` role. Talks to the core over the internal API.
- **Done when:** tests use mocked interactions; there's no live token.

### WP9 — Companion extension
- MV3 + TypeScript:
  - Service worker with the WebSocket bridge (pairing token, reconnect, one action at a time per profile)
  - Content scripts
  - **Recipe engine:** a step runner covering navigate / wait_for / query / click / type / attach_file (fetches the file from 127.0.0.1 and attaches it with DataTransfer) / read_text / screenshot. Every failure returns a screenshot plus a simplified DOM.
- Recipe JSON schema plus **draft** recipes for `youtube.upload_short`, `tiktok.upload`, `instagram.upload_reel`, `vyro.list_campaigns`, `vyro.submit_url`, `whop.list_campaigns`, `whop.submit_url`.
  - Mark every selector `UNVERIFIED` (you can't see the real sites).
  - Challenge detection (login / CAPTCHA / verification screens) → pause the account and alert. **Never** attempt to solve or bypass a challenge.
- **Done when:** the engine is unit-tested with jsdom fixtures.

## 3. Ground rules
- Follow CLAUDE.md and PLAN.md. If you have to deviate, do it deliberately and record it under "Decisions and deviations" in HANDOFF.md.
- Prefer finished and tested over broad and half-done. If time runs short, stop at a clean work-package boundary.
- No secrets in the repo. No real accounts. No anti-bot or CAPTCHA tooling of any kind.
- Keep commits small and conventional (`feat(core): …`). Work on a branch named `cloud/foundation` (or the branch the environment gives you), push it, and open a **draft PR** if you can.

## 4. Required output: `HANDOFF.md` (repo root)
Use **exactly** this structure. The local session reads it as its instructions.

```markdown
# HANDOFF — cloud → local

## 1. Snapshot
- Branch / PR:
- Last commit:
- Work packages: WP0 ✅/🟡/❌ … WP9 (one line each, with a one-line summary)
- Test status: <command> → <result> (per suite)

## 2. How to run (on Windows)
Exact commands in order: install, migrate, seed fixtures, run API, run UI in fixture mode, run tests.

## 3. What was built
Per work package: main files/modules, public interfaces, notable design choices.

## 4. LOCAL-VERIFY list
Every place that needs the user's machine, as a table: file:line · what · how to verify · expected result.
(At minimum: CUDA/WhisperX, NVENC encoder, Tauri build + native menu/tray/Mica, Python sidecar packaging, extension in the Chrome profile + pairing, each upload/marketplace recipe's selectors, live Discord bot, Claude plan login + real agent run, Windows Credential Manager.)

## 5. Known gaps and TODOs
Ordered by importance, with file paths.

## 6. Decisions and deviations from PLAN.md / UI.md
What, why, and impact.

## 7. Interfaces the local side must implement or finish
Signatures and where they plug in.

## 8. Ordered task list for the local session
Numbered, concrete, each with a "done when" line. Start with environment setup and the LOCAL-VERIFY items that unblock the most.

## 9. Risks and open questions for the user
Only things the user must decide.
```

## 5. Final message of your session
End with **only** this block, filled in, so the user can paste it straight into the local Claude Code session:

```
Continue Clipper.io from the cloud handoff.
Branch: <branch>   PR: <url or "none">   Last commit: <sha>
1. git fetch && git checkout <branch>
2. Read HANDOFF.md fully, then CLAUDE.md.
3. Run section 2 "How to run" and report any failures before changing code.
4. Work through section 8 in order, starting with the LOCAL-VERIFY items in section 4.
Highest-priority item: <one line>
```
