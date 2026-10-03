# Clipper.io — System Plan (v2: agent-driven)

Automated clipping operation for the **Vyro** and **Whop Content Rewards** clipping marketplaces (each can be switched on or off), **run end-to-end by Claude agents** launched as Claude Code subprocesses through the **Claude Agent SDK**. The agents find campaigns, pick the good ones, read every brief, download the authorized sources, find and cut viral clips, send them to Discord for review, publish the approved ones to whichever socials are switched on (Shorts / TikTok / Reels / X), submit the post URLs back to the marketplace, and track earnings. A Windows desktop dashboard shows everything the agents do and lets you step in at any point.

> **Key constraint:** both marketplaces pay per 1,000 verified views on posts made from *our own* social accounts. The live post URLs must be submitted back to the campaign. **Vyro** has no public API (≈$3 CPM, $1k cap per clip). **Whop** campaigns vary ($0.20–$6 CPM) and Whop has a beta bounty-submission API. Both are reached through the browser by default (§15). Check each marketplace's ToS on automation before Phase 4.

---

## 1. Design principles

1. **Claude is in charge.** Each Claude Code subprocess decides what to do next: which campaigns, which moments, when to re-cut, what to post and when. No hard-coded state machine decides that.
2. **Tools do the work, rules are enforced in code.** Agents act only through our own MCP tools (download, transcribe, render, post, submit). Rules that must never be broken (no publishing without human approval, posting caps, usage limits, only whitelisted sources) are checked **in code, in a `PreToolUse` hook**, not just written in the prompt.
3. **The database holds all state, sessions are temporary.** Agents read and write state through tools. A session can crash, run out of context or be killed, and the next one picks up from the DB.
4. **One session per campaign, resumed on events.** Nobody holds a session open while waiting hours for a human or a GPU job. The agent finishes its turn; when something happens (download done, review submitted, post went live), the supervisor **resumes** that campaign's session with a message describing the event.
5. **Heavy work runs on the local GPU.** Transcription, face tracking and encoding run on the RTX 5080 as background jobs; Claude's tokens go to judgment, not to video processing.
6. **You can see and stop everything.** Every agent message, tool call and dollar spent streams to the dashboard. There's a kill switch, a dry-run mode, and per-session and daily budget caps.

---

## 2. Architecture

```
┌──────────────────────── Windows Dashboard (Tauri v2 + React) ────────────────────────┐
│ Home │ Agents (live console + chat) │ Campaigns │ Library │ Review │ Publishing │ Earnings │ Settings │
└───────────────────────────────────┬──────────────────────────────────────────────────┘
                                    │ REST + WebSocket (127.0.0.1)
┌───────────────────────────────────▼──────────────────────────────────────────────────┐
│ clipper-core (Python 3.12, FastAPI, Tauri sidecar)                                   │
│                                                                                      │
│  SUPERVISOR  ── small and deliberately simple: triggers + event bus + guardrails     │
│   • cron triggers (scout every 15m, analyst daily)                                   │
│   • events (job.done, review.shipped, post.live, campaign.taken, user.chat)          │
│   • starts / resumes agent sessions via claude-agent-sdk  ──────────┐                │
│   • budget accounting, kill switch, watchdog for stuck campaigns    │                │
│                                                                     ▼                │
│   ┌──────────────── Claude Code subprocesses (Agent SDK) ────────────────────┐       │
│   │ Scout agent      · Campaign agent (1 session per campaign)               │       │
│   │ Analyst agent    · Director (chat with you)                              │       │
│   │ subagents: brief-reader · editor · qa-checker · copywriter               │       │
│   └───────────────┬──────────────────────────────────────────────────────────┘       │
│                   │ MCP tool calls (in-process SDK servers)                          │
│   ┌───────────────▼──────────────────────────────────────────────────────────┐       │
│   │ state · marketplace · media · review · publish · browser · supervisor
│   │ notify · memory · trends · insights          (full list + access: §16)                        │       │
│   │      + PreToolUse guard hooks (approval, caps, whitelist, dry-run)       │       │
│   └───────────────┬──────────────────────────────────────────────────────────┘       │
│                   │ enqueue                                                          │
│   GPU WORKER (Huey, SQLite) ── yt-dlp · WhisperX · PySceneDetect · MediaPipe · NVENC │
│   SQLite (SQLModel + Alembic) ── all state                                           │
└───────────────────────────────────┬──────────────────────────────────────────────────┘
                                    │ internal API + DB
┌───────────────────────────────────▼──────────────────────────────────────────────────┐
│ clipper-bot (discord.py 2.x, persistent button views)                                │
│   #control (talk to Director) · #campaigns · #clip-review (forum) · #published · #alerts │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Why the supervisor still exists
The Agent SDK runs one session at a time per subprocess and has no clock or inbox. Something has to (a) wake agents on a schedule, (b) turn outside events into session resumes, (c) pace agent work to fit your Claude plan's usage limits and enforce the kill switch, and (d) restart crashed sessions. That's the supervisor's whole job. It **never decides** anything about campaigns, clips or posts.

### Tech choices

| Layer | Choice | Why |
|---|---|---|
| **Agent runtime** | **`claude-agent-sdk` (Python)** → Claude Code CLI subprocess | Agent loop, tools, subagents, hooks, sessions/resume, per-session usage reporting built in |
| Agent model | **Claude Opus 5.5** (`claude-opus-5-5`), effort set per agent/subagent | Strongest judgment; tune depth per role via `effort` |
| Agent tools | In-process SDK MCP servers (`create_sdk_mcp_server` + `@tool`) | Same Python process, direct DB access, typed inputs; also exposed over stdio for Claude Desktop |
| Desktop shell | Tauri v2 (Rust installed) | **Installed Windows software** (MSI/EXE, ~10 MB + Python sidecar), native window frame and menus, tray icon, starts with Windows. Not a web app: no browser, no server you visit |
| UI | React + Vite + TypeScript + Tailwind + shadcn/ui + TanStack Query | |
| Backend | Python 3.12, uv, FastAPI | All the video/AI tooling is in Python |
| GPU jobs | Huey with SQLite storage | Background workers; nothing extra to install |
| DB | SQLite (WAL) + SQLModel + Alembic | |
| **Browser "hands"** | **Clipper Companion**: our own Chrome extension (MV3) in a dedicated Chrome profile, connected to clipper-core over a localhost WebSocket. Playwright over CDP as a backup | One mechanism for Vyro, Whop, YouTube Studio, TikTok Studio, Instagram and X. No platform APIs, no audits, no quotas. See §5 |
| Media | yt-dlp, WhisperX large-v3 (CUDA), PySceneDetect, librosa, MediaPipe, ffmpeg h264_nvenc, libass captions | |
| Discord | discord.py 2.x | Buttons, modals, forum posts, persistent views |
| Secrets | Windows Credential Manager via `keyring` | |

> **RTX 5080 note:** pin PyTorch **CUDA 12.8+** (`cu128`) wheels, otherwise WhisperX silently falls back to CPU.

> **Auth: your Claude plan, not API billing.** The agents run through the Claude Code CLI subprocess using **your logged-in Claude account** (`claude` login). The supervisor **removes `ANTHROPIC_API_KEY` from every subprocess's environment** so it can never silently switch to per-token API billing, and `clipper doctor` checks which login is active. There's no money to track; the limit is your **plan's usage limits**, so agent work is paced to fit them (§4 "Usage limits").

---

## 3. The agents

All agents run with **`setting_sources=[]`** (your personal Claude Code settings, CLAUDE.md files and plugins don't leak in), a **custom system prompt**, **built-in tools turned off** (no Bash, no file writes; only our MCP tools), and `max_turns`.

| Agent | Trigger | Session | Effort | Job |
|---|---|---|---|---|
| **Scout** | Every 15 min | New each run | `low` | Read campaigns from every **enabled** marketplace (Vyro, Whop), update the DB, score new ones, post cards to `#campaigns` (or take them automatically in `auto` mode) |
| **Campaign** | `campaign.taken`, then resumed on every event for that campaign | **One per campaign, resumed** (`resume=<session_id>`) | `high` | Owns the campaign start to finish: brief → spec → sources → moments → renders → review → schedule → submit |
| ↳ *brief-reader* (subagent) | Called by Campaign | — | `high` | Turns the full campaign page into a `ClipSpec` |
| ↳ *editor* (subagent) | Called by Campaign | — | `high` | Reads transcript + signals, returns ranked moments with hook/payoff |
| ↳ *qa-checker* (subagent) | Called by Campaign | — | `low` | Checks rendered clips against the spec and keyframes |
| ↳ *copywriter* (subagent) | Called by Campaign | — | `medium` | Titles, captions and hashtags per platform, including the spec's required text |
| **Analyst** | Daily, 09:00 | New each run | `medium` | Pulls metrics, updates learning weights and example clips, posts a daily report, flags weak campaigns to drop |
| **Director** | You (dashboard chat or `#control`) | Persistent conversation (`ClaudeSDKClient`) | `high` | Your interface: "skip campaign X", "5 more clips from source Y", "why was clip 31 rejected?", "pause TikTok" |

