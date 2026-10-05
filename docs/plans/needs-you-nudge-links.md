# Plan: Needs you details, nudges, campaign links, and stuck-work fixes

Status: planned 2026-10-04. All milestones (M0 to M6) are implemented (see the commit log). What was left out on purpose is listed under each milestone's "As built" and in HANDOFF §5 item 12. Based on `claude/affectionate-davinci-f3xmlm` at `e66b2f7`. The questions in §12 all have defaults written into the plan, so work can start at M0 without waiting for answers.

This plan is for whoever implements it. Read CLAUDE.md first: agents run on the plan login only, safety rules live in code, and UI work follows the routine (frontend-design skill, shadcn MCP, utility style, check dark and light at 1280×800 and 1920×1080).

Requested by the user:
1. Expand a "Needs you" item on Overview to see everything about it: every option, plus a place for a custom answer.
2. A **nudge** for any agent or piece of work that gets stuck on a step.
3. A working link from every campaign to its page on the marketplace.
4. Bug: a black, glitched window sometimes opens.
5. Bug: when a download gets stuck, the expanded item should show a clickable link to the file and accept a video file dropped onto it.
6. Review the app as a critic and add more improvements (§7).
7. Scrap videos in the Library: throw clips away, one or many at a time (§6b).

---

## 0. Summary

| # | Item | Kind | Size | Milestone |
|---|---|---|---|---|
| H1 | Needs you rows hide the question text (layout bug) | bug | S | M0 |
| H2 | Drop-folder scan attached a stale test file to a real campaign | bug, data safety | S | M0 |
| H3 | Download errors show a yt-dlp warning instead of the error | bug | S | M0 |
| H4 | Black window: Clipper's hidden Chrome shown before it repaints | bug | M | M0 |
| H5 | Questions stay open after their campaign ends | bug | S | M0 |
| A | Expandable Needs you items, with a custom reply | feature | L | M1 |
| C | A working link for every campaign, opened in the logged-in Clipper browser | feature | M | M2 |
| S | Scrap clips in the Library: select, scrap, undo, restore, clean up, purge files later | feature | M | M2b |
| F | Footage needed: link, drag and drop, recent downloads, import progress | feature + bug | L | M3 |
| B | Stall detection and nudges for agents, requests, jobs and recipes | feature | L | M4 |
| B4 | Automatic nudges with escalation; Discord parity | feature | M | M5 |
| §7 | Critic's review items | mixed | S–M each | M0–M6 |

---

## 1. What the running app showed (2026-10-04, about 21:05 UTC)

I looked at the running app (Tauri dev, `clipper api`, the bot, and the hidden Chrome `main` profile), read `D:\Clipper.io\data\clipper.sqlite` in read-only mode, and listed the processes' top-level windows. Each item below has evidence. The fixes are in the sections listed.

1. **The black window is Clipper's own Chrome** (§5). A visible `Chrome_WidgetWin_1` window of the `main` profile (pid 60188, command line `--user-data-dir=C:\ClipperData\chrome\main …`) sat on the portrait monitor at (-1080, -186), 1080×1372, titled "Edits - Frame.io - Google Chrome". That matches the screenshot's size, position, rounded corners and accent border. A screen capture of the same area a moment later showed the window painted normally (Vyro campaign dialog, Frame.io tab). The user's screenshot is that window before Chrome drew anything, not even its tab strip.
2. **Question rows hide the question** (H1). On Overview, each question's answer buttons fill the Item and Details columns, so you can't read what is being asked. Cause: `attention.tsx:27` gives the action column `minmax(200px,auto)`, and four long button labels push the other columns to zero.
3. **Answer options are cut mid-word** (§7.1). For example "…give you the correct URL; then retry t". `notify.py:60` keeps only the first 80 characters (`o[:80]`). The bot puts the option text in the Discord `custom_id`, which is limited to 100 characters (`components.py:370`).
4. **"Stuck on a download" turned out to be worse than stuck** (H2, §6). Campaign 1 ("5 Guys Face Their Crush") lists one source, `https://f.io/DvtfTpUk`. No download job ever ran for it. Source 5 was created at 21:04:03.397. Within a second, `MediaService.scan_drop_folders` (`media.py:168`) attached `C:\ClipperData\sources\campaign_1\youtube_ext101xxxxx.mp4`. That file is a 550 KB test fixture (FakeDownloader naming, created 2026-10-03 13:54), left over from before fixture paths were isolated in `5aa5f8e`/`03293ef`. It was then analyzed as "10 s, 2 words". The campaign agent noticed and asked question 6 ("probably a bad download… How should I proceed?"). A second stale fixture (`youtube_dQw4w9WgXcQ.mp4`) is still in that folder and will be attached to the next source that waits for footage.
5. **Download errors are misleading** (H3). Jobs 1 and 2 show `RuntimeError: yt-dlp failed: WARNING: Your yt-dlp version (2026.03.17) is older than 90 days!…`. The real `ERROR:` line (unsupported Frame.io or WeTransfer URL) is at the end. The Needs you row shows only the first 200 characters. yt-dlp itself is out of date.
6. **Failure rows never clear** (§7.4). Job 2 (download for source 4) failed on 10-03. You then attached the file by hand and source 4 was analyzed, but "download failed" is still listed. Failure rows have no actions at all: no retry, no dismiss, no link.
7. **Stale questions** (H5). Question 1 belongs to campaign 6, which ended on 10-04. Question 5 belongs to campaign 2, which is skipped. Both are still open in Needs you.
8. **Join confusion** (§4.5). `join_campaign` returned `needs_user` for campaign 1, but the brief text the agent read starts with "You've joined this campaign". The campaign now has status `needs_user`. The drawer offers Take and Skip, which mean nothing for this status, and the Needs you "Open" button only opens the drawer, not Vyro.
9. **Whop links don't open** (§4.1). All 11 Whop campaigns store the iframe app URL (`https://b4e0vdqv6zgqeqj4pfgm.apps.whop.com/c/exp_…/campaigns/<uuid>`). That page only works through Whop's launch URL (docs/LOCAL_CHECKS.md, "Marketplace sites"). "Open in browser" also opens the default browser, which may not be logged in to Vyro or Whop. Only the Clipper Chrome is.
10. **Vyro slug "mismatch" misled the agent** (§4.4). Campaign 2's slug is `i-built-a-city-…` while its title is "Eat Everything In A Grocery Store". By design, the slug comes from the first title. The agent took the mismatch as a wrong link and stopped the submit.
11. **A subagent was left behind** (§3, §7.10). Session 30 started the brief-reader as an async subagent (`"isAsync": true, "status": "async_launched"`) and ended its turn with "Waiting for the brief-reader to finish." Nothing would ever resume it with that result. The agent later wrote the spec itself ("brief-reader stalled").
12. **"Turns 85 / 80"** on the Agents context pane for campaign 2. The 85 is the total across every run, but the limit of 80 applies per run (`runner.py:303`), so the display wrongly suggests the limit was broken.
13. **Failure screenshots are missing.** Recipe runs 28 and 29 (`vyro.submit_url`) failed with `screenshot_path = None`.
14. **Window enumeration can hang.** My probe made the same `user32` calls as `Win32WindowOps.windows()` (`GetWindowTextLengthW`/`GetWindowTextW`, which send messages to the window) and hung for more than 2 minutes. The version using `InternalGetWindowText`, which sends no message, finished at once. `ChromeManager` makes these calls while holding its lock, and every status poll needs that lock (`manager.py:67`).
15. **The Library can't get rid of anything** (§6b). Campaign 2 is skipped, but its clips 1–8 still sit in `ready`: they failed first-pass QA and were never reviewed. They hold about 75 MB of previews plus about 55 MB of work folders and will stay forever. Clip 3 also keeps its v1 files next to v6. The Library has no selection, no context menu and no remove action. Its status filter offers `candidate` and `scheduled`, which no clip ever has, and lacks `draft`, `ready` and `final` (`LibraryScreen.tsx:12` against `ClipStatus` in `db/types.py`).

---

## 2. Feature A: expandable Needs you items

### Now
- `overview_needs_you()` (`core/clipper/api/views.py:262`) builds `NeedsYouItem {kind, urgency, title, detail, actions}` (`schemas.py:243`). It has no id and no link to the entity it is about, so the UI keys rows by index (`attention.tsx:40`).
- Kinds: `challenge` (paused account), `question`, `review` (batch), `campaign` (suggested or needs_user), `failure` (the last 3 failed jobs of any age).
- Alerts (`notify.alert`) are events only. They become toasts and output-panel lines but never appear in Needs you, and they can't be acknowledged.
- Rows are one line, with `truncate-1` on title and detail. Actions are buttons inline.

