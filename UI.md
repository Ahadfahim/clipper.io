# Clipper.io — UI Outline

Companion to [PLAN.md](PLAN.md) §8. **Installed Windows desktop software**, not a web app: one installer (`.msi`/`.exe`), its own window, tray icon, starts with Windows, no browser and no website involved. Built with Tauri v2: a Rust shell around the system's built-in WebView2 renderer, with React drawing the UI, so it ships as a ~10 MB native program.

Prototypes: [Clipper.io theme prototypes](https://claude.ai/artifact/DdWqpUC3FyG5k77Ysiq1Qp), on the "Utility" page.

---

## 1. Design direction: utility style

**It should look like a Windows power tool** (think Process Explorer, OBS, Everything, PowerToys, a DAW mixer), not a SaaS dashboard. The agents do the work; you supervise, approve and steer. So the screens are built around three questions, in this order:
1. **What needs me right now?** (reviews, challenges, campaign picks)
2. **What are the agents doing?** (live activity, Claude usage)
3. **Is it making money?** (earnings, views, approval rates)

| Element | Choice |
|---|---|
| Window | **Native Windows frame** (Tauri `decorations: true`) with Mica backdrop on Windows 11; snap layouts, standard min/max/close; minimum 1200×760; remembers size, position and pane sizes |
| Structure | **Menu bar → toolbar → panes → docked output panel → status bar.** Resizable splitters between panes; panes can be collapsed |
| Navigation | **Tree view** on the left (Overview, Agents with each running session, Campaigns by marketplace, Library, Review, Publishing by account, Earnings, Settings), with counts right-aligned |
| Data | **Data grids** everywhere (sortable columns, resizable, multi-select, right-click context menus, Ctrl+C copies rows). No big cards or dashboard tiles |
| Detail | **Property panes** (label/value grids) instead of decorated detail views |
| Settings | A real **Settings dialog** (section list on the left; OK / Cancel / Apply), not a settings page |
| Theme | **Follows Windows light/dark** and the **Windows accent color**; can be overridden in Settings. Neutral grays; color only for status |
| Status colors | Small dots and text only: green = healthy/approved/live · yellow = waiting on you/warning · red = blocked/failed/rejected · accent blue = selected/primary · violet = Claude agent activity |
| Type | **Segoe UI Variable** (Windows system font) at 12px for UI; **Cascadia Mono** for numbers, times, IDs, logs, tool names |
| Density | Compact: 26–30px rows, 28px buttons, 4px corners. A "comfortable" density option in Settings |
| Controls | Native-looking: checkboxes, radio buttons, fieldsets with legends, dropdowns, underline-style text fields. Toggles appear as checkboxes, not pill switches |
| Motion | Almost none: progress bars move, live rows appear. No animations for decoration |
| Icons | Fluent-style outline icons (Fluent UI System Icons), 16px |

---

## 2. Main window shell

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ✂ Clipper — Overview                                                        ─  ▢  ✕  │ ← native title bar
│ File  Edit  View  Agents  Campaigns  Tools  Help                                      │ ← menu bar
│ [⏸ Pause all] ☑ Dry run │ Scout now  Review queue (12)  Ship approved │ Sources ☑Vyro ☑Whop  Post to ☑YT ☑TT ☑IG ☐X   [Search… Ctrl+K] │ ← toolbar
├──────────────┬───────────────────────────────────────────────────────────────────────┤
│ ▸ Overview   │                                                                       │
│ ▾ Agents 3/4 │                      document area                                    │
│    Campaign… │       (grids, property panes, preview, timeline)                      │
│ ▾ Campaigns 5│                                                                       │
│    Vyro    2 │                                                                       │
│    Whop    3 │                                                                       │
│   Library 214│                                                                       │
│   Review   12│                                                                       │
│ ▾ Publishing │                                                                       │
│   Earnings   │                                                                       │
│   Settings   │                                                                       │
├──────────────┴───────────────────────────────────────────────────────────────────────┤
│ Activity │ Agent output │ Jobs (5) │ Problems (1)                                     │ ← docked output panel
│ 14:32:07  campaign/night  Rendered 6 clips · queued QA                                │
│ 14:30:51  guard           Blocked publish.schedule_post · clip 31 not approved        │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ ● Running │ ● Dry run │ ● Agents 3/4 │ ● GPU 62% · 5 jobs │ ● Claude usage 38% · resets 2h14m │ ● Extension 2 │ ● Discord │ Today $48.20 │ ← status bar
└──────────────────────────────────────────────────────────────────────────────────────┘
```

- **Menu bar:** every action is reachable from a menu with its shortcut shown (File · Edit · View · Agents · Campaigns · Tools · Help). Agents menu: Pause all, Resume, Interrupt session, Dry run, Slot count. Tools: Run scout, Clipper doctor, Open Chrome profile, Open data folder.
- **Toolbar:** Pause all, **Dry run** checkbox, Scout now, Review queue (count), Ship approved, then the **on/off checkboxes for marketplaces (Vyro, Whop) and socials (YouTube, TikTok, Instagram, X)** (PLAN §15), and the search/command box.
- **Dry run on** also adds a thin yellow bar under the toolbar so it's impossible to miss.
- **Stop everything:** `Agents → Stop all` (Ctrl+Shift+Esc-style confirm dialog) and the tray menu. No hold button needed in a native app; a confirm dialog is the Windows convention.
- **Tree (left):** the navigation. Selecting a node opens it in the document area. Running agent sessions appear under Agents; accounts appear under Publishing with their status ("paused" in yellow).
- **Docked output panel (bottom, `Ctrl+J`):** tabs for **Activity** (human-readable feed), **Agent output** (raw tool calls), **Jobs** (GPU/download queue with progress), **Problems** (errors and blocked actions). Like the output pane in an IDE.
- **Status bar:** live health at a glance. Each segment is clickable (e.g. Claude usage opens the pacing popup; Extension opens the profiles list).
- **Search / command box** (`Ctrl+K`): jump to any campaign or clip, run any menu command, or type `>` to message the Director.
- **Context menus everywhere:** right-click a clip → Approve, Reject, Edit, Re-cut, Open source at timestamp, Copy link. Right-click a campaign → Pause, Open brief, Open in browser, Skip.
- **Notifications:** Windows toast notifications ("12 clips ready for review", "TikTok account needs you", "Usage limit reached, resuming at 16:10"). No in-app toast clutter.
- **Tray icon:** Open · Pause all / Resume · Dry run · today's stats · Quit (warns if uploads are in progress). Closing the window minimizes to tray; the agents keep running.
- **Multiple windows:** Review and Edit can be **popped out into their own windows**. The user's setup is a 3440×1440 ultrawide plus a **1080×1920 portrait monitor**: the main window is laid out for the ultrawide (wide grids, panes side by side), and the pop-out Review window has a **portrait layout** (full-height 9:16 player on top, clip list and properties below) that fills the portrait monitor. Windows remember which monitor they were on.

---

## 3. Pages

> Every page below lives in the document area of the main window shell (§2): grids instead of cards, property panes instead of detail cards, and the Settings page is a dialog. The layouts sketched below show content and behavior; their visual treatment follows §1.

### 3.1 Home — "what needs me"
```
┌ Needs you (3) ───────────────────────────────────────────────┐ ┌ Health ────────┐
│ ⚠ TikTok @clipsdaily paused: verification needed  [Open window]│ │ ● Extension ×2 │
│ ✓ 12 clips ready: MrBeast #42 · Source 1          [Review]    │ │ ● Discord bot  │
│ ◎ New campaign: Ali Abdaal, score 81, $3 CPM      [Take][Skip]│ │ ● GPU worker   │
└──────────────────────────────────────────────────────────────┘ │ ● Vyro  ● Whop │
┌ Earned today ┐┌ Views today ┐┌ Clips posted ┐┌ Usage ┐┌ Find→post ┐│ ● Disk 412 GB  │
│ $48.20 ▲12%  ││ 16.1k       ││ $6.10/$25   ││ 7.9×││ 3h 40m    │└────────────────┘
┌ Active campaigns ────────────────────────────────────────────────────────────────┐
│ MrBeast #42   Brief●Sources●Analyze●Clips●Review◐Post○   Budget ████░░ runs out ~2d │
│ Ali Abdaal    Brief●Sources◐ ...                          Budget ██████ runs out ~9d │
└──────────────────────────────────────────────────────────────────────────────────┘
┌ Next 24h posts ───────────────── (timeline strip per account) ──────────────────┐
```
- The **Needs you** list is ranked by urgency: blocked accounts first, then review batches nearing their timeout, then campaign picks, then failures. Each row has its action right there.
- Each campaign row shows a **marketplace badge** (Vyro / Whop), a **stage progress bar**, and a **budget bar** with a marker for when it's predicted to run out.
- Earned-today tile shows a split by marketplace on hover.
- **Agent questions** (`notify.ask_user`) appear here with their answer buttons, e.g. "Rules unclear: can we use the trailer footage? [Yes] [No] [Skip campaign]". Answering resumes the agent.
- When nothing needs you, the list says "You're all caught up. Next scout run in 6 min."

### 3.2 Agents — "what are the agents doing"
Three panes, plus a chat box at the bottom:
**Slot board** across the top: each of the agent slots (default 4) with its agent, campaign, current tool and elapsed time. A dimmed slot means the pool has shrunk because Claude usage is high. Next to it is the **queue** of waiting requests with P0–P3 priority, which you can bump or cancel (PLAN §17).

| Sessions (left, 260px) | Live transcript (center) | Context (right, 300px) |
|---|---|---|
| Grouped: **Running** · **Waiting on event** · **Done today**. Each row: role icon, campaign, turns, tokens, last active | A stream of event rows: agent message · **tool call** (name, collapsed input/output, duration, ✓/✗) · **subagent** block (nested and collapsible) · **guard hook blocked** (red, shows the rule that blocked it) · thinking summary (grey italic) | Linked campaign, timeline of events → resumes, turns used vs. `max_turns`, buttons: **Interrupt · Nudge · Resume · Fork** |

- **Director chat** at the bottom: the same conversation as `#control` in Discord. Replies use the serif "Claude voice" font to set them apart from system text.
- Filters: role, campaign, "only errors", "only blocked by rules".
- Each tool call has a **Replay in dry-run** action, for debugging.

### 3.3 Campaigns
- **Table:** marketplace badge (Vyro / Whop) · score (colored chip) · brand/title · CPM · budget bar + runs-out date · deadline · matching account(s) · status · clips posted · earned
- Filter tabs: **Suggested · Active · Ended · Skipped**, plus marketplace chips (**All · Vyro · Whop**) and a content-type filter (clipping / UGC).
- Campaigns from a marketplace that's switched off are greyed out with a "Vyro is off" label.
- Campaigns limited to socials that are all switched off show "No enabled socials". Plus a **Paste campaign URL** button for manual mode
- **Detail drawer** (right, 560px) with tabs:
  - **Overview:** the agent's score breakdown and reasoning; payout terms (CPM, caps, minimum views, tracking window, link/upload); Take / Skip / Pause; **Socials for this campaign** (switches, limited to globally enabled ones)
  - **Brief:** the raw text, under a banner "Written by a third party, treated as untrusted"
  - **Spec:** the ClipSpec as a form you can edit (duration range, required text, banned list, platforms). Saving resumes the Campaign agent with "spec updated"
  - **Sources:** each source with its download/analysis status and the heatmap shown as a sparkline
  - **Clips:** grid filtered to this campaign
  - **Timeline:** every event and agent session for the campaign, in order
  - **Money:** earnings, views and payout status for the campaign

### 3.4 Library
- **Grid** of 9:16 thumbnail cards: score badge, length, status color, platform icons once posted, view count. Plays on hover
- Filters: campaign, status, score range, layout, caption style, posted/not; sort by score / views / date
- **Clip detail** (full page):
  - Left: player with frame stepping
  - Right tabs:
    - **Transcript:** words highlight as the video plays
    - **Why this moment:** the agent's reasoning, plus a **signal timeline** of the whole source (heatmap, energy, scene cuts) with this clip's window highlighted and other moments shown faintly
    - **Versions:** re-cuts compared side by side
    - **Posts:** each platform post with views over time

### 3.5 Review — the main screen you'll work in
```
┌ MrBeast #42 · Source 1 · 7/12 reviewed · ✓5 ✗2      [Approve all ≥ 80] [Ship approved ▸] ┐
├──────────┬──────────────────────────────┬──────────────────────────────────────────┤
│ Queue    │                              │ Score 87 · 0:42 · src 12:31–13:13         │
│ ▣ 92 ✓   │        ┌──────────┐          │ Hook "Nobody tells you this about..."      │
│ ▣ 87 ●   │        │  9:16    │          │ Why: payoff lands at 0:31, heatmap peak    │
│ ▣ 84     │        │  player  │          │ ─────────────────────────────────────────  │
│ ▣ 79     │        │          │          │ Platforms  [YT ✓] [TT ✓] [IG ○]            │
│ ▣ 71 ✗   │        └──────────┘          │ YouTube title  [..................]       │
│ ...      │  ◀▮▮▶  ━━━━●━━━━━━━  0:18     │ TikTok caption [..................]       │
│          │  [trim: |◀━━━━━━━━━━━▶|]      │ Instagram      [..................]       │
├──────────┴──────────────────────────────┴──────────────────────────────────────────┤
│ [A] Approve   [R] Reject ▾   [E] Edit   [C] Re-cut   [Space] Play   [←/→] Prev/next     │
└────────────────────────────────────────────────────────────────────────────────────┘
```
- Platform buttons and caption fields only appear for socials that are **switched on** and allowed by the campaign.
- The queue is sorted by score; ✓/✗/● show the decision so far. **Plays automatically** when you move to a clip.
- **Re-cut** turns on trim handles on a mini timeline (with ±5s of extra source footage visible on each side), plus a layout picker. Submitting sends it to the agent and shows a "re-rendering…" placeholder.
- **Reject** opens a reason picker (bad hook / boring / broken / off-brief / other). The reasons feed the learning loop.
- Approving with `A` moves straight to the next clip, so a batch of 12 takes about 2 minutes.
- **Synced with Discord:** a decision made in Discord appears here instantly, labeled "via Discord".
- Shows the **auto-approve offer** card when the approval history qualifies (PLAN §14).

### 3.5b Edit — watch Claude edit, steer it with notes
```
┌ Clip 31 · MrBeast #42 · v3            ● Claude is editing: removing filler words 0:12–0:19…   [Take over] ┐
├─────────────────────────────┬────────────────────────────────────────┬──────────────────────────┤
│ History                     │            ┌──────────┐                │ Agenda                    │
│ ✦ cold open from 0:31  ↺    │            │  9:16    │                │ Plan (Claude)             │
│ ✦ remove silences (med) ↺   │            │  live    │                │ ✓ Cold open from 0:31     │
│ ● you: trim end −1.2s   ↺   │            │  preview │                │ ✓ Remove silences         │
│ ✦ split-screen 0:20–0:28 ↺  │            └──────────┘                │ ◐ Remove filler words     │
│ ✦ removing fillers…         │                                        │ ○ Captions with emphasis  │
│                             │  ▶ 0:14 ━━━━━━●━━━━━━━━━━━━━━  0:41     │ ○ QA                      │
│                             │  video   ▇▇▇▇ ▇▇▇▇▇ ▇▇▇▇▇▇ ▇▇▇▇        │ ───────────────────────── │
│                             │  camera  [crop ][ split ][ crop  ]     │ Your notes                │
│                             │  captions ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪        │ "Hook shorter" · clip ✓   │
│                             │  overlay [hook]                        │ [Add note… ][clip ▾][Send]│
│                             │  audio   ~~~~~~~~~~~~~~~~~~~~~         │                           │
│                             │         ▲ violet range = Claude working │                           │
└─────────────────────────────┴────────────────────────────────────────┴──────────────────────────┘
```
- **Center:** live preview (proxy video + captions/crop/overlays drawn from the EDL) and a multi-track timeline: video segments, camera layouts, caption words, overlays, audio. While an agent is working, a **violet playhead and range** shows exactly where, and a status line in the header says what it's doing.
- **Left, History:** every edit step (✦ Claude, ● you) with its reason on hover. Click to compare before/after; ↺ undoes.
- **Right, Agenda:**
  - **Plan:** the agent's to-do list for this clip, ticked off live (○ queued · ◐ in progress · ✓ done · ✗ skipped, with the reason).
  - **Your notes:** a text box + scope picker (**this clip / this campaign / always for this creator**). Sending a note goes to the agent at top priority; it replies under the note ("Got it: hook cut to 1.2s") and adds the change to its plan.
- **Take over / Hand back to Claude:** taking over locks the clip to you and turns on manual tools (trim handles, split, layout per range, click a caption word to edit it or mark it for emphasis, style picker). Handing back makes the agent continue from your version.
- **Hook variants:** a strip under the preview shows the 2–3 variants; click to compare, and star the one to post.
- Opened from Review (press `E`), from Library, or from a live notification ("Claude is editing clip 31").
- The **Review** page shows a small "editing live" badge on any clip an agent is changing right now, and its preview updates when the edit lands.

### 3.5c Agenda on Home
A compact **Agenda** card on Home: what the agents plan to do next, in order:
- Queued agent work by priority
- Self-scheduled follow-ups (`wake_me`)
- Scheduled posts in the next few hours

It also has a **global note box** ("Focus on Whop campaigns today", "Don't post on IG until Monday"). Global notes go to every agent at its next run and stay pinned until you clear them.

### 3.6 Publishing
- **Calendar** (week view): one **row per account**; rows for disabled socials or accounts are collapsed and greyed out with their switch shown inline; posts as draggable cards (thumbnail + time). Drag to reschedule; the posting-cap and minimum-gap rules are checked while you drag (red outline when a drop isn't allowed)
- **Accounts tab:** each account card shows:
  - Platform, handle, niche tags
  - Chrome profile, and whether the extension is connected
  - **Warm-up progress** (week 1 → 2 → normal)
  - Posts today vs. cap
  - **On/off switch** and status (active / paused-challenge / off)
  - An **Open Chrome window** button
- **Recipes tab:** health of each upload script (last success, last failure + screenshot), with a **Test in dry-run** button
- **Queue tab:** list of everything scheduled, with Cancel / Post now

### 3.7 Earnings
- **Main chart:** earnings and views per day, split by marketplace
- **Breakdowns:** by **marketplace** (Vyro vs Whop: earned, approval rate, average CPM, payout delay) · by campaign · by social · by account
- **Top clips:** ranked by $ and by views, with a thumbnail. Click to open the clip
- **Unit numbers:** $ per clip, $ per GPU hour, review approval rate, median time from campaign found to first post

### 3.8 Settings
Left sub-nav:
- **Marketplaces and socials** (first in the list):
  - Marketplace cards (Vyro, Whop): big switch · login status + **Log in** button · active campaigns · earned (7d) · approval rate · settings (minimum CPM; Whop: include UGC, join free Whops automatically)
  - Social cards (YouTube Shorts, TikTok, Instagram Reels, X): big switch · connected accounts, each with its own switch · posts today vs. cap
  - Switching something off opens the dialog from PLAN §15.2 (finish/pause campaigns, cancel/keep scheduled posts)
  - **Change log:** who flipped what, when, and from where (app / Ctrl+K / Discord)
- **Automation:** scout mode (suggest/auto + thresholds), review timeout rule, auto-approve tier (only appears once you qualify)
- **Usage pacing:** max turns per session, daily agent-run cap, what gets slowed first under high usage, auto-resume after the usage window resets
- **Agents:** model and effort per role; **prompt editor** with a diff view. **Saving requires passing the quality test set** (§14), and shows the results before applying
- **Accounts and browser:** Chrome profiles, extension pairing (QR-free token copy), niche tags, caps
- **Discord:** bot token, server and channel mapping, reviewer role
- **Media:** caption style gallery (live previews on a sample clip), default layouts, encode settings
- **Storage:** data folder, retention, disk usage, backups (last backup + "Back up now")
- **Tools and MCP:** every MCP server (ours + third-party) with status, call counts and errors; the per-agent access matrix (PLAN §16.3) as a grid you can view and adjust, saved with a confirmation; **Memory** browser to search, edit or delete lessons the agents saved, each with its evidence link
- **Health:** full diagnostics (`clipper doctor`) with a copy-report button

---

## 4. First-run setup wizard
1. Welcome + data folder (default `D:\Clipper.io\data`)
2. Claude login check: confirms the `claude` CLI is logged in to your Claude plan and **no API key** is set → test agent run
3. GPU check (CUDA, WhisperX test on a 10s sample) + ffmpeg/yt-dlp
4. Chrome profile + Companion extension install and pairing (shows "Connected ✓")
5. First account: log in inside that profile, add niche tags → warm-up schedule starts
6. Discord: bot token → pick server → creates the channels automatically
7. Marketplaces: choose **Vyro, Whop, or both** → log in to each inside the Chrome profile → test reading its campaign list. Socials: choose which to turn on (X off for now)
8. Done → Home, with dry-run **on** by default

---

## 5. Component inventory

| Component | Used on | Notes |
|---|---|---|
| `StatusPill` | shell, sessions, accounts | running/paused/blocked/dry-run |
| `KpiTile` | Home, Earnings | value + change + sparkline |
| `BudgetBurnBar` | Home, Campaigns | budget left + predicted run-out marker |
| `StageStepper` | Home, Campaigns | Brief → Sources → Analyze → Clips → Review → Post → Submit |
| `NeedsYouItem` | Home | icon, text, inline actions, urgency order |
| `ClipCard` | Library, Review queue | 9:16 thumbnail, score, status, hover play |
| `ClipPlayer` | Review, Library | frame step, trim handles, keyboard |
| `EdlPreview` | Edit, Review | proxy video + captions/crop/overlays drawn live from the EDL, no render |
| `Timeline` | Edit | multi-track (video, camera, captions, overlays, audio), violet agent presence range |
| `EditHistory` | Edit | steps by Claude/you, reasons, compare before/after, undo |
| `AgendaPanel` | Edit, Home | plan checklist (live) + notes with scope picker and agent replies |
| `SlotBoard` | Agents, title bar popover | agent slots, queue, priorities |
| `TranscriptView` | Library, Review | word highlight synced to the player |
| `SignalTimeline` | Library, Campaigns | heatmap/energy/scene cuts + moment windows |
| `AgentEventRow` | Agents, Activity rail | message / tool / subagent / blocked / thinking variants |
| `AskUserCard` | Home, Discord | an agent's question with answer buttons and a timeout |
| `LessonRow` | Settings → Memory | lesson text, scope, evidence link, edit/delete |
| `UsageMeter` | shell, Agents | Claude plan usage in the current window, amber ≥80%, shows reset time |
| `AccountChip` | everywhere | platform icon + handle + health dot |
| `CalendarLane` | Publishing | drag-drop with cap checks |
| `HoldButton` | shell (Stop) | hold-to-confirm |
| `UntrustedBanner` | Campaign Brief | marks third-party content |
| `SwitchChip` | title bar | marketplace/social chip with health dot and popover |
| `ToggleCard` | Settings | big switch + health + stats + settings for one marketplace or social |
| `MarketBadge` | Campaigns, Home, Discord cards | Vyro / Whop label |
| `SwitchOffDialog` | everywhere switches live | what happens to active campaigns / scheduled posts |

---

## 6. Keyboard map

| Keys | Action |
|---|---|
| `Ctrl+K` | Command bar (`>` = message the Director) |
| `Ctrl+.` | Show/hide the Activity rail |
| `Ctrl+1…8` | Go to page |
| `Ctrl+Shift+P` | Pause / resume all |
| `Ctrl+Shift+D` | Toggle dry-run |
| `Ctrl+K` → "turn off whop" / "turn on tiktok" | Flip any switch (shows the switch-off dialog when needed) |
| Review: `A` `R` `E` `C` `Space` `←` `→` `Shift+A` | approve, reject, edit, re-cut, play, prev, next, approve all ≥ threshold |
| Edit: `Space` `I` `O` `S` `Del` `Ctrl+Z` `N` `T` | play, set in, set out, split, delete range, undo, new note, take over / hand back |
| Library: `/` | search |

---

## 7. Front-end tech

| Concern | Choice |
|---|---|
| Framework | React 19 + Vite + TypeScript |
| Styling / components | Tailwind + shadcn/ui (Radix underneath), **restyled to Windows utility conventions** (Segoe UI Variable, 4px corners, compact rows, checkbox toggles, underline text fields). Data grids: TanStack Table + virtualization; splitters: `react-resizable-panels` |
| Routing | TanStack Router |
| Server data | TanStack Query; a **WebSocket event stream** updates the cached data live (agent events, job progress, review decisions) |
| Tables | TanStack Table (virtualized for Library/Agents) |
| Local UI state | Zustand (rail open, filters, current review clip) |
| Charts | Recharts (KPIs, earnings); custom canvas for `SignalTimeline` |
| Drag and drop | dnd-kit (calendar) |
| Command bar | cmdk |
| Video | native `<video>` + custom controls; clips served from the sidecar over `127.0.0.1` |
| Desktop | Tauri v2: **native title bar + Mica** (window-vibrancy plugin), **native menu bar** (Tauri menu API), tray, Windows toast notifications, autostart, single-instance, multi-window (pop-out Review/Edit), reads the Windows accent color and light/dark setting |

**Data flow:** every screen reads from the FastAPI REST endpoints, and live updates arrive as WebSocket events (`agent.event`, `job.progress`, `clip.updated`, `review.decided`, `post.status`, `alert`) that update the cached data. Review actions update the screen immediately and are confirmed by the server, so Discord and the app never disagree.

---

## 8. Build order (fits PLAN.md phases)
- **Phase 0:** shell (title bar, nav, status pill, Stop button, dry-run bar), Agents page with live transcript, Health panel, setup wizard steps 1–4
- **Phase 1:** Library + clip detail, Campaigns (manual paste mode)
- **Phase 2:** Review page + Discord sync, Home "Needs you"
- **Phase 3:** Publishing (calendar, accounts, recipes), social and account switches + title-bar chips
- **Phase 4:** Campaigns suggested/active + budget bars + marketplace badges/filters, Marketplaces settings cards, wizard step 7
- **Phase 5:** Earnings, Director chat everywhere, command bar `>` mode, auto-approve offer