Subagents keep the Campaign session's context small: long transcripts are read inside the *editor* subagent, which returns only the moment list.

### Example Campaign lifecycle (events → resumes)
```
campaign.taken        → START   read brief (brief-reader) → save spec → queue downloads → end turn
job.done(download)    → RESUME  queue analysis jobs → end turn
job.done(analysis)    → RESUME  editor → moments → queue renders → end turn
job.done(render)×N    → RESUME  qa-checker → copywriter → review.post_batch → end turn
review.shipped        → RESUME  read decisions → publish.schedule per account caps → end turn
post.live             → RESUME  marketplace.submit_post_url → end turn
campaign.ending       → RESUME  final submissions, clean up, summarize → close session
```
If a campaign gets no event for a while, the watchdog resumes it with "status check: what's blocked?"

---

## 4. Tool surface (MCP servers the agents use)

Core servers are below. The complete list, including `supervisor`, `notify`, `memory`, `trends`, `insights`, the third-party servers and which agent gets what, is in **§16**.

| Server | Tools (examples) | Notes |
|---|---|---|
| `clipper-state` | `get_campaign`, `list_campaigns`, `update_campaign`, `save_spec`, `save_moments`, `log_note`, `get_learning_examples` | The only way agents change state |
| `marketplace` | `list_campaigns(market?)`, `get_campaign_page`, `join_campaign`, `submit_post_url`, `get_submission_status`, `get_earnings`, `snapshot_page` | One tool server that passes each call to the right marketplace adapter (Vyro, Whop) based on the campaign. Disabled marketplaces are rejected in code. Uses the Companion extension; reads each site's own JSON calls when possible, page text otherwise (§15) |
| `browser` | `snapshot(tab)` (screenshot + simplified DOM), `click`, `type`, `attach_file`, `navigate` | Low-level fallback: when a recipe breaks, the agent looks at the page and finishes the step itself, then the fix gets written back into the recipe |
| `media` | `download(url)`, `analyze(source)`, `get_transcript(source, from, to)`, `get_signals(source)`, `render(moment, layout, caption_style)`, `get_keyframes(clip)`, `job_status(id)` | Long operations return a `job_id` right away; the agent gets resumed with `job.done` |
| `review` | `post_batch(clips)`, `get_batch_status`, `get_decisions` | Goes through clipper-bot, so buttons, forum posts and modals work. The plain Discord MCP can't receive button clicks |
| `publish` | `list_accounts`, `schedule_post(clip, account, time, copy)`, `cancel_post`, `get_post_metrics` | Browser upload recipes for YouTube Studio / TikTok Studio / Instagram, run by the Companion extension. Metrics are read from the public post pages with yt-dlp, no API needed |

### Guardrails (in code, `PreToolUse` hooks + tool code)
- `publish.schedule_post` **denied** unless the clip has an `approved` review row created by a human (Discord or dashboard)
- Posting caps per account per day and minimum gap between posts (defaults: 3/day for new accounts, ramping up slowly; at least 2h apart)
- Any login page, CAPTCHA or verification screen → **pause that account** and alert `#alerts`; you deal with it by hand in the Clipper Chrome window
- `media.download` only for URLs on the campaign spec's source whitelist
- `marketplace.submit_post_url` only for posts we made that are live, on a marketplace that's switched on
- **Toggles enforced in code:** any tool call for a disabled marketplace or social platform is denied (§15)
- **Dry-run mode:** publish and submit tools pretend to succeed and only log what they would have done
- **Kill switch:** the dashboard interrupts all running sessions and pauses all triggers
- **Usage limits (Claude plan):**
  - `max_turns` per session, and a daily cap on agent runs, so one runaway session can't use up the plan.
  - The supervisor tracks usage in the current usage window, from the SDK's usage reports and its rate-limit messages.
  - **When usage gets high, work is done in priority order:** user-facing and money-critical work first (review batches, scheduled posts, URL submissions), then campaign production, with Scout and Analyst runs slowed or skipped.
  - **On a rate-limit error:** sessions are paused and automatically resumed after the reset time, with a notice in `#alerts`. GPU jobs and uploads already queued keep running.