### A1. Data model
- Extend `NeedsYouItem` (keep the old fields so the bot and fixtures don't break):
  - `key: str`: stable, `<kind>:<entity id>`: `challenge:1` (account id), `question:6`, `review:3` (batch id), `campaign:1`, `join:1`, `footage:5` (source id), `stuck:job:2` (stall kind's entity), `alert:960` (event id), `failure:job:2`.
  - `entity: {type, id}`, `campaign_id`, `campaign_title`, `campaign_link: Link | None` (§4).
  - `since: datetime` (when it started needing you) and `timeout_at: datetime | None`.
  - `primary: NeedsYouAction | None`: the one action shown in the collapsed row. `actions` holds every action.
  - `options: list[str]`: the full answer options of a question, not cut short.
  - `links: list[Link]` with `Link {label, url, kind: "marketplace"|"source"|"post"|"platform"|"doc", host, open_in: "clipper"|"default"}`.
- New kinds, in urgency order:
  `challenge` 0 → `question` 1 → `footage` 1 (§6) → `join` 2 (§4.5) → `stuck` 2 (§3) → `review` 3 (2 if it times out within 2 h) → `campaign` 4 → `alert` 5 → `failure` 6.
- New table `attention` (migration `0003`): `key` (PK), `state` (`snoozed|dismissed|resolved`), `snoozed_until`, `note`, `by`, `updated_at`. Items are still computed from the source tables; `attention` only hides snoozed and dismissed keys. A key that comes back with new evidence (another job fails for the same source, say) uses a new key (`failure:job:<new id>`), so dismissing never hides new trouble.
- Alerts become items: `alert` events of level `warning`/`error` from the last 7 days with no `attention` row. Repeats of the same text and campaign within 1 h merge into one item with a count.
- Failures become items only while unresolved: newest failed job per input (`source_id`/`clip_id`/kind), no later successful job for that input, under 7 days old, not dismissed. A failed download whose source is now waiting for footage is shown as the `footage` item instead, not twice.

### A2. API (`core/clipper/api/routes.py`, `views.py`, `schemas.py`)
- `GET /api/needs-you` → `list[NeedsYouItem]`. `OverviewOut.needs_you` keeps the same list.
- `GET /api/needs-you/{key}` → `NeedsYouDetail`:
  - `item`: the row.
  - `body`: the full text (question, alert, error), never cut.
  - `facts`: property rows (label, value, optional link), e.g. Campaign, Asked by (role and session), Since, Times out, Source, Job, Attempts.
  - `agent`: `{session_id, role, status, last_messages: [≤3 agent messages or log notes for this campaign, newest first]}`. This is what the agent said just before asking.
  - `evidence`: `{error, raw_tail (≤4 KB), screenshot_url, dom_excerpt}` for failures, challenges and recipe errors.
  - `sources`: for `footage`, each source waiting for footage (§6).
  - `nudge`: for `stuck`, the nudge options (§3).
  - `timeline`: the last 20 events for the entity and its campaign, already turned into text by `describe()`.
- `POST /api/needs-you/{key}/dismiss {note?}`, `POST /api/needs-you/{key}/snooze {minutes}` (60, 240, or until 08:00 local), `POST /api/needs-you/{key}/reopen`. Questions, challenges, footage and stuck items can only be snoozed, not dismissed: dismissing them would silently stall the agent.
- `POST /api/needs-you/{key}/reply {text}` (1–2000 characters) is the **custom option**. It routes by kind and returns `{routed_to, id}`:
  - `question` → `notify.answer(qid, text, custom=True)`. `QuestionAnswered` gets `custom: true`, and `messages.describe()` says "The user answered in their own words: …".
  - Anything else tied to a campaign → a campaign note (`scope="campaign"`), which already resumes the campaign agent at P0 (`router.py`, `note.added`). The note text is prefixed with the item: "About: Footage needed for source 5. <text>".
  - Items with no campaign (account challenge, global alert) → Director chat (`POST /api/agents/director/chat`), with the same "About: …" prefix.
- `POST /api/questions/{id}/answer` gains `custom: bool = false`.
- Events: `attention.changed {key, state}`. `live.ts keysFor` maps `attention.*`, `alert` and `job.*` to `qk.overview` and the new `qk.needsYou`/`qk.needsYouItem(key)`.
- Performance: `status()` (`views.py:237`) recomputes the whole Needs you list on every 15 s poll and on many events, and `gpu_util()` starts `nvidia-smi` each time. Cache the count for 2 s and the GPU reading for 5 s.

### A3. UI (Overview, `components/domain/attention.tsx`, `screens/OverviewScreen.tsx`)
Load the frontend-design skill first. Use the shadcn MCP for `collapsible`, `radio-group`, `textarea`, `dropdown-menu` and `tooltip`, restyled with `tokens.css`. Add every state to `/dev/gallery` with fixtures.

**Collapsed row** (fixes H1):
```
 ▸ ● Question  The only listed source analyzed as just 10 s long with 2 words…   5 Guys Face…  4m  [Answer]  ⋯
 ▸ ● Footage   Footage needed: source 5 (f.io)                                   5 Guys Face…  4m  [Add file]  ⋯
 ▸ ● Stuck     Download of source 7 has made no progress for 14 min              Persona 4…   14m [Nudge]  ⋯
```
- Columns: chevron 20px · type 92px · item (`minmax(0,1fr)`, 2-line clamp, full text in tooltip) · campaign 160px (a link that opens the drawer) · age 44px (Cascadia Mono) · actions `minmax(120px,200px)`.
- At most one primary button plus a `⋯` menu with the rest. Questions show only "Answer", which expands the row. The exception is when all options are 16 characters or fewer and there are at most 3 (Yes/No/Skip); then they appear inline.
- Never wrap buttons into other columns. Labels truncate with a tooltip.

**Expanded row** (one at a time; the open key lives in the URL as `?item=question:6`, so toasts, the tray and the command bar can deep-link):
```
 ▾ ● Question  The only listed source analyzed as just 10 s long…             5 Guys Face…  4m
 ┌ What happened ──────────────────────────────┐ ┌ What to do ────────────────────────────────┐
 │ The only listed source (https://f.io/…)      │ │ ( ) 1  Re-download the source and re-analyze│
 │ analyzed as just 10 s long with 2 words, but │ │ ( ) 2  I'll upload the full video myself    │
 │ the campaign needs clips of at least 20 s…   │ │ ( ) 3  Pause the campaign                   │
 │ Campaign   5 Guys Face Their Crush  ↗ Vyro   │ │ ( ) 4  Proceed anyway with what we have     │
 │ Asked by   Campaign agent · session 30       │ │ Something else                             │
 │ Since      21:05 (4 min ago) · no timeout    │ │ [Answer in your own words…              ]  │
 │ Agent said "I saved the spec, but I can't…"  │ │ [Send answer]  [Snooze ▾]  Open transcript │
 │ ▸ Timeline (6)                               │ └────────────────────────────────────────────┘
 └──────────────────────────────────────────────┘
```
- At 900px wide and up there are two columns; below that they stack. The left column is selectable text and uses `PropertyGrid`. The right column holds the options as a numbered radio list with full text, then "Something else" (a textarea, placeholder by kind), then buttons.
- Content per kind:
  - `challenge`: paused reason, the recipe screenshot that hit it, last 5 recipe runs for the account, buttons "Show browser" (profile), "Resume account", "Open <platform> page".
  - `review`: clip count, thumbnail strip (6 max), timeout, "Review batch", "Pop out", "Approve all ≥ <threshold>".
  - `campaign`: score reason, payout terms, deadline, listed sources, "Take", "Skip", and "Open on Vyro" (§4).
  - `join`, `footage`, `stuck`: see §4.5, §6 and §3.
  - `alert`: full text, level, source, campaign, "Acknowledge" (dismiss), "Tell the agent…" (reply).
  - `failure`: kind, input, cleaned error, "▸ Full output" (raw tail in Cascadia Mono), started and finished, "Retry", "Dismiss", "Open campaign".
- Keyboard: ↑/↓ move between rows, Enter or → expands, Esc or ← collapses, 1–5 picks an option, Ctrl+Enter sends the custom reply, S opens the snooze menu, Delete dismisses (failures and alerts only).
- Also: the Overview tree node shows the count, a status bar segment "Needs you 7" opens Overview, and the Windows tray tooltip includes the count.
- Copy (sentence case, verb first, no "please"): "Send answer", "Add file", "Open on Vyro", "Snooze for 1 hour", "Dismiss", "Tell the campaign agent". Placeholders: "Answer in your own words", "Tell the campaign agent what to do".

### A4. Discord parity (`apps/bot/clipper_bot/components.py`, `actions.py`, `relay.py`)
- Answer buttons: `custom_id = clipper:question:answer:<qid>:<index>`. `from_custom_id` still accepts the old `<option text>` form, so posted messages keep working. The button label is the option, cut to 80 characters with "…".
- Add an "Other…" button that opens a modal (one paragraph `TextInput`, ≤ 500 characters) and posts the custom answer with `via="discord"`.

### A5. Tests
- `views`: keys are stable across calls; `failure` items disappear after a later success or a dismiss; repeated alerts merge; snoozed items come back after `snoozed_until` (fake clock).
- `reply` routing: question gives a custom answer, a campaign item gives a campaign note and a P0 request, a global item gives Director chat.
- Old and new Discord custom_ids both resolve.
- vitest: long options never render inline; Ctrl+Enter sends; one row open at a time; `?item=` opens the row.
- Playwright e2e: expand a question, answer with your own text, and see the row disappear (fixture build). Screenshots of every kind expanded, in dark and light, at 1280×800 and 1920×1080.
- Run `just gen-api` (openapi.json, TS client, fixture export) and check that the fixture export holds no secrets.

---

## 3. Feature B: nudge anything that's stuck

### Now
- Watchdog (`supervisor.py:496`): an **active or ending campaign** whose session has been idle for `triggers.watchdog_stale_min` (180 min), with no queued or running request **and no queued or running job**, gets a `watchdog.nudge` event at P2. The prompt says "Status check: no events for N min…" (`messages.py:53`).
- Manual nudge: `POST /api/agents/sessions/{id}/nudge` publishes the same event with `idle_minutes=0`, so the agent reads "no events for 0 min". It works for campaign sessions only. The Agents context pane has two buttons, "Nudge" and "Resume", that call the same endpoint (`AgentsScreen.tsx:167`–`172`).
- Not covered at all:
  - A **hung job**. yt-dlp runs with a 6 h timeout and reports no progress (`download.py:114`). A job counts as "busy", so the watchdog never fires for its campaign. That is exactly "stuck on a download".
  - A **running session that hangs**, for example on a browser action that never returns. It holds the campaign lease for 3 h (`LEASE_TTL_S`).
  - A **queued request that can't start**. `_begin()` returns False when a lease is held and nothing records why (`supervisor.py:292`). The pool can also be halted, P0/P1-only, low on memory, or at its daily cap.
  - A **session that ends its turn while waiting on something that will never come**, like the async brief-reader in §1.11.
  - Scout, Analyst and Director sessions, overdue posts, and stuck recipe runs.

### B1. Stall detector (`core/clipper/supervisor/stalls.py`, pure)
`detect_stalls(snapshot, now, settings) -> list[Stall]`. `Stall {key, kind, entity, campaign_id, since, summary, evidence, actions}`. The snapshot is read once per supervisor tick (cheap queries) and again by the Needs you view.

| Stall kind | Detected when | Evidence shown | Default action |
|---|---|---|---|
| `session_hung` | request running and no `agent_event` for `stalls.session_quiet_min` (10 min) | last tool call (name, args summary), how long it has been open, model | Restart turn |
| `waiting_on_nothing` | campaign active or ending, session waiting, and none of these for `stalls.idle_min` (30 min): queued request, open job, open question, pending wakeup, scheduled post, footage item | last agent message, e.g. "Waiting for the brief-reader to finish." | Nudge agent |
| `request_blocked` | request queued longer than `stalls.request_blocked_min` (5 min) | the reason, from a new `agent_request.waiting_reason` set by `dispatch()`: paused, kill switch, rate limited until HH:MM, high usage (P0/P1 only), daily run cap, low memory, all slots busy (what runs), lease held by session N since HH:MM | Run now / Release lease |
| `job_stalled` | job running and `progress_at` unchanged for `stalls.job_quiet_min` (15 min; 30 for analyze) | kind, input, last progress, bytes, speed, process alive | Cancel and retry |
| `job_waiting` | job queued longer than 10 min | resource (download, gpu, encode), running jobs holding it, kill switch | Show jobs |
| `recipe_stuck` | browser action in flight longer than its timeout, or extension disconnected while an action waits | recipe, step, profile, extension state | Show browser / Reload extension |
| `post_overdue` | scheduled post more than 15 min past due and not started | account status, cap, browser state | Open calendar / Nudge agent |

`footage` (§6) and `challenge` stay their own kinds; the detector doesn't duplicate them.

### B2. Nudge actions

| Action | Applies to | What it does | Guard |
|---|---|---|---|
| `nudge` | any session (all roles) or campaign | publishes `user.nudge {target, text, stall_key, evidence}`; the router sends P0 to the session's role (campaign → its campaign agent; scout or analyst → a fresh run; director → the Director) | normal tool guards; dry run and switches unchanged |
| `restart_turn` | `session_hung` | interrupts the running session (`runner.interrupt`), marks the request failed with "interrupted by your nudge", releases the lease, then `nudge` | only when the session is running |
| `run_now` | `request_blocked` | bumps to P0 (existing `bump`) | doesn't override pause, kill switch or rate limit; the UI says why it still can't start |
| `release_lease` | lease held by a session not in `_running` | `LeaseManager.release` | refused when the holder is running |
| `cancel_retry` | `job_stalled` | kills the job's process tree, marks it cancelled, queues a retry | at most 3 retries per input |
| `retry` | failed job | `JobQueue.retry` (exists) | — |
| `skip_source` | footage, failed download | marks the source `skipped`, then `nudge` "the user skipped source N" | — |
| `show_browser` / `reload_extension` | `recipe_stuck` | existing routes | — |

Every nudge accepts an optional message (1–1000 characters) from the user. The resume text (`messages.describe`) becomes:
"The user nudged you: <message, or 'You look stuck.'> What looks stuck: <summary>. Evidence: <one line>. Check `state.get_campaign`, then carry on or ask the user."
This replaces "no events for 0 min". Automatic nudges say "Automatic check" instead of "The user nudged you".

Each nudge writes a `nudge.sent {actor, target, action, stall_key, text}` event, so it appears in the campaign timeline and the Activity panel.

### B3. Jobs: progress, heartbeats and real cancel (`worker/jobs.py`, `media/download.py`, `worker/handlers.py`)
- Add `Job.progress_at` (migration `0003`), set whenever `JobContext.progress()` sees a changed value. Add `JobContext.detail(text)` for "1.2 of 3.4 GB · 8 MB/s · 4 min left".
- `JobContext.register_process(popen)` and a `cancelled` flag. `JobQueue.cancel_running(job_id)` kills the process tree (`taskkill /PID <pid> /T /F` on Windows, `psutil` elsewhere). The handler then raises `JobCancelled`. Today `cancel()` (`jobs.py:122`) only cancels queued jobs.
- Download: replace `subprocess.run(..., timeout=6*3600)` with `Popen` and read the lines as they come. Drop `--no-progress` for downloads only, add `--newline --progress-template "download:[clipper] %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s"`, parse the `[clipper]` lines, and keep `--print after_move:filepath` for the result. Kill the process when the stall rule fires, not after 6 h.
- Analyze: report each stage (transcribe, scenes, faces, OCR) through `progress` and `detail`. WhisperX already runs as a subprocess, so register it too.

### B4. Auto-nudge and escalation (generalizes the watchdog)
- Settings `[stalls]` (§8). In order:
  1. `waiting_on_nothing` shows in Needs you after `idle_min`. The existing auto-nudge still fires at `watchdog_stale_min`.
  2. `session_hung`: auto `restart_turn` after `auto_restart_hung_min` (30; 0 turns it off).
  3. `job_stalled`: one automatic `cancel_retry`.
  4. No more than `max_auto_nudges` (2) automatic actions per stall key. After that the item stays in Needs you and a toast says so.
- Nothing automatic runs while paused or with the kill switch on. Automatic nudges are P2; user nudges are P0 (PLAN §17.1: user requests first).

### B5. Where the nudge appears
- **Needs you**: `stuck` items. The expanded row shows the evidence, the actions as a split button (default action plus a menu), and "Nudge with a message" (a textarea; that's this item's custom option).
- **Agents**: the Context pane's "Nudge" opens a popover with a message field. Remove the duplicate "Resume" and hide the disabled "Fork". Slot rows show "quiet 12m" in amber when hung, with a Nudge menu. Queue rows show `waiting_reason`.
- **Campaigns**: a "Nudge agent" button in the drawer header. `StageStepper` marks the stage that is stuck in amber with the reason as a tooltip, on the Overview campaigns table too. A right-click "Nudge" on the grid and the Overview table.
- **Output panel → Jobs**: stalled jobs flagged, with "Cancel" and "Retry".
- **Command bar**: "Nudge <campaign>" and "Nudge everything stuck".
- **Discord**: `/clipper nudge <campaign> [message]`, and a "Nudge" button on stall alerts.

### B6. Safety
A nudge is only an event and a resume. It goes through the same guard hooks, approvals, caps, dry run and switches as any other turn. Its text comes from the user (trusted). The evidence lines are built from our own database, never from web pages. `release_lease` and `cancel_retry` touch only our own resources.

### B7. Tests
- `stalls.py` table tests with a fake clock: one case per kind, plus "not stuck" counterexamples (a job with fresh progress, a session waiting on a question).
- Router: `user.nudge` → P0 to the right role. Describe text with and without a message.
- `restart_turn` with the fake runner: the session is interrupted, the lease released, the request failed, and a new P0 request queued.
- `cancel_running`: a dummy long `python -c "sleep"` process is killed, the job becomes `cancelled`, and `retry` gives a new id.
- Download progress parsing on recorded yt-dlp output (fixture text file).
- Auto escalation stops at `max_auto_nudges`.
- UI: the nudge popover sends the message; Agents shows `waiting_reason`.

---

## 4. Feature C: a working link for every campaign

### Now
`Campaign.url` exists and is set for all 14 rows. Vyro rows use deep links (`app.vyro.com/campaigns?c=<slug>`), which open the dialog. Whop rows use the iframe app URL, which doesn't work on its own. The link is reachable only from the drawer's "Open in browser" (`CampaignsScreen.tsx:171`), which opens the default browser (`commands.rs:109`). The grid, the Overview table, Needs you, clip and post screens, and Discord cards have no link.

### C1. One link builder (`core/clipper/marketplaces/links.py`)
`campaign_link(c: Campaign, settings) -> Link` builds the link from `(marketplace, external_id)` with fixed templates and never trusts a scraped URL as-is, because campaign pages are untrusted input (PLAN §4):
- Vyro: `https://app.vyro.com/campaigns?c={slug}`, where the slug must match `[A-Za-z0-9_-]{1,120}`.
- Whop: `https://whop.com/core/app/launch/?redirect=<urlencoded https://{app_host}/c/{experience}/campaigns/{uuid}>`, with `uuid` checked against the UUID pattern. `app_host` and `experience` move from the hardcoded `whop.*.json` launch URL into `marketplaces.whop.app_url` (HANDOFF already notes other communities need this as a setting).
- Manual campaigns (pasted URL): the pasted URL, if its host is on the marketplace allowlist (`rules/urls.domain_allowed`).
- Fallback: the marketplace's campaign list page. Every campaign then has **some** link, and a test enforces that.
- The read models gain `link: Link`: `CampaignRow`, `CampaignDetail`, `ActiveCampaign`, `NeedsYouItem.campaign_link`, `ClipDetail.campaign_link`, `PostOut.campaign_link`, and the earnings rows.
- Verified 2026-10-05 in Clipper's logged-in Chrome (read-only probe): Whop's launch URL with a deep `/campaigns/<uuid>` redirect lands on that campaign's page, and a Vyro `?c=<slug>` link opens the campaign's dialog.

### C2. Open marketplace links in the logged-in Clipper browser
- `POST /api/browser/open {url, profile?}` → `ChromeManager.open_url(profile, url)`:
  1. Make sure the profile is running.
  2. Run `chrome.exe --user-data-dir=… --new-window <url>`. Chrome hands it to the running instance.
  3. Find the new window by comparing windows before and after, then show only that one, using the show steps from §5.
  4. Leave the other hidden windows hidden, including the extension's recipe window.
- The URL must be `https` and on the allowlist: marketplace and platform domains, the same list the extension uses. Other URLs are refused with 400.
- `profile` defaults to the marketplace's profile (`main` today).
- Setting `ui.open_marketplace_links_in = "clipper" | "default"`, defaulting to `clipper`. Source links (Frame.io, WeTransfer, Drive) open in the **default** browser, because they are third-party file hosts and downloads should land in your normal Downloads folder (§6). "Open in Clipper browser" stays available as a secondary action.
- Front end: `openCampaignLink(link)` in `lib/tauri.ts` picks the route by `link.open_in`.

### C3. Where the link shows

| Place | How |
|---|---|
| Campaigns grid | 24px link column (icon button, tooltip "Open on Vyro"); context menu "Open on Vyro" and "Copy link"; `O` opens the selected row's link |
| Campaign drawer | link icon next to the title; Overview property grid row "Page" (host and path, Copy); the old "Open in browser" button becomes "Open on Vyro" |
| Overview campaigns table | link icon in the title cell; right-click menu |
| Needs you | `campaign`, `join`, `question`, `footage`, `stuck` items carry the link in the campaign column and the expanded facts |
| Clip detail, Review header, Publishing post rows, Earnings rows | the campaign name opens the drawer; ↗ opens the marketplace |
| Agents context | ↗ next to the campaign |
| Discord campaign cards and review threads | a link-style button (`discord.ui.Button(style=link, url=…)`, no custom_id) plus the embed URL |

### C4. Link status
- Add `Campaign.link_status` (`ok|unavailable|unknown`) and `link_checked_at` (migration `0003`).
- Set the status from every `get_campaign` recipe run: the dialog showed this campaign → `ok`; "this campaign isn't available" or a 404 → `unavailable`, and also alert the campaign agent with `campaign.ending` (reason "page unavailable").
- Show a warning dot on the link icon when the status is `unavailable`, with the tooltip "Vyro says this campaign isn't available (checked 21:04)".
- Prompt fix (`agents/prompts/shared.md`, `campaign.md`): "Vyro slugs come from a campaign's first title and survive renames; a slug that doesn't match the title is normal."

### C5. Joining on the site (`join` items)
- `join_campaign` returning `needs_user` makes a `join` item instead of a vague `campaign` row:
  - Title: "Join 5 Guys Face Their Crush on Vyro".
  - Primary action: "Open on Vyro" (C2). Other actions: "I've joined", "Skip campaign".
- "I've joined" → `POST /api/campaigns/{id}/joined` sets the status back to `active` and publishes `campaign.joined {by: user}`, routed P0 to the campaign agent ("The user joined campaign N on the site. Carry on.").
- Recipe fix: `vyro.get_campaign` returns `joined: bool`, read from the dialog's "You've joined this campaign" text. `MarketService.join` checks it first and returns `already`, so the agent no longer asks about a campaign that is already joined.
- Drawer: for status `needs_user`, show "Open on Vyro to join" and "I've joined" instead of Take and Skip (`CampaignsScreen.tsx:157`).

### C6. Tests
- `campaign_link`: Vyro and Whop templates, a bad slug or uuid falls back to the list page, a manual URL off the allowlist falls back, and every seeded fixture campaign has a link.
- `/api/browser/open`: refuses non-https and off-allowlist URLs; with `FakeWindowOps`, only the new window becomes visible.
- `joined` route: status change, event and P0 routing.
- UI: link column, context menu, drawer. Screenshot checks.

---

## 5. Bug: the black, glitched window (H4)

### What it is
The window is a Clipper Chrome window (`main` profile), shown before Chrome has painted. With nothing painted, Chrome's own frame and tab strip are missing too, so you see a plain dark rectangle with the Windows 11 border. Evidence is in §1.1. The same window later painted fine.

### Why it happens (likely; confirm with the repro below)
1. **Hidden launch, then an outside show.** `Win32WindowOps.launch()` starts Chrome with `STARTF_USESHOWWINDOW` + `SW_HIDE` (`windows.py:43`). `show()` then calls `ShowWindow(SW_SHOW)` and `SetForegroundWindow` from another process (`windows.py:103`). Chrome stops producing frames for a window it believes is hidden, and an outside `ShowWindow` doesn't always make it draw a new frame until something resizes, activates or invalidates the window. `--disable-features=CalculateNativeWinOcclusion` and the background flags (`manager.py:25`) keep pages running but don't force a paint on show.
2. **New windows flash before the 1 s loop hides them.** New Chrome windows appear visible: the extension's tab when no window exists (`driver.ts:36`, `chrome.tabs.create` with `active: true`), session restore, and `target=_blank` popups from Frame.io and other pages. `tick()` only hides them up to a second later, and `windows()` skips any window whose title is still empty (`GetWindowTextLengthW > 0`, `windows.py:91`), which is exactly the state of a brand-new window.
3. **The window can freeze the loop.** `GetWindowTextLengthW` sends a message to the window. If Chrome's UI thread is busy, the manager blocks while holding its lock, and status polls wait on that lock (§1.14).

### Fix
1. **Repaint on show** (`windows.py` `show()`):
   1. `ShowWindow(SW_SHOWNOACTIVATE)`.
   2. `SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_FRAMECHANGED|SWP_SHOWWINDOW)`.
   3. `RedrawWindow(hwnd, None, None, RDW_INVALIDATE|RDW_ERASE|RDW_FRAME|RDW_ALLCHILDREN|RDW_UPDATENOW)`.
   4. If no new frame arrives within 300 ms (see verification), resize the window by 1px and back, which reliably makes Chrome redraw.
   5. Bring it forward with `AllowSetForegroundWindow` + `SetForegroundWindow`. If Windows refuses, flash the taskbar button (`FlashWindowEx`) instead of leaving it behind.
   6. Keep it on screen: if the window rect isn't inside any monitor's work area (it was at y=-186), move it into the nearest one, like `place_popout` does.
2. **Hide new windows before they paint.** Replace the 1 s polling for new windows with a WinEvent hook: `SetWinEventHook(EVENT_OBJECT_SHOW, …, pid, 0, WINEVENT_OUTOFCONTEXT)` on a dedicated thread with a message loop, one hook per Chrome pid. A new top-level window of a hidden profile is hidden as soon as it shows. Keep the 1 s tick as a backstop.
3. **Choose windows without sending messages.** Use `InternalGetWindowText`, not `GetWindowTextLengthW`. Pick top-level windows by class `Chrome_WidgetWin_1`, no owner, not `WS_EX_TOOLWINDOW`, and root owner equal to itself (`GetAncestor(GA_ROOTOWNER)`). Empty titles are allowed. Skip windows where `IsHungAppWindow` is true and report them instead (below).
4. **Start visible when you asked to see it.** `ensure_running()` launches hidden only for autostart. The "Show browser" button, an account login and `open_url` launch Chrome visible, without `SW_HIDE`.
5. **A recipe window of its own** (`driver.ts`): the Companion creates its working tab in its own window (`chrome.windows.create({url: "about:blank", focused: false})`) and remembers the window id in `chrome.storage.session`. Your tabs and the link windows from C2 never share a window with recipe runs, so `captureVisibleTab(windowId)` captures the right tab (this may also fix §1.13).
6. **Report a hung Chrome**: if a profile's window is hung (`IsHungAppWindow`) for more than 30 s, raise an `alert` with a `stuck` Needs you item: "Clipper's Chrome isn't responding." Actions: "Restart browser" (`taskkill /T` of that profile's pid, then `ensure_running`) and "Show browser".
7. **Pop-outs (hardening, lower priority)**: `pop_out` (`commands.rs:56`) shows the WebView2 window before React has drawn anything. Create it hidden with `background_color` set to the theme background, and let the page call `getCurrentWindow().show()` after its first render, with a 2 s fallback show from Rust. That rules out a blank pop-out on the portrait monitor too.

### Verification
- New LOCAL-VERIFY test `tests/local/test_local_verify.py::test_clipper_chrome_show_paints`:
  1. Launch a scratch profile (under `with_data_dir`, never the real profiles) hidden, on a local test page with a known pattern.
  2. Call `ChromeManager.show`.
  3. Capture the window with `PrintWindow(PW_RENDERFULLCONTENT)`.
  4. Assert the top 80px (tab strip) and the page area are not one flat color, within 1 s. Repeat 20 times.
- Manual check:
  1. Restart `just dev-api` so Chrome starts hidden.
  2. Click Show browser and Hide browser ten times.
  3. Trigger a recipe run while hidden, then show.
  4. Open a Frame.io link that opens a popup.
  5. Close every Chrome window and let the extension recreate its tab.
  No black window in any of these; the status bar keeps updating during all of it.
- Unit tests with `FakeWindowOps`: new windows from a hidden profile are hidden at once; `open_url` shows only the new window; a hung window is reported, not waited on.

---

## 6. Bug: stuck download → link and drag-and-drop in the expanded item (Feature F)

### 6.1 A `footage` item per source waiting for footage
- A source needs footage when any of these is true:
  - status `failed` (download failed);
  - new status `needs_footage` (the host can't be downloaded, §6.5);
  - a `job_stalled` download for it (§3).
- One Needs you item per such source:
  - Key: `footage:<source_id>`.
  - Title: "Footage needed: <campaign> · <host>".
  - Detail: the cleaned reason, e.g. "Clipper can't download Frame.io share links."
  - It replaces the raw "download failed" failure row for that source.
- Agent side: new tool `media.need_footage(source_id, reason)` (campaign agent; added to `access.py`) sets the status `needs_footage` and the reason. It replaces free-text `ask_user` questions about footage and the regex that guesses answers to them (`_FOOTAGE_QUESTION`, `media.py:32`). When the file arrives, `source.attached` resumes the agent at P1. Update `campaign.md`: "If a source can't be downloaded, call `media.need_footage` and end your turn. Don't ask the user a question about it."

### 6.2 Expanded footage item
```
 ▾ ● Footage   Footage needed: 5 Guys Face Their Crush · f.io                       4m
 ┌ What happened ───────────────────────────────┐ ┌ Add the video ──────────────────────────────┐
 │ Clipper can't download Frame.io share links. │ │ ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
 │ Download the file yourself and add it here.  │ │      Drop the video file here              │
 │ Link     https://f.io/DvtfTpUk               │ │ │    or [Browse…]  [Paste path]          │  │
 │          [Open link] [Open in Clipper browser]│ │ └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
 │          [Copy link]                         │ │ Recent downloads                            │
 │ Source   5 · failed 21:04 · attempt 1        │ │  5 Guys Face Their Crush.mp4 1.4 GB 12:31 [Use]│
 │ Error    Unsupported URL (frame.io)          │ │  episode-final.mov          2.1 GB 18:02 [Use]│
 │ ▸ Full output                                │ │ Something else                              │
 │ Drop folder C:\ClipperData\sources\campaign_1 │ │ [Tell the campaign agent…            ][Send]│
 │          [Open folder]                       │ │ [Retry download] [Skip source] [Snooze ▾]   │
 └──────────────────────────────────────────────┘ └─────────────────────────────────────────────┘
```
- **Clickable link** (left column):
  - "Open link" opens the default browser, so the file lands in your normal Downloads folder. "Open in Clipper browser" and "Copy link" are secondary.
  - The host shows as a badge, because the URL came from an untrusted page.
  - For `docs.google.com` sources, the doc is a list of links, not a video. Show "This link is a document. The video links in it:" followed by the links `marketplaces/docs.py` extracts, each with "Add as source". That is a user action through the API with `actor="user"`; the agent's source whitelist rule is unchanged.
- **Drop zone** (right column): a 1px dashed `--line` border, 4px corners, muted text; on drag-over the border and background turn `--accent`. No animation. Video types only (`VIDEO_EXTS`); a folder or another file type is refused with an inline message.
- **Browse…**: add `tauri-plugin-dialog`, with the `dialog:allow-open` capability in `capabilities/default.json`. `open({ filters: [{ name: "Video", extensions: [...] }] })` returns a path.
- **Paste path**: the existing field. It strips quotes from Explorer's "Copy as path".
- **Recent downloads**: `GET /api/sources/{id}/candidates` lists the 5 newest video files modified in the last 48 h:
  - Where it looks: `media.downloads_dirs` (default `%USERPROFILE%\Downloads`) and the campaign's drop folder.
  - What it returns: name, size, modified time and duration (ffprobe, cached by path and mtime).
  - Local only. It never reads other file types.
- **Several sources waiting**: each source gets its own row and drop zone inside the item. Dropping on the header area asks which source.
- **Before accepting a file**, probe it and warn when it looks wrong: shorter than 60 s or shorter than the spec's `duration_min_s`, no audio, or a different aspect than the other sources. Example: "This file is 0:10 long. The campaign needs clips of at least 20 s. Use it anyway?" with "Use file" and "Cancel". This check alone would have stopped the fixture mix-up in §1.4.

### 6.3 Drag and drop in the desktop app
- Tauri v2 handles OS file drops (`dragDropEnabled` defaults to true). Listen once with `getCurrentWebview().onDragDropEvent(...)`; events are `enter` (paths), `over` (position), `drop` (paths) and `leave`.
- New `lib/filedrop.ts` (Zustand store plus a `useFileDropZone(ref, onFiles)` hook):
  1. Each drop zone registers its DOM rect.
  2. The listener converts the physical position to CSS pixels (`/ devicePixelRatio`) and finds the zone under the pointer.
  3. `enter`/`over` light up that zone (and dimly every zone while you drag).
  4. `drop` calls that zone's handler with the paths.
- Dropped outside any zone:
  - Exactly one source waiting for footage → a small confirm dialog: "Add 5 Guys Face Their Crush.mp4 to source 5 (5 Guys Face Their Crush)?"
  - Otherwise → a status bar message: "Drop the file on a Needs you item."
- Works in the main window and the Review/Edit pop-outs (same capability set). dnd-kit in the calendar uses pointer events, not HTML5 drag and drop, so it isn't affected (check it in M3).
- Browser build (dev, Playwright): HTML5 drops give files without paths, so the zone says "Drag and drop works in the desktop app. Paste the file path here instead." For tests, `window.__clipperTestDrop(paths)` dispatches a fake drop (fixture mode only).
- Run the existing Campaign drawer Sources tab and `AttachDialog` (`CampaignsScreen.tsx:338`) on the same `FileDropZone` component.

### 6.4 Import as a job, with progress
- `POST /api/sources/{id}/file {path}` stops copying inside the request (`media.py:131` copies multi-GB files synchronously). It now checks the file (exists, extension, `ffprobe`), then queues an `import` job and returns `{job_id}`:
  - Same drive as the drop folder: **move** the file if it came from the Downloads candidates and the user chose "Move", otherwise copy.
  - Copy in 8 MB chunks with `progress`/`detail` ("1.2 of 3.4 GB").
  - Hash while copying (one pass), then set the source to `downloaded` and queue `analyze` (as today).
- The expanded item shows the progress bar and then "Analyzing…". The item resolves on its own when the source leaves the waiting states.

### 6.5 Fewer stuck downloads
- **Know the hosts up front** (`rules/urls.py` `download_support(url) -> "yes" | "no" | "try"`):
  - `no`: `frame.io`, `f.io`, `next.frame.io`, `we.tl`, `wetransfer.com`, `docs.google.com` (a document).
  - `try`: `drive.google.com`, `dropbox.com`.
  - `request_download` on a `no` host sets `needs_footage` right away instead of running a job that is sure to fail. "Try download anyway" stays in the item's menu.
- **Clean errors**: `clean_ytdlp_error(stderr) -> (reason, raw_tail)`:
  - Take the last `ERROR:` line and drop `WARNING: Your yt-dlp version … is older than 90 days`.
  - Known patterns: "Unsupported URL" → "This site isn't supported by the downloader"; "HTTP Error 403" → "The host refused the download (403)"; "Sign in to confirm" → "YouTube asked for a sign-in check"; "Private video" → "The video is private".
  - `Job.error` holds the reason; `result_json.raw_tail` holds the last 4 KB.
- **Keep yt-dlp current**: doctor warns when yt-dlp is older than 60 days. Settings → Media gets "Update yt-dlp", which runs `uv pip install -U yt-dlp` in the core env, or `yt-dlp -U` for the standalone exe, and shows the new version. The installed one is 2026.03.17.
- Progress and stall handling: see B3.

### 6.6 Drop-folder safety and fixture isolation (H2)
- `scan_drop_folders` only attaches a file when all of these hold (implemented in M0):
  - its `st_mtime` is not older than the source (`created_at`); an older file is a leftover. Later, with `source.waiting_since` (migration `0003`), use the time the source last entered a waiting status;
  - the source's status is `failed` (and `needs_footage` once M3 adds it), never `listed`, `queued` or `downloading` (those haven't been tried, or are still running);
  - the file is not shorter than the campaign spec's `duration_min_s`. This check only runs once a spec is saved; the UI's confirm in §6.2 also warns about files under 60 s.
  - A file that fails a rule is mentioned once (an alert) and ignored until it changes, with the list kept in `kv` (`media.drop_refused`). From M3 it becomes a `footage` item with "Found <file> in the drop folder. Use it for source N?" instead of an alert.
- Every automatic attach posts an `info` alert (today) **and** adds a line to the campaign timeline with "Undo": put the source back to waiting and move the file aside.
- Fixture isolation (implemented in M0): `Settings.with_data_dir()` keeps a sources folder **you chose yourself**, on purpose. Fixture mode and the fixture export now use the new `Settings.isolated(data_dir)`, which moves **every** folder under the demo data folder. `Core.create(fakes=True)` raises when the sources folder is outside the data folder, so fake footage can't reach real folders; tests cover both.

### 6.7 One-time cleanup on this machine (do it by hand; listed so it isn't forgotten)
1. Move `C:\ClipperData\sources\campaign_1\youtube_ext101xxxxx.*` and `youtube_dQw4w9WgXcQ.*` to a quarantine folder. They are fixtures, not footage.
2. Reset source 5 to `needs_footage` (once 6.1 exists) or `failed`, and remove its `analysis` row and the moments derived from it.
3. Answer question 6 with "The 10 s file was a leftover test file; the real footage is on Frame.io and I'll add it" so the agent's notes are right.

### 6.8 Tests
- `scan_drop_folders`: older files are ignored; `listed` sources aren't touched; a short file becomes a confirm item, not an attach.
- Fixture mode never writes under a custom `sources_dir`.
- `download_support` table; `clean_ytdlp_error` on recorded stderr (the two real failures from §1.5 as fixtures).
- `import` job: copy with progress, move on the same drive, the hash matches, then analysis is queued; with a fake clock, the item resolves.
- `candidates`: only video files, newest first, 48 h window, max 5.
- vitest for `filedrop.ts` hit-testing with DPR 1, 1.25 and 1.5.
- e2e (fixture build): expand a footage item, `__clipperTestDrop([path])`, the confirm dialog appears for a short file, and the item resolves.
- LOCAL-VERIFY: drag a real file from Explorer onto the item in `just dev-app` at 100% and 125% display scaling, on both monitors.

---

## 6b. Feature S: scrap clips in the Library

To **scrap** a clip is to throw it away. It leaves the Library, it can never be posted, the agents learn from it, and its files are deleted after a grace period. Until then you can restore it.

### Now
- The Library (`apps/desktop/src/screens/LibraryScreen.tsx`) is a card grid with filters. A single click opens a clip. There is no selection, no context menu (UI.md §2 promises "right-click a clip → Approve, Reject, Edit, Re-cut, Open source at timestamp, Copy link") and no way to remove anything.
- Clip detail (`ClipDetailScreen.tsx`) has only Edit and Open source.
- The only way to drop a clip is Reject inside a review batch. That keeps the files and keeps the clip in the Library.
- Evidence from the live data is §1.15.
- Files a clip owns, all built from its id and version:
  - `previews/clip_<id>_v<n>.mp4`, `.jpg`, `_discord.mp4`
  - `clips/clip_<id>_v<n>_final.mp4`
  - `work/clip_<id>_v<n>/`, `work/clip_<id>_v<n>_final/`, `work/frames_clip<id>/`, `work/sheet_clip<id>/`
  - Older versions are never removed.

### S1. Rules (enforced in the service, not just the UI)
New status `scrapped` in `ClipStatus`. Implement in `LibraryService.scrap(ids, *, reason, include_variants, cancel_posts, by, via)` in a new `core/clipper/services/library.py`, wired into `Core` like the other services.

| Clip state | Can scrap? | What happens |
|---|---|---|
| `draft`, `rendering`, `ready`, `failed`, `in_review`, `approved`, `final`, `rejected` | yes | Its queued and running render jobs are cancelled (B3 `cancel_running`). A `Review` row is written or updated: decision `rejected`, reason `scrapped: <reason>`, `via` dashboard or discord. A pending clip in a batch therefore no longer holds the batch up. The previous status and decision are kept in `scrap_json` for restore |
| has a `scheduled` post | only with "Cancel its posts" checked | the posts are cancelled first (`PublishingService.cancel`, `by="user"`) |
| an upload is running (`posting`) | no | "An upload of this clip is running. Try again when it finishes." |
| posted (any `live` or `simulated` post) | no | its records feed submissions and earnings. Offer **Hide from Library** instead (a `hidden` flag; files follow normal retention) |
| an agent holds the edit lock (`Edl.locked_by = "session:N"`) | yes | the user takes the lock first, the same as Take over. The agent's next edit op fails with "clip <id> was scrapped by the user" |
| has hook variants (`variant_of = id`) | yes | the dialog offers "Also scrap N variants", checked by default |

Safety rules in code, so a scrapped clip can never be published:
- The `approval` rule (`agents/hooks.py`), `schedule_post_tx` (`services/posting.py`) and the due-post runner (`PublishingService.run_due`) all refuse a clip whose status is `scrapped`. The rejected review decision covers this too; the explicit status check is a second lock.
- `EdlService.apply/undo/render` refuse a scrapped clip.
- `media.make_clip` refuses a moment whose clip the user scrapped, unless a user note for the campaign asks for it. Add a `moment.scrapped` flag, with the tool error "The user scrapped a clip of this moment; pick a different moment."

### S2. The agents learn from it
- The confirm dialog has an optional reason: Weak hook · Bad framing · Off-brief · Duplicate · Bad source · Other (free text).
- Event `clip.scrapped {clip_ids, campaign_id, reason, by, via}`. The router (`supervisor/router.py`) sends a P2 campaign request only while the campaign is `active` or `ending` (merged like other events). `messages.describe()`: "The user scrapped clips 3, 4 (reason: weak hook). Don't re-cut those moments; adjust your picks."
- `state.get_learning_examples` and the approval-rate insights already read rejected `Review` rows, so scraps count as rejections with their reason. Check that the `scrapped:` prefix reads well in the examples.
- Not in this plan: an agent tool to scrap its own drafts. Agents could later clean up clips that failed QA, but that needs its own guard (only unreviewed clips the agent made).

### S3. Grace period, restore and purge
- Files stay on disk for `retention.scrapped_clip_days` (default 7) after a scrap.
- **Restore** within that time puts back the previous status and review decision from `scrap_json`, clears `moment.scrapped` and publishes `clip.restored`.
- **Purge**: a daily job (supervisor tick, once per local day; the first piece of the retention job in HANDOFF §5.2) deletes the files listed in "Now" for clips scrapped longer than the grace period, all versions included. It keeps the thumbnail `.jpg` (about 50 KB) so the Scrapped view still shows something, sets `files_purged_at` and publishes `clip.purged`. The rows stay, for history and learning. After a purge, Restore is refused with "This clip's files were deleted."
- **Delete files now** in the Scrapped view purges the selected (or all) scrapped clips at once, behind a confirm that shows the total size.
- The purge deletes only paths it builds from the clip id under `core.dir("previews"|"clips"|"work")`, and checks `is_relative_to` before each unlink. It never uses a path stored in the database as-is. It never touches source videos (those belong to the HANDOFF §5.2 retention job) or posted clips.

### S4. API (`routes.py` `library` router; every write uses `actor="user"` and `via`)
- `POST /api/library/scrap/preview {clip_ids}` → per clip `{id, can_scrap, blocked_reason, scheduled_posts, in_batch, editing_by, variants, bytes}`, plus totals. The confirm dialog is built from this.
- `POST /api/library/scrap {clip_ids, reason?, include_variants = true, cancel_posts = false}` → `{scrapped: [id], refused: [{id, reason}], bytes}`. Up to 500 ids in one writer transaction.
- `POST /api/library/restore {clip_ids}` → `{restored, refused}`.
- `POST /api/library/purge {clip_ids? , expired_only = false}` → `{clips, files, bytes}`.
- `POST /api/library/hide {clip_ids, hidden}`: for posted clips.
- `GET /api/library/cleanup` → suggested groups (S5).
- `ClipRow` gains `scrapped_at`, `scrap_reason`, `purge_at`, `files_purged`, `hidden` and `bytes`. `GET /api/library` gains `include_scrapped` and `include_hidden` (both off by default).

### S5. UI (frontend-design skill, shadcn MCP for `context-menu`, `dialog`, `checkbox`, `radio-group`; utility style)
**Library**
- **Selection works like Explorer**:
  - Click selects; double-click or Enter opens. This changes today's single-click open, to match the data-grid rules in UI.md §1.
  - Ctrl+click and Shift+click add to the selection; Ctrl+A selects every clip shown; Esc clears.
  - Selected cards use `ClipCard`'s existing `selected` outline.
  - The title row says "3 selected".
- **Toolbar**: when something is selected, "Scrap (3)" (shortcut Delete) and "Open". In the Scrapped view, "Restore (3)" and "Delete files now". Always "Clean up…".
- **Context menu** on a card:
  - Open, Edit, Review (if in a batch), Open source at timestamp, Copy link.
  - Then Scrap… (or Restore when scrapped) and Hide from Library (posted clips).
- **Confirm dialog**:
  ```
  ┌ Scrap 3 clips? ─────────────────────────────────────────────┐
  │ Clip 3  ready     weak hook…                                 │
  │ Clip 4  ready                                                 │
  │ Clip 9  posted    Can't scrap a posted clip. Hide it instead. │
  │ Reason (optional)  (•) Weak hook ( ) Bad framing ( ) Off-brief │
  │                    ( ) Duplicate ( ) Bad source ( ) Other [__] │
  │ [x] Also scrap 2 hook variants                                │
  │ [ ] Cancel 1 scheduled post                                   │
  │ Files are deleted after 7 days. You can restore them until then.│
  │                               [Scrap 2 clips]  [Cancel]        │
  └──────────────────────────────────────────────────────────────┘
  ```
  The primary button counts only the clips that can actually be scrapped. Blocked rows show their reason in muted text.
- **Undo**: after a scrap, an info bar under the toolbar says "2 clips scrapped. [Undo]" for 15 s. No toast. Ctrl+Z does the same while the Library has focus.
- **Status filter**: built from the real `ClipStatus` values (a shared constant with a test against the backend enum; fixes §1.15), plus "Scrapped" and "Hidden". "Any status" leaves scrapped and hidden clips out.
- **Scrapped view**: cards are greyed with a "Scrapped" badge and "Deleted in 5 days" (or "Files deleted"). Hover-play is off once the files are purged.
- **Clean up…** dialog: groups with a count and size each, a checkbox per group and a total.
  - "Unreviewed clips of ended or skipped campaigns": today, campaign 2's 8 clips, about 130 MB with work folders.
  - "Rejected more than 14 days ago".
  - "Failed renders".
  - "Old versions": render files of versions that aren't current. This deletes files only and keeps the clips; the EDL history stays and Edit re-renders on demand.
  - Buttons "Scrap 8 clips and free 130 MB" and "Cancel".

**Elsewhere**
- Clip detail: toolbar "Scrap clip" (Delete), or "Restore" for a scrapped clip. A scrapped clip shows a banner: "Scrapped 2 days ago (weak hook). Files are deleted in 5 days. [Restore]". Edit opens scrapped clips read-only with the same banner.
- Campaign drawer, Clips tab: not done (the Library is where you select and scrap).
- Review: not done (Reject stays the way to drop a clip while reviewing; scrap it from the Library).
- Discord: the relay (`apps/bot/clipper_bot/relay.py`) edits a scrapped clip's message in its review thread to "Scrapped by <user>" and disables its buttons (`discord_ref` kind `clip_message`). Discord needs no Scrap button; Reject is there.
- Gallery fixtures: card states (selected, scrapped, purged, hidden), the confirm dialog with blocked rows, the Clean up dialog, the info bar.
- Copy: "Scrap clip", "Scrap 3 clips", "Restore", "Delete files now", "Hide from Library", "Clean up…". No "successfully" or "!".

### S6. Tests
- Rules table: each clip state gives the right `can_scrap` and reason. Scheduled posts are cancelled only with the flag. `posting` and posted clips are refused.
- Safety: a scrapped clip can't be scheduled (guard rule and `schedule_post_tx`), its edit ops and renders are refused, and `make_clip` on a scrapped moment is refused.
- A pending clip in a batch becomes rejected and the batch can ship.
- Restore within the grace period brings back the status and decision. After a purge, restore is refused.
- Purge with a fake clock and a temporary data dir deletes exactly the expected files, keeps the thumbnail, never deletes outside the data dirs or any source file, and running it twice changes nothing.
- Router: `clip.scrapped` gives a P2 campaign request only for active or ending campaigns. Check the describe text.
- Clean up groups on the seeded fixtures.
- vitest: the selection model (click, Ctrl, Shift, Ctrl+A, Esc), Delete opens the dialog, Undo restores.
- e2e (fixture build): select two cards, press Delete, confirm, the cards are gone; switch to Scrapped, Restore, they're back.
- Screenshots in dark and light at 1280×800 and 1920×1080, including the Library with a selection and both dialogs.

---

## 7. Critic's review: more fixes and improvements

Found by using the live app and reading the code. They are grouped by type, and each has a milestone.

### Correctness
| # | Problem (evidence) | Fix | Where | M |
|---|---|---|---|---|
| 7.1 | Options cut at 80 characters mid-word (§1.3) | `ask_user` rejects options over 60 characters with a clear error for the agent ("keep options short; explain in the question text") instead of cutting them; the DB keeps up to 200; Discord uses option indexes (A4) | `services/notify.py:51`, `tools/notify.py`, `prompts/shared.md` | M0 |
| 7.2 | Stale open questions (§1.7) | when a campaign becomes `ended`/`skipped`, close its open questions (status `closed`, answer "(campaign ended)"); a default timeout of 48 h moves an unanswered question into the urgent group rather than auto-answering it | `services/campaigns.py`, `services/notify.py` | M0 |
| 7.3 | `needs_user` campaigns show Take/Skip; join state ignored (§1.8) | C5 | `CampaignsScreen.tsx:157`, `services/market.py:124` | M2 |
| 7.4 | Failure rows never clear and have no actions (§1.6) | A1 unresolved-only rule; Retry/Dismiss/Open | `views.py:338` | M1 |
| 7.5 | Skipping a campaign that has a live post with no submission drops its payout without warning (campaign 2 is `skipped` with post 1 live and not submitted) | Skip shows a confirm: "1 live post isn't submitted yet. Skipping stops the submission." Choices: "Skip and keep submitting" (finish mode), "Skip anyway", "Cancel" | `services/campaigns.py`, Campaigns drawer and grid | M2 |
| 7.6 | "Turns 85 / 80" mixes the total with the per-run limit (§1.12) | Show "This run 6 / 80 · total 85"; track `turns_this_run` from the running request | `views.py:723`, `AgentsScreen.tsx:151` | M4 |
| 7.7 | Recipe failures have no screenshot (§1.13) | After §5.5 (own window), check `captureVisibleTab(windowId)` on a hidden window. If it still returns nothing, store the simplified DOM excerpt the runner already builds and show it in the expanded item | `apps/extension/src/background/runner.ts`, `driver.ts`, `services/publishing.py` | M3 |
| 7.8 | Window enumeration can block the status endpoint (§1.14) | §5 fix 3; also take the lock only around state changes and read cached state without it | `browser/windows.py`, `browser/manager.py` | M0 |
| 7.9 | Leases outlive dead sessions for up to 3 h (`LEASE_TTL_S`) | Each tick, release `campaign:*` leases whose holder isn't in `_running` (logged) | `supervisor.py` | M4 |
| 7.10 | Async subagents are abandoned when the turn ends (§1.11) | Check the SDK options for background agents and turn them off for our sessions. If there's no option, deny `run_in_background` in the PreToolUse hook for the Agent tool, so subagents run inline. B1 `waiting_on_nothing` catches anything left | `agents/definitions.py`, `agents/hooks.py` | M4 |

### UX
| # | Problem | Fix | M |
|---|---|---|---|
| 7.11 | Health rows look like links but do nothing | Each row opens its fix: Extension → profiles popover, Discord → Settings → Discord, GPU → Jobs tab, Vyro/Whop → "Show browser" for the login, Disk → data folder | M1 |
| 7.12 | Output panel "Problems" and Needs you disagree | Problems lists the same unresolved items (A1) plus guard blocks; clicking one opens Overview with `?item=` | M1 |
| 7.13 | "Accounts: none match" on every campaign, with no reason | Tooltip with the reason ("No account has the niche tags <tags>"), linking to Publishing → Accounts | M2 |
| 7.14 | The Director chat is squeezed to one line on Agents at 1280×800 | Put chat and transcript in a resizable splitter (`components/ui/splitter.tsx`), with chat collapsible to its input row | M4 |
| 7.15 | Toasts don't lead anywhere | Clicking a toast (where the notification plugin supports it on Windows; LOCAL-VERIFY) brings the main window forward and opens `?item=<key>`. Otherwise the toast body says where to look | M1 |
| 7.16 | Timeouts are hidden inside detail text (regex at `attention.tsx:47`) | A real `timeout_at` field (A1) shown in its own column and in the expanded facts | M1 |
| 7.17 | The browser state is easy to forget ("Browser shown" in the status bar while Chrome sits on the portrait monitor) | The status bar segment turns amber when the browser has been shown for more than 30 min with no recipe running, and offers "Hide browser" | M6 |
| 7.25 | The Library has no selection or context menu, although UI.md §2 promises right-click actions on a clip; the status filter lists statuses that don't exist (§1.15) | S5 | M2b |

### Reliability and operations
| # | Problem | Fix | M |
|---|---|---|---|
| 7.18 | No progress or cancel for running jobs; 6 h download timeout | B3 | M4 |
| 7.19 | yt-dlp is out of date and nothing says so | 6.5 doctor and update button | M0 |
| 7.20 | Status endpoint does heavy work every poll | A2 caching | M1 |
| 7.21 | Retention and backups still aren't built (HANDOFF §5.2); 1.4 GB per source on C: | Not in this plan. Keep it next in line after M3, because F makes it easier to fill the disk (users drop big files) | — |

### Agent behavior (prompts and tools)
| # | Problem | Fix | M |
|---|---|---|---|
| 7.22 | Footage problems arrive as free-text questions | `media.need_footage` (6.1) | M3 |
| 7.23 | Slug "mismatch" read as a wrong link | prompt note (C4) | M2 |
| 7.24 | Questions with long options | prompt rule plus validation (7.1) | M0 |

---

## 8. New settings (`core/clipper/settings.py`, `config/settings.example.toml`; the test-enforced example lists every key)
```toml
[stalls]
session_quiet_min = 10        # running session with no agent events
idle_min = 30                 # campaign waiting on nothing → Needs you
request_blocked_min = 5
job_quiet_min = 15            # analyze uses 2× this
auto_restart_hung_min = 30    # 0 = off
auto_retry_stalled_job = true
max_auto_nudges = 2

[media]
downloads_dirs = []           # empty = %USERPROFILE%\Downloads
ytdlp_max_age_days = 60

[marketplaces.whop]
app_url = "https://b4e0vdqv6zgqeqj4pfgm.apps.whop.com/c/exp_zeADOv9rOOKk2x"

[ui]
open_marketplace_links_in = "clipper"   # or "default"

[retention]
scrapped_clip_days = 7        # files of scrapped clips are deleted after this; 0 = at once
```
Settings dialog: "Stalls and nudges" goes under Agents, with the thresholds in a property grid and checkboxes for the automatic actions. "Open marketplace links in" goes under General. "Downloads folders" goes under Media and captions. "Delete scrapped clip files after N days" goes under Backups.

## 9. Database changes (migration `0003_attention_stalls_links.py`, `render_as_batch`)
- New table `attention(key TEXT PK, state TEXT, snoozed_until DATETIME NULL, note TEXT NULL, by TEXT NULL, updated_at DATETIME)`.
- `job.progress_at DATETIME NULL`, `job.detail TEXT NULL`.
- `agent_request.waiting_reason TEXT NULL`.
- `campaign.link_status TEXT DEFAULT 'unknown'`, `campaign.link_checked_at DATETIME NULL`.
- `source.waiting_since DATETIME NULL`, `source.reason TEXT NULL`. New status value `needs_footage` in `SourceStatus` (plain string column, no enum migration). Also add `skipped`.
- For scrapping (S): `clip.scrapped_at DATETIME NULL`, `clip.scrapped_by TEXT NULL`, `clip.scrap_reason TEXT NULL`, `clip.scrap_json JSON` (previous status and review decision), `clip.files_purged_at DATETIME NULL`, `clip.hidden BOOLEAN DEFAULT 0`, `moment.scrapped BOOLEAN DEFAULT 0`. New status value `scrapped` in `ClipStatus`. If `0003` has already shipped by the time M2b starts, put these in `0004_clip_scrap.py`.
- The existing models/migration drift test must pass. Regenerate `openapi.json`, the TS client and the fixture export (`just gen-api`).

New events (`events/types.py`): `attention.changed`, `user.nudge`, `nudge.sent`, `campaign.joined`, `source.attached`, `source.needs_footage`, `clip.scrapped`, `clip.restored`, `clip.purged`. Each needs a `describe()` line (core `messages.py` and UI `describe.ts`) and a `keysFor` mapping.

## 10. Order of work

Each milestone ends with `just lint`, `just test`, the e2e run and the screenshot routine (dark and light, 1280×800 and 1920×1080, compared with UI.md). Commit after each one.

**M0. Hotfixes (H1–H5, 7.1, 7.2, 7.8, 7.19)**
- Needs you grid layout: the question text is visible and actions never overflow. Collapsed rows only; the expansion comes in M1.
- Option validation (the Discord bot already sent option indexes, not option text, so it needed no change).
- Drop-folder rules (6.6) and fixture isolation, then the cleanup in 6.7 (by hand).
- `clean_ytdlp_error`, the yt-dlp age warning and the update button.
- Chrome window fixes from §5, steps 1–6 (step 7, pop-outs, is in M6).
- Close questions when their campaign ends.
- Done when §1.1, 1.2, 1.3, 1.4, 1.5, 1.7 and 1.14 can't be reproduced: `test_clipper_chrome_show_paints` passes 20 out of 20, old drop-folder files are ignored, and the status bar keeps updating while Chrome is busy.

**M1. Expandable Needs you (A)**
- A1–A3: keys, the detail endpoint, the `attention` table, reply routing, the expanded UI for the existing kinds, and alert and failure items.
- 7.11, 7.12, 7.15, 7.16, 7.20.
- Done when every kind expands in the gallery and the e2e "answer in your own words" flow passes.

**M2. Campaign links (C)**
- `links.py`, `/api/browser/open`, links on every surface, link status, the join flow, the Whop app URL setting, 7.5 and 7.13.
- Done when every campaign row has a link, the Whop deep link is verified on the live site (LOCAL-VERIFY), and the join flow works end to end in dry run.

**M2b. Scrap clips in the Library (S)**
- S1–S6: the `scrapped` status and safety checks, `LibraryService`, the API, Library selection, context menu, confirm dialog, Undo, Scrapped view, Clean up, the daily purge, clip detail, drawer and Review entry points, the Discord message update, and 7.25.
- Uses B3's `cancel_running` for render jobs. If M4 hasn't landed yet, scrapping a clip whose render is running is refused with "A render of this clip is running", and queued renders are cancelled with the existing `JobQueue.cancel`.
- Done when campaign 2's 8 unreviewed clips can be scrapped in one go from Clean up, restored with Undo, and purged after the grace period (fake clock test), and a scrapped clip can't be scheduled.

**M3. Footage and drag-and-drop (F)**
- 6.1–6.5: `need_footage`, the expanded footage item, `filedrop.ts`, Browse (dialog plugin), candidates, the import job, host classes, 7.7 and 7.22.
- Done when dropping the real Frame.io file onto campaign 1's item imports it with progress, analysis runs and the agent resumes. Check it in `just dev-app` at 100% and 125% scaling.
- As built (differences from the design above):
  - The campaign agent's tool list was already at the 25-tool limit, so `state.get_clip` moved to its subagents (editor, qa-checker and copywriter already have it) to make room for `media.need_footage`.
  - `need_footage` is checked in the tool, not the guard: the guard only knows `campaign_id`, `clip_id` and `post_id`, so the tool refuses a source of another campaign.
  - The item shows the source link (default browser), "Copy link", the drop box, "Choose file…", the paste field, recent downloads, the move/copy checkbox, the drop folder with "Open folder", and Retry/Skip. A file that looks wrong (under 60 s, or under the spec's minimum, or without audio) is shown back before it is used.
  - Not done: "Open in Clipper browser" for source links (`/api/browser/open` only opens sites Clipper works with), the Google Doc link list, dimming every zone while you drag, the confirm for a drop outside any zone, the aspect-ratio warning, and turning a refused drop-folder file into a footage item (it is still one alert, mentioned once; the same file shows under Recent downloads). Recipe failure screenshots (7.7) move to M6.

**M4. Stalls and nudges (B1–B3, B5)**
- The detector, the nudge API and events, job progress/heartbeat/cancel, the UI on every surface, 7.6, 7.9, 7.10 and 7.14.
- Done when each stall kind can be produced on purpose (a hung fake runner, a stalled dummy job, a lease held by a dead session) and cleared from Needs you with one action.
- As built (differences from the design above):
  - The detector has seven kinds. `recipe_stuck` has no in-flight recipe record to look at, so it means "a post has been in `posting` for 10 minutes". A running turn counts as hung when the newest `agent_event` of its session is older than `stalls.session_quiet_min`.
  - Jobs report through `ctx.progress`, `ctx.detail` and `ctx.beat` (liveness without a percentage); `progress_at` is what the detector reads. A job's subprocesses are registered through a context variable (`system.PROCESS_REGISTRAR`) and `run_cancellable`, so ffmpeg and WhisperX are killed with the job (`taskkill /T /F`); the face-tracking ffmpeg and the OCR calls are not (they are short). yt-dlp streams its progress through a template (`parse_progress`, tested on a recorded sample).
  - `cancel_retry` allows at most 3 retries per input. When the job's process is gone (the app restarted) the row is closed by hand.
  - `restart_turn` interrupts the turn, waits 10 s, then cancels the task; the request ends failed with "interrupted by your nudge", the lease is released and a nudge follows.
  - A nudge to Scout, Analyst or the Director starts a fresh run at P0 (P2 for an automatic one). Your words on a stuck item are the nudge's message.
  - 7.10: the guard refuses `run_in_background` on the Agent tool (rule `foreground_subagents`), and `campaign.md` says to start subagents together in the foreground.
  - 7.14: the Director chat can be folded down to its input row, and the pane keeps at least 16%.
  - Settings → Agents has "Stalls and nudges" (the thresholds and the two automatic actions; the automatic checks themselves are M5).
  - Not done: a right-click "Nudge" on the Overview campaigns table (the Campaigns grid has it), the Discord nudge, and the automatic checks (M5).

**M5. Automatic nudges and Discord (B4, A4's "Other…" modal, Discord parts of B5 and C3)**
- Done when an automatic restart happens once, escalates after `max_auto_nudges`, and Discord can nudge and send a custom answer.
- As built:
  - `supervisor/auto.py` runs from the supervisor tick (not while paused or with the kill switch on). A hung turn is restarted once it has been quiet for `auto_restart_hung_min`; a stalled job is cancelled and retried when `auto_retry_stalled_job` is on; each stall gets at most `max_auto_nudges` automatic actions, counted in `kv` and forgotten after 6 hours without the stall. An automatic action that is refused (a job already retried three times) counts as spent. When the actions are used up, or the stall has none (a request that can't start, a late post), Clipper raises one alert (`source = "stalls"`, with the stall's key), which Discord shows with the stall's buttons. Needs you does not list that alert again: the stuck item stands for it.
  - Discord: question messages have an "Other…" button with a modal (500 characters) that answers in your own words; `/clipper nudge <campaign> [message]` (autocomplete from the running campaigns, or the campaign's number); stall alerts carry up to two buttons (restart turn, run now, release lease, cancel and retry).
  - Found on the way: the relay never re-drew a question message after it was answered, because the bot's `question()` only looked among open questions. It looks at all of them now.
  - Tests that change settings use `tune(core, section, ...)` (it replaces the section with a copy): changing the shared default in place leaked into the fixture export test.

**M6. Polish**
- 7.17, the pop-out show-when-ready (§5.7), and a review pass against UI.md.
- Update UI.md §3.1 (Needs you expansion, kinds, keys), §3.2 (Nudge popover, no Resume/Fork), §3.3 (link column, join), §3.4 (Library selection, context menu, Scrap, Clean up, Scrapped view), §5 (new components: `NeedsYouDetail`, `FileDropZone`, `NudgeMenu`, `LinkRow`, `ScrapDialog`, `CleanupDialog`) and §6 (new keys: Delete and Ctrl+Z in the Library, Ctrl+A to select all).
- Update HANDOFF §5 and §6.
- As built: a pop-out window is created hidden with the theme's background and shows once its page has drawn two frames (`popout_ready`), or after 2 s if the page never answers (7 in §5); the status bar says "Browser shown for N min · hide" after 30 minutes (7.17; it can't tell whether a recipe is running, so it doesn't look); UI.md §3.1–3.4, §5 and §6 and HANDOFF §4–§6 are updated; all screenshots are regenerated and reduced to a 256-colour palette (pngquant isn't installed, so a small Pillow script did it).
- Also fixed on the way: the navigation's Library count included scrapped and hidden clips; a campaign whose posts are still tracked for payouts is no longer called "waiting on nothing"; `tsc --noEmit` alone checks nothing in this repo (use `tsc -b --noEmit`, the `typecheck` script).

## 11. LOCAL-VERIFY rows to add to HANDOFF §4
| What | How | Expected |
|---|---|---|
| Chrome shows painted | `just local-verify` (`test_clipper_chrome_show_paints`); manual steps in §5 | never a flat dark window; status bar stays live |
| Whop deep link | open a Whop campaign's link from the grid | lands on that campaign in the Clipper Chrome (verified by probe on 2026-10-05) |
| Vyro link | same for Vyro | the campaign dialog opens (verified by probe on 2026-10-05) |
| File drop | drag a video from Explorer onto a footage item at 100% and 125% scaling, on both monitors | the right zone lights up; import runs with progress |
| yt-dlp progress | download a long YouTube source | Jobs shows bytes, speed and time left; Cancel kills yt-dlp |
| Toast click | trigger an alert, click the toast | the main window opens on that item (or the limitation is noted) |

## 12. Out of scope, and questions for the user
- Out of scope:
  - Downloading Frame.io/WeTransfer automatically through the Companion (a `frameio.download` recipe using `chrome.downloads`). Possible later, but it needs the `downloads` permission and a verified recipe.
  - An in-app upload endpoint for the browser build. The desktop app has file paths, so it isn't needed.
  - Retention and backups (HANDOFF §5.2).
- Questions:
  1. Should "Open on Vyro/Whop" use the Clipper browser by default (recommended: it's the one that's logged in) or your normal browser?
  2. Should auto-restarting a hung agent turn (B4.2) be on by default, or only appear in Needs you?
  3. For files from Downloads, should Clipper move them into `C:\ClipperData\sources` (no duplicate on disk) or copy them (leaves your Downloads untouched)? The plan asks each time and remembers the choice.
  4. Is 7 days the right grace period before a scrapped clip's files are deleted? Setting it to 0 deletes them right away, and then Undo only works until the next purge run.