- Every tool call and result is written to `agent_event` for the audit trail and the live console
- **Untrusted content:** campaign briefs, marketplace pages and platform pages are written by third parties and may contain prompt injections. The *brief-reader* subagent has **no tools that change anything** (it only outputs a `ClipSpec`). The Campaign agent works from the spec, not the raw brief text. `browser` tools only work on a domain allowlist (vyro, whop.com, studio.youtube.com, tiktok.com, instagram.com, x.com), further limited to what's switched on. The hard checks above apply no matter what the agent decides

---

## 5. Browser automation: Clipper Companion extension

No YouTube/TikTok/Instagram APIs. All platform work (Vyro, Whop, uploads, captions, post URLs) runs in a **real Chrome window you're logged into**, driven by our own extension.

### Why an extension (vs. Playwright-launched browser)
| | Companion extension (**primary**) | Playwright over CDP (**backup**) |
|---|---|---|
| Browser | Your real Chrome, a dedicated "Clipper" profile, normal window | Same profile, attached through Chrome's remote-debugging connection |
| Looks like | A normal user session | A browser under remote control (debug port open, automation flags) |
| File upload | Gets the clip from `127.0.0.1` as a file and attaches it to the page's upload field | `set_input_files(path)` |
| Logins | You log in once; normal cookies, 2FA done by you | Same |
| Visibility | You can watch it work, and take over any time | Same |

### How it works
```
clipper-core ── WebSocket (127.0.0.1, pairing token) ── Companion (MV3 service worker)
                                                          ├─ content scripts per site: vyro · whop · youtube studio · tiktok studio · instagram · x
                                                          ├─ generic actions: navigate · wait_for · query · click · type · attach_file · read_text · screenshot
                                                          └─ recipes: step lists per site/action
```
- **Recipes** are short, versioned JSON/TS step lists, e.g. `youtube.upload_short`: open the Studio upload dialog → attach file → wait for processing → fill title/description → set "not made for kids" → set visibility (public or schedule time) → publish → **read the post URL** from the confirmation dialog.
- `tiktok.upload`: TikTok Studio upload page → attach → caption with hashtags → cover frame → schedule/post → get the URL from the profile's newest video.
- `instagram.upload_reel`, `vyro.list_campaigns`, `whop.list_campaigns`, `whop.submit_url`, `x.post_video`, and so on, work the same way.
- **When a recipe breaks** (site redesign), the step fails with a screenshot + simplified DOM. The Campaign agent gets them through the `browser` tools, finishes the step by looking at the page, and logs what changed. Recipe selectors are then updated (by you, or by asking the Director to patch them).
- **Pacing:** realistic delays between steps, one upload at a time per account, posting caps per account (§4).
- **Several accounts:** one Chrome profile per account. Each gets its own Companion pairing and is shown on the Publishing page.

### Boundaries (deliberate)
- **Only your own accounts.** The system automates what you could do by hand.
- **No anti-bot workarounds.** No CAPTCHA-solving services, no browser fingerprint spoofing, no proxy rotation. If a platform challenges the session, that account pauses and you handle it by hand. Fighting detection is how accounts get permanently banned, and these accounts are where the money comes from.
- Both YouTube's and TikTok's terms restrict automated access outside their official APIs. Running this is a **risk to the accounts** that you're choosing to take. The caps and pacing are there to keep that risk low, not to hide anything.

---

## 6. Media engine (what the `media` tools run)

> Upgraded in **§18**: every clip is an editable JSON timeline (EDL) with live preview, and only approved clips get a final render. The steps below are what the engine runs underneath.

- **Acquire:** yt-dlp, best ≤1080p, plus subtitles, chapters and the **"most replayed" heatmap**. Skips files already downloaded (by hash). Deletes sources N days after the campaign ends
- **Analyze (GPU):** WhisperX word timestamps + speaker labels; PySceneDetect shot cuts; librosa loudness/energy and laughter peaks; face tracks per shot
- **Signals returned to the editor:** heatmap peaks, energy spikes, topic changes, plus the transcript in chunks the agent can page through
- **Render:**
  - Cut accurately; snap the start and end to sentence and shot boundaries
  - Layout per shot: speaker-following crop / stacked split-screen for two speakers / blurred-background fit for wide shots
  - Animated word-by-word ASS captions (3–4 styles, keyword highlight)
  - Hook text overlay for the first ~2 seconds, plus any branding/@ the spec requires
  - Normalize to −14 LUFS; NVENC encode at 1080×1920
  - Also outputs a thumbnail and a ~9.5 MB Discord preview (2-pass encode to a target size)
- **Quality bar, not quantity:** the editor keeps every moment above a threshold the Analyst tunes over time, never a fixed count

---

## 7. Discord

| Channel | Purpose |
|---|---|
| `#control` | Talk to the Director in plain English; it replies in a thread |
| `#campaigns` | Campaign cards: score, CPM, budget left, deadline, the agent's reasoning → **Take / Skip / Details** |
| `#clip-review` (**forum**) | One forum post per campaign × source batch. Tags `pending` / `in review` / `shipped` |
| `#published` | Log of each post with its link, later updated with views |
| `#alerts` | Login expired, quota hit, budget cap reached, stuck campaign, failed tool calls |

**Clip message:** preview video + embed (score, length, source timestamp, hook, captions per platform, the agent's reasoning) with **✅ Approve · ❌ Reject (reason) · ✏️ Edit caption (pop-up form) · 🔁 Re-cut (pop-up form: ±start/end, layout)** and a **platforms dropdown**. A re-cut is sent to the Campaign agent as an event, and the new render replaces the preview in place.

**Batch summary (pinned):** `Reviewed 7/12 · ✅5 ❌2` with **🚀 Ship approved · ✅ Approve all ≥80 · ⏭ Reject rest**. "Ship" sends the `review.shipped` event, which resumes the Campaign agent. Optional timeout rule. Only the `@Clipper` role can press buttons.

Review state lives in SQLite; Discord and the dashboard Review page show the same data.

---

## 8. Windows dashboard

| Page | Contents |
|---|---|
| **Home** | Earnings and views today, active campaigns, GPU/queue status, Claude usage (current window + reset time), alerts, **kill switch**, dry-run toggle |
| **Agents** | Live console per session: agent messages, tool calls + results, subagent activity, turns and tokens so far. Session list (running / waiting-on-event / done) with **Interrupt / Resume / Nudge**. **Director chat** panel |
| **Campaigns** | Table with score, CPM, budget, deadline, status; details panel with the brief, the agent's spec (editable) and the campaign's session timeline |
| **Library** | Clip player, transcript with a timeline of the source window, the agent's reasoning, version history |
| **Review** | Same queue as Discord with keyboard shortcuts (A / R / E / ←→ / Space) |
| **Edit** | Live view of the agent editing a clip (violet playhead + status), multi-track timeline, history with undo, **Agenda** (agent's plan + your notes), take over / hand back (§18.4) |
| **Publishing** | Calendar per account, drag to reschedule, caps, connection status |
| **Earnings** | $ and views per campaign/clip/platform/marketplace, earnings per clip and per GPU hour |
| **Settings** | Accounts/OAuth, Discord, automation mode, usage pacing and posting caps, model/effort per agent, editable agent prompts, caption styles, storage/retention, **Marketplaces and socials toggles**, marketplace re-login |

Tray icon, optional start with Windows, toast notification when a batch is ready for review.

---

## 9. Data model (core tables)

```
campaign(id, marketplace, external_id, title, brand, cpm, budget_total, budget_left, cap_per_clip, platforms,
         deadline, rules_raw, score, score_reason, status, spec_json, session_id, agent_turns)
source(id, campaign_id, url, path, hash, duration, heatmap_json, status)
analysis(source_id, transcript_path, scenes_json, energy_path, faces_path)
moment(id, source_id, start, end, hook, payoff, scores_json, final_score, reason)
clip(id, moment_id, version, path, preview_path, layout, caption_style, qa_json, status)
review(clip_id, decision, reason, platforms, captions_json, reviewer, decided_at, via)
post(id, clip_id, account_id, platform, scheduled_at, posted_at, url, status)
submission(post_id, campaign_id, marketplace, submitted_at, external_status, tracking_ends)
marketplace(id, name, enabled, mode, session_ok, last_scout, settings_json)    -- vyro, whop
platform(id, name, enabled, settings_json)                                     -- youtube, tiktok, instagram, x
metric(post_id, ts, views, likes, comments, shares, earnings)
account(id, platform, handle, chrome_profile, niche_tags, warmup_started, daily_cap, min_gap_min, status)
job(id, kind, input_json, status, progress, result_json, campaign_id)
agent_session(id, sdk_session_id, role, campaign_id, status, turns, input_tokens, output_tokens, started, last_active)
agent_event(id, session_id, ts, type, tool, input_json, output_json, tokens)     -- audit + live console
usage_window(id, started, resets_at, tokens, sessions, rate_limited)      -- plan-usage pacing
wakeup(id, session_id, due_at, reason, status)                            -- supervisor.wake_me
question(id, session_id, text, options_json, answer, answered_by, via, timeout_at)   -- notify.ask_user
lesson(id, scope, entity_id, note, evidence_ref, created_by, created_at, active)     -- memory
edl(clip_id, version, json, locked_by, updated_at)                         -- editable clip timeline
edit_op(id, clip_id, version, actor, op, args_json, reason, ts, undone)     -- live edit history
agenda_item(id, scope, scope_id, session_id, text, status, result, ord)     -- agent plan
note(id, scope, scope_id, text, author, created_at, acked_by_session, response, pinned)
agent_request(id, priority, kind, campaign_id, payload, status, slot, queued_at, started_at)
lease(resource, holder_session, expires_at)                               -- campaign / clip / profile locks
event(id, type, entity, entity_id, payload, ts, handled_by_session)
```

---

## 10. Repository layout

```
Clipper.io/
├─ PLAN.md
├─ apps/
│  ├─ desktop/              Tauri v2 + React dashboard
│  ├─ bot/                  discord.py bot
│  └─ extension/            Clipper Companion (MV3, TypeScript): service worker, content scripts, recipes
├─ core/                    Python package `clipper`
│  ├─ supervisor/           triggers, event bus, session runner, usage pacing, watchdog, kill switch
│  ├─ agents/
│  │  ├─ prompts/           scout.md · campaign.md · analyst.md · director.md · subagents/*.md
│  │  ├─ definitions.py     ClaudeAgentOptions + AgentDefinition per role
│  │  └─ hooks.py           PreToolUse/PostToolUse guardrails + event logging
│  ├─ tools/                SDK MCP servers: state · marketplace · media · review · publish · browser ·
│  │                         supervisor · notify · memory · trends · insights · clipper (umbrella)
│  ├─ browser/              Companion WebSocket bridge, recipe runner, CDP fallback
│  ├─ media/                download, transcribe, scenes, energy, faces, reframe, captions, encode
│  ├─ worker/               Huey GPU tasks
│  ├─ api/                  FastAPI + WebSocket for the dashboard
│  └─ db/                   models, migrations
├─ data/                    (gitignored) sources, work, clips, previews
├─ config/                  settings.example.toml
└─ tests/                   tool unit tests, golden-clip fixtures, recorded agent runs
```

---

## 11. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0. Foundations** | uv workspace, CUDA 12.8 torch check, DB + migrations, FastAPI skeleton, Tauri app launching the sidecar, **supervisor + Agent SDK "hello agent"** that calls one `clipper-state` tool and streams to the Agents console. **Companion extension skeleton** paired over WebSocket, plus a **YouTube Studio upload test** (one clip uploaded *unlisted* and its URL captured) | `clipper doctor` green; an agent run on your Claude login (no API key) is visible live in the app; the upload test works end to end |
| **1. Media tools + Campaign agent (manual input)** | `media` + `state` tools, GPU worker, editor/qa/copywriter subagents. You paste a source URL + brief text → the agent produces clips | 10 test videos produce clips you'd post; plan usage per source measured (how many sources fit in a usage window); the **quality test set** (§14) exists. Then **2 weeks of posting by hand** to measure real views before Phase 4 |
| **2. Review loop** | clipper-bot + `review` tools + event→resume. Dashboard Review page | Clips get reviewed in Discord, the agent resumes on ship, re-cuts work |
| **3. Publishing** | Upload recipes (YouTube Studio → TikTok Studio → Instagram) + `publish` tools + guard hooks + dry-run + post-URL capture + yt-dlp metrics | Approved clips go live on schedule; unapproved posts are impossible (tested) |
| **4. Marketplaces** | Marketplace adapter interface + **Vyro** adapter, then **Whop** adapter; Scout across enabled marketplaces; campaign cards; URL submission; earnings scraping; toggles UI | For each marketplace: campaign discovered → URL submitted, with only the review step manual; turning a marketplace off stops it cleanly |
| **5. Director, Analyst, polish** | Director chat (dashboard + `#control`), daily Analyst + learning loop, Earnings, tray, MSI installer | Runs daily without a terminal; you steer it by chatting |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Agent does something it shouldn't (posts a bad clip, spams) | Hard checks in hooks/tool code, not prompt instructions; dry-run first; human approval required to publish; caps; kill switch |
| Agents hit the Claude plan's usage limits | Subagents keep context small; effort per role; `max_turns`; priority order under high usage; automatic pause and resume at reset; usage measured per source in Phase 1 so throughput is known up front |
| Session context grows over a long campaign | Resume per event with short summaries; subagents read the big transcripts; SDK compaction; Campaign agent writes a running `log_note` so a fresh session can take over |
| A marketplace forbids automation / changes its site | Check the ToS first; the agent can read raw page snapshots when the parser breaks; manual "paste campaign" mode |
| Platform spam suppression | Per-account caps and spacing, caption variation, quality threshold |
| Platform UI changes break upload recipes | Agent finishes the step from screenshot + DOM; failure screenshots saved; recipes versioned and quick to patch; dry-run recipe tests against each site weekly |
| Account flagged for automation | Your real profile and home IP, human pacing, low caps, slow ramp-up, pause on any challenge; no fingerprint tricks or CAPTCHA solving |
| Copyright | Source whitelist enforced in code; authorization record kept per clip |
| Discord 10 MB bot upload limit | 2-pass encode to a target size; link to the dashboard for full quality |

---

## 13. Decisions (defaults, changeable in Settings)
- **Orchestration:** Claude Agent SDK subprocesses; a small supervisor only for triggers, events, usage pacing and safety
- **Model:** Claude Opus 5.5 for all agents and subagents, effort per role
- **Platforms:** YouTube Shorts → TikTok → Instagram Reels, one account each to start, **uploaded through the Companion browser extension (no platform APIs)**
- **Autonomy:** Scout in `suggest` mode at first; every clip batch reviewed by a human; publishing hard-gated on approval
- **Clip engine:** in-house on the local GPU, with the agent choosing moments, layouts and captions
- **Stack:** Python core + Tauri/React desktop software + discord.py bot + Clipper Companion Chrome extension (MV3, TypeScript)
- **Look:** Windows utility style: native frame, menu bar, toolbar, tree navigation, data grids, docked output panel, status bar; follows Windows light/dark and accent color (UI.md §1)

---

## 14. Operating playbook (v2.1 additions)

### Speed and budget awareness
- **Pre-download sources when a campaign is found**, before you accept it (cheap; deleted if you skip). Analysis starts the moment you click Take.
- The Scout records `budget_left` every run and predicts **when each campaign's budget will run out**. The Campaign agent stops queueing clips that couldn't get their views before then. Views after the budget runs out pay nothing.
- Headline KPI on Home: **time from campaign found to first post**, plus $ earned per clip and per hour of GPU time.

### Accounts: niches and warm-up
- Each account has **niche tags** (e.g. `gaming`, `podcast-business`, `mrbeast-style`). The Scout's fit score and the Campaign agent's account choice only pair campaigns with matching accounts.
- **Warm-up schedule** for new accounts: 1 post/day for week 1, 2/day for week 2, then the normal cap. Enforced in the posting-cap hook.

### Auto-approval earned over time
- Every review decision is recorded against the clip's score. When clips scoring ≥ T have been approved **> 95% of the time over ≥ 100 decisions**, the dashboard *offers* to auto-approve that tier. It's opt-in, can be undone, and auto-approvals are logged and still appear in Discord as "auto-approved" cards you can pull back before they're posted.
- Review batches show the strongest clips first, so you can skip the bottom of the list when short on time.

### Avoiding moments others already used
- Before choosing moments, the editor searches YouTube Shorts and TikTok (yt-dlp search) for clips already made from the same source. It lowers the score of moments that are already well covered and favors ones nobody has posted.

### Quality test set
- `tests/golden/`: 10 fixed source videos + the clips you approved from them + rejected examples.
- `clipper eval` re-runs the editor on the set and scores how well the new picks overlap the approved clips, plus how often rejected-style moments come back. **Any change to agent instructions, model or effort settings has to pass this before going live**, so changes can't quietly lower quality.

### Upkeep
- Nightly SQLite backup (keep 14 days) to a second folder or cloud drive of your choice.
- Stop Windows from sleeping while jobs or uploads run (`SetThreadExecutionState`).
- Logs rotate daily; failure screenshots kept for 30 days.
- **Health panel:** extension connected (per profile), Discord bot online, GPU worker alive, each enabled marketplace's session valid, disk space, Claude login (plan account, no API key in use) and usage window status. A problem with any of these posts to `#alerts`.

---

## 15. Marketplaces (Vyro + Whop) and on/off switches

### 15.1 Marketplace adapters
Every marketplace implements one interface, so the agents never contain marketplace-specific logic:

```
MarketplaceAdapter
  session_check() → ok | needs_login
  list_campaigns() → [CampaignCard]
  get_campaign(id) → CampaignDetail (rules text, sources, payout terms)
  join_campaign(id) → joined | needs_user (e.g. paid join, extra verification)
  submit_post(campaign, post_url | file) → submission_id
  submission_status(submission_id) → pending | approved | rejected(reason) | paid
  earnings(since) → [payout rows]
```

Every campaign is converted to the same shape: `marketplace`, `external_id`, `cpm_usd`, `budget_total/left`, `cap_per_post`, `min_views_to_pay`, `allowed_platforms`, `deliverable` (`link` | `upload`), `content_type` (`clipping` | `ugc` | `other`), `tracking_window_days`, `rules_raw`.

| | **Vyro** | **Whop Content Rewards** |
|---|---|---|
| Access | Companion extension (browser) | Companion extension by default. Whop's beta bounty-submission API (needs a *user* token) is an optional route if it turns out to cover Content Rewards; checked in Phase 4 |
| Discovery | Campaign list | Content Rewards discovery pages. Some campaigns require joining the creator's Whop: free joins are done automatically, **paid joins are never automatic** (they go to "Needs you") |
| Pay | ≈ $3 CPM, $1k cap per clip | $0.20–$6 CPM, caps and minimum-view thresholds vary per campaign |
| Submission | Post URL | Post URL (link campaigns) or file upload (upload campaigns) |
| Content | Clipping | Clipping **and UGC**. UGC is filtered out by default (setting) because it needs on-camera content we don't make |

- **Scoring across marketplaces:** expected $ = CPM × expected views (limited by caps, minimum-view thresholds and budget left) × **approval rate per marketplace** × payout reliability. The Analyst learns the last two from real submission results, since approval rates and payout delays differ between marketplaces.
- **Same creator on both marketplaces:** campaigns from the same creator/source are grouped together. A post is never submitted to two campaigns unless both campaigns' rules allow it.
- Earnings, approval rate and payout delay are tracked **per marketplace** and shown side by side.

### 15.2 On/off switches
Three levels, all stored in the DB:

| Level | Switches | Default |
|---|---|---|
| **Marketplaces** | Vyro · Whop | both on (once logged in) |
| **Socials** | YouTube Shorts · TikTok · Instagram Reels · X | YT, TT, IG on · **X off** (its upload script comes in Phase 5) |
| **Accounts** | each account individually | on, after warm-up starts |

Each campaign can also be limited to a subset of the enabled socials, in its spec.

**What switching off does:**
| Switch off | Immediately | Asked in a dialog |
|---|---|---|
| A marketplace | Scout stops reading it; its campaigns stop getting new clips; its tools are denied | Active campaigns: **Finish them** (still submit posts that are already live; default) or **Pause them now** |
| A social | Nothing new is scheduled there; captions aren't generated for it; campaigns that only allow disabled socials are marked "no enabled socials" and skipped | Already-scheduled posts: **Cancel N posts** or **Let them post** |
| An account | Same as a social, for that account only | Same |

**Switching on** runs a check first (marketplace login valid / at least one connected account on that social). If it fails, the switch shows "Needs setup" with a link to fix it.

**Enforced in code, not by the agent:**
- At session start, the supervisor builds each agent's tool list and context from the current switches.
- `PreToolUse` hooks re-check the switches on **every** call, so a change takes effect mid-session.
- A `toggles.changed` event resumes running sessions with a short note so they re-plan.

**Where you can flip them:** the title-bar chip strip (quick), Settings → Marketplaces and socials (full), Ctrl+K ("turn off Whop"), and Discord `/clipper toggle <name> on|off` (only for the `@Clipper` role). Every change is logged with who made it and where.

### 15.3 Phase placement
- **Phase 3:** social and account switches (publishing respects them)
- **Phase 4:** marketplace interface → Vyro adapter → Whop adapter → marketplace switches
- **Phase 5:** X upload script (switch becomes available)

---

## 16. MCP servers

Three groups: **our own servers** (the agents' main tools), **third-party servers** used at runtime, and **development-only servers** that help build the project in Claude Code. Every server runs locally.

### 16.1 Our own servers (in-process SDK MCP, also exposed over stdio)

| Server | Status | Tools | Why |
|---|---|---|---|
| `clipper-state` | core | `get_campaign`, `list_campaigns`, `update_campaign`, `save_spec`, `save_moments`, `get_clip`, `log_note` | The only way agents change state |
| `marketplace` | core | `list_campaigns`, `get_campaign_page`, `join_campaign`, `submit_post_url`, `get_submission_status`, `get_earnings`, `snapshot_page` | Vyro + Whop behind one interface (§15) |
| `media` | core | `download`, `analyze`, `get_transcript(from,to)`, `get_signals`, **`get_comments`** (timestamped top comments, a strong virality signal), **`frames(ts[])`**, **`contact_sheet(clip)`**, **`ocr_frames`** (finds burned-in watermarks/captions in the source), `render`, `job_status` | GPU media engine; lets agents *see* the video |
| `review` | core | `post_batch`, `post_campaign_card`, `get_batch_status`, `get_decisions`, `replace_preview` | Discord + dashboard review |
| `publish` | core | `list_accounts`, `schedule_post`, `cancel_post`, `get_post_metrics`, **`account_health`** (follower count, recent reach, signs of a shadowban) | Uploads through the Companion extension |
| `browser` | core | `snapshot`, `click`, `type`, `attach_file`, `navigate` | Fallback when an upload/marketplace script breaks; domain allowlist |
| **`supervisor`** | **new** | `wake_me(at or in, reason)`, `list_wakeups`, `cancel_wakeup`, `get_usage` (current window, reset time, how heavily to pace), `report_status(text)` | Agents have no clock. This lets them schedule their own follow-ups ("check views in 6h", "post the next clip at 19:00") and pace themselves to the plan's usage |
| **`notify`** | **new** | `alert(level, text)`, **`ask_user(question, options[], timeout)`**, `send_report(markdown)` | Lets agents ask you something instead of guessing (e.g. "these rules are unclear: can we use the trailer footage?"). The question appears as Discord buttons + in the dashboard's "Needs you"; your answer **resumes the session**. Optional phone push via ntfy |
| **`memory`** | **new** | `recall(entity, query)`, `remember(entity, note, evidence)`, `forget(id)`, `list_lessons(scope)` | Long-term lessons, stored per creator, marketplace, platform, account and recipe: "this creator rejects clips with background music", "Whop campaign X pays out ~10 days late", "TikTok upload button moved, new selector …", "you reject clips under 20s". Every note links to the evidence behind it; you can edit or delete notes in the dashboard |
| **`trends`** | **new** | `niche_trends(niche)` (trending Shorts/TikToks in a niche via yt-dlp search + browser), `hashtags(niche, platform)`, `saturation(source)` (how many clips of this source already exist, and which moments), `best_post_times(account)` | Feeds the editor (avoid moments others already used, §14), the copywriter (hashtags) and the scheduler (timing) |
| **`insights`** | **new** | `query(sql)` on a **read-only** connection, plus ready-made queries: `performance_by(dimension)`, `approval_rate_by(dimension)`, `top_clips(n, metric)`, `campaign_report(id)` | Lets the Analyst and Director answer questions with real numbers ("which hook style earns most on Whop?") without being able to change anything |
| **`edit`** | **new** | EDL operations: `get_edl`, `trim`, `split`, `remove_silences`, `remove_fillers`, `set_layout`, `set_camera_keyframes`, `set_caption_style`, `emphasize`, `set_hook`, `add_overlay`, `set_audio`, `make_variant`, `preview`, `render_final`, `undo` | The agent's video editing tools; every step is broadcast live to the Edit page (§18.3) |
| **`agenda`** | **new** | `set_plan`, `check`, `get_notes`, `ack_note` | The agent's visible to-do list and your notes (§18.5) |
| **`clipper`** (umbrella) | **new** | read-only subset of the above + pause/toggle controls | A single stdio server for **Claude Desktop / Claude Code**, so you can ask about the system from anywhere ("what's waiting for review?") |

### 16.2 Third-party servers at runtime

| Server | Used by | Purpose | Notes |
|---|---|---|---|
| **Playwright MCP** (`@playwright/mcp`) | Director only, on request | Debugging fallback: attaches to the Clipper Chrome profile over CDP when the extension is down | Off by default; domain allowlist still applies |
| **Claude Code built-in WebSearch / WebFetch** | Analyst, a *research* subagent | Creator background for scoring, platform policy changes, marketplace announcements | **Only given to agents with no publish/submit tools**, because web pages are untrusted (prompt-injection rule, §4) |
| ntfy (HTTP, wrapped inside `notify`) | `notify` | Phone push notifications | Optional; self-hostable |

Not added on purpose: generic filesystem/shell servers (agents never get raw disk or shell access), a generic SQLite server with write access (use `insights`, which is read-only), music/sound libraries (copyright risk, and many campaigns ban added music).

### 16.3 Per-agent access (least privilege)

| Agent | state | market | media | review | publish | browser | supervisor | notify | memory | trends | insights | web |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Scout | rw | read | download (pre-fetch) | campaign cards | — | — | ✓ | alert | rw | ✓ | — | — |
| *brief-reader* | — | — | — | — | — | — | — | — | read | — | — | — |
| *research* | — | — | — | — | — | — | — | — | write | — | — | ✓ |
| Campaign | rw | its campaign only | ✓ | ✓ | schedule (approved clips only) | fallback | ✓ | ✓ | rw | ✓ | — | — |
| *editor* | read | — | read + frames | — | — | — | — | — | read | saturation | — | — |
| *qa-checker* | read | — | frames, contact sheet, OCR | — | — | — | — | — | read | — | — | — |
| *copywriter* | read | — | — | — | — | — | — | — | read | hashtags, times | — | — |
| Analyst | rw (weights) | earnings, status | — | — | metrics, health | — | ✓ | reports | rw | ✓ | ✓ | ✓ |
| Director | read + controls | read | read | read | read + cancel | Playwright (on request) | ✓ | ✓ | rw | ✓ | ✓ | — |

**`edit` and `agenda` access:** the *editor* subagent gets all `edit` operations except `render_final`, plus `agenda`; the Campaign agent gets `edit.render_final` (approved clips only) and `agenda`; the Director gets `agenda` and read-only `edit`.

**Rules for every tool:**
- Names are namespaced (`mcp__media__render`).
- Read-only tools carry `readOnlyHint`.
- Results stay small: IDs, file paths, summaries and pages of a transcript, never whole videos or full transcripts in one result.
- Every call is checked by the `PreToolUse` hooks (approval, switches, caps, allowlists).
- Each agent sees **at most 25 tools**.

### 16.4 Development-only servers (for building Clipper.io in Claude Code)

| Server | Why |
|---|---|
| **context7** | Current docs for Tauri v2, discord.py, claude-agent-sdk, WhisperX, shadcn/ui, so code isn't written against outdated APIs |
| **shadcn MCP** (`npx shadcn@latest mcp`) | Browse and install real shadcn/ui components and blocks from the registry instead of hand-writing them |
| **Playwright MCP** / the built-in browser | Click through the dashboard during development; screenshot every screen in dark + light and compare against UI.md |
| **Skills / plugins:** `frontend-design` (installed), Anthropic **Design** plugin (critique, accessibility, UX copy), `dataviz` (charts) | Design direction while building, and a review pass on each finished page |
| **Discord MCP** (already connected in this session) | Create the test server's channels, check bot messages while building the review flow |
| **SQLite MCP** (read-only, dev DB) | Inspect state while debugging the agents |
| Our own servers over stdio | Call each tool by hand before any agent uses it |

These go in the repo's `.mcp.json` during Phase 0.

### 16.5 Phase placement
- **Phase 0:** `clipper-state`, `supervisor` (wake_me, get_usage), `notify.alert`, dev `.mcp.json`
- **Phase 1:** `media` (incl. frames/comments/OCR), `memory`
- **Phase 2:** `review`, `notify.ask_user`
- **Phase 3:** `publish`, `browser`, `trends.hashtags/best_post_times`
- **Phase 4:** `marketplace`, `trends.saturation/niche_trends`
- **Phase 5:** `insights`, the `clipper` umbrella server for Claude Desktop, Playwright fallback, research subagent with web access

---

## 17. Running many agents at once

The supervisor runs a **pool of agent slots**. Each slot is a Claude Code subprocess (`ClaudeSDKClient`), and all of them run at the same time on your Claude login.

### 17.1 Slots and priority
- **Slots:** default **4**, configurable 1–8 in Settings. The 9800X3D + 32 GB RAM handles 6+ comfortably (each subprocess ≈ 300–500 MB).
- **Every piece of agent work is a queued request** with a priority. When a slot frees up, the highest-priority request runs:

| Priority | Work |
|---|---|
| **P0** | You're waiting: Director chat, answers to `ask_user`, a re-cut or note from the Edit page, Discord commands |
| **P1** | Money on the line: review shipped → scheduling, live post → URL submission, budget about to run out |
| **P2** | Production: Campaign agents (brief, moments, edits, QA) |
| **P3** | Background: Scout, Analyst, memory upkeep |

- **One P0 slot is always kept free**, so the app answers you instantly even when everything else is busy.
- **Adapts to usage:** as the Claude usage window fills up, the pool shrinks automatically (e.g. 4 → 2 → P0/P1 only), and it grows back after the reset. You can see this in the Agents page header.

### 17.2 Parallel work within a campaign
- Several **Campaign agents run side by side**, one per active campaign.
- Inside one campaign, the Campaign agent starts **background subagents in parallel**: one *editor* per source video, one *copywriter* per batch of clips, *qa-checker*s on finished renders. It collects their results when they finish.

### 17.3 Keeping parallel agents from colliding
| Shared thing | How conflicts are prevented |
|---|---|
| A campaign | **Lease**: only one session acts on a campaign at a time. Events that arrive while it's busy are queued and merged into the next resume |
| A clip's edit | **Edit lock** per clip: agent or you. If you open a clip in the Edit page, the agent pauses its edits on that clip and waits for your notes (§18.4) |
| GPU | The GPU worker queue: 1 WhisperX job + up to 3 NVENC encodes at a time (the RTX 5080's encoder limit), previews first |
| Browser / accounts | **One action at a time per Chrome profile**, and one upload at a time per account. Marketplace sites have their own request rate limits |
| Database | SQLite in WAL mode; all writes go through one writer queue in clipper-core, so the agents never write directly |
| Posting caps | Checked at the moment of scheduling, under a lock, so two agents can't both take the last slot of the day |

### 17.4 Visibility
The Agents page shows a **slot board**: each slot's agent, campaign, current tool and elapsed time, plus the **waiting queue** with priorities. You can pause any slot, bump a request's priority, or cancel it.

---

## 18. Editing engine v2

### 18.1 One editable recipe per clip (the core change)
Every clip is a **timeline document in JSON** (an edit decision list, "EDL"), not a finished video file:

```
clip.edl = {
  source, range,
  segments:  [ {in, out} ... ]                  ← cuts, removed silences/filler words
  camera:    [ {t, layout, crop:{x,y,w,h}, zoom} ... ]   ← reframing keyframes
  captions:  { style, words:[{t,text,emphasis}], position, safe_zone:"tiktok" }
  overlays:  [ {type:"hook_text"|"progress_bar"|"brand", t_in, t_out, props} ]
  audio:     { loudness:-14, denoise:true, duck_music:true }
  hook:      { type:"cold_open"|"text"|"none", range }
}
```

- **Agents and you edit the same thing** with the same operations (§18.3), and every change is a logged step that can be undone. A re-cut is just a few edits, not a new job.
- **Preview without rendering:** the Edit page plays a low-res **proxy** video (made during analysis) and draws captions, crop and overlays live in the browser from the EDL. Changes appear instantly, nothing is rendered.
- **Final render only for approved clips** at full quality. That saves most of the GPU time, because rejected clips never get a final render.
- Renders are reproducible: same EDL + source → same output.

### 18.2 Editing quality improvements
| Area | Improvement |
|---|---|
| **Cuts** | Snap to word boundaries with a little padding; **remove dead air** (silences above a threshold, with an aggressiveness setting); **remove filler words** ("um", "uh", "like", false starts) using word timestamps; never cut mid-word |
| **Hook** | **Cold open**: the agent can move a teaser of the payoff (1–2s) to the very start, then play from the beginning. Rule: speech starts within the first 0.5s. A hook-text overlay is written per clip |
| **Reframing** | **Active-speaker detection** (lip movement + speaker labels), not just "the biggest face". A smooth virtual camera with a dead zone and eased movement; hard cuts only on real scene changes; **switches layout mid-clip** (speaker crop ↔ split-screen when both people talk ↔ blurred-background fit for wide shots) |
| **Captions** | Word-by-word with **emphasis words chosen by the agent** (color/scale pop); lines broken at phrase boundaries; **platform safe zones** so captions never sit under TikTok's buttons or the Shorts title area; avoids covering faces (checked per frame); profanity masking when the campaign requires it |
| **Source issues** | Text recognition finds **burned-in captions/watermarks** in the source → crop past them, or move our captions so they don't collide |
| **Audio** | Dialogue denoise (DeepFilterNet), loudness normalized to −14 LUFS with a true-peak limit, background music ducked under speech, clean fades at the cuts |
| **Motion** | Subtle **punch-in zooms** on emphasis moments (1.0→1.08), optional progress bar; no gimmicks by default |
| **Picture** | Frame rate conformed (30/60), HDR→SDR conversion, gentle sharpening for low-res sources, high upload bitrate (1080×1920, ~12–16 Mbps) so the platforms' re-encode looks clean |
| **Variants** | 2–3 **hook variants** per clip (different hook text or a cold open vs. none) shown side by side in review; you choose, and the choice feeds the learning loop. Only the chosen variant is posted |
| **Presets** | Style presets per campaign (from the brief's brand rules) and per account (consistent look per channel) |

### 18.3 The `edit` MCP server (new)
Agents edit through these tools. The Edit page calls the same operations.

`get_edl`, `trim(in,out)`, `split(t)`, `delete_range`, `remove_silences(level)`, `remove_fillers`, `set_layout(range, layout)`, `set_camera_keyframes`, `set_caption_style`, `edit_caption_words`, `emphasize(words)`, `set_hook(type, range | text)`, `add_overlay`, `set_audio`, `make_variant(changes)`, `preview(range)` (renders a quick proxy if needed), `render_final`, `undo(op_id)`

Each operation is saved to `edit_op` and **broadcast live** to the Edit page (§18.4).

**Automatic QA on every EDL** (before review): speech starts ≤ 0.5s, face in frame ≥ 90%, captions never cover faces or platform buttons, no black or frozen frames, no audio clipping, silence ratio, length within the spec.

### 18.4 Edit page: live view + agenda
- **Live view of what the agent is doing:** while an agent edits a clip, the Edit page shows each operation **as it happens**:
  - A violet "Claude" playhead and highlighted range on the timeline where it's working
  - A status line ("Removing filler words 0:12–0:19…")
  - The preview updates as soon as each step lands
- **History panel:** every step from the agent or you, with who did it and why (the agent's one-line reason). Click a step to preview the clip before/after it; undo any step.
- **Agenda panel** for the clip and its campaign:
  - **Plan:** the agent's current to-do list for this clip ("1. cold open from 0:31 · 2. remove fillers · 3. split-screen 0:20–0:28 · 4. captions with emphasis"), ticked off live. Agents set it with the `agenda` tools.
  - **Your notes:** type instructions ("make the hook shorter", "no zoom on this one", "use yellow captions for this creator"). Choose where each note applies: **this clip** / **this campaign** / **always for this creator** (saved to `memory`). Adding a note sends a P0 request to the agent, which updates its plan and makes the edits, and you watch them happen.
- **Taking over:** start editing by hand and the clip is locked to you (the agent pauses). Click **Hand back to Claude** and the agent continues from your version, reading your notes first.

### 18.5 The `agenda` MCP server (new)
`set_plan(scope, items[])`, `check(item_id, result)`, `get_notes(scope)`, `ack_note(note_id, response)`. Scopes: clip, campaign, global. Notes are untrusted only in the sense that they're yours; the hooks still block anything against the rules (e.g. a note can't make the agent publish an unapproved clip).

### 18.6 Phase placement
- **Phase 1:** EDL format, proxies, renderer from the EDL, `edit` operations, cut/caption/reframe improvements, automatic QA
- **Phase 2:** Edit page (live view, history, agenda + notes), hook variants in review, edit locks
- **Phase 3–4:** agent pool with priorities + leases (a basic 2-slot pool exists from Phase 0)
- **Phase 5:** active-speaker detection upgrade, style presets per account, adaptive pool sizing tuned on real usage data
