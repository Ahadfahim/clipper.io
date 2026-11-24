# Campaign titles everywhere

**Ask:** "In some places it calls campaigns by name/title, some places the number, like campaign 2, 3. Make it use the title everywhere, even in the folder names."

**Goal:** wherever a person reads about a campaign (the app, Discord, alerts, folders on disk), they see its title. Numbers stay only where nobody reads them: database ids, API paths, URL parameters, lease and Needs you keys, Discord button ids, and agent tool arguments.

## Where numbers show today

Everything below was found in the code. The folder names were checked on this machine.

| Where | Today | After |
|---|---|---|
| Activity and Problems tabs, toasts (`api/describe.ts`) | "Took campaign 2 (discord)", "Campaign 2 updated", "Found campaign 14 on whop", "Skipped campaign 4", "Campaign 2 ending: deadline", "Spec updated for campaign 2", "Nudged campaign 2 after 30m idle" | "Took Eat Everything In A Grocery Store, Win $1,000,000 (Discord)", and so on |
| Activity, Needs you snooze and dismiss lines | "campaign 8 dismissed" (it prints the item's key) | "Adriatique - X São Paulo Sold-Out Show Clips dismissed" |
| Needs you question panel (`attention.tsx:447`) | "Question from the agent · campaign 2" | "Question from the agent · Eat Everything…" |
| Jobs tab | "Download of source 4", with no campaign at all | the same label, plus the campaign's title in its own column |
| Agents screen queue reasons, stuck-item evidence (`pool.py`, `supervisor.py`) | "All 2 agent slots are busy (campaign 2, scout)", "Campaign 2 has an agent running…", "Campaign 2 is held by session 4…" | the titles |
| Campaign drawer timeline (`views.event_text`) | "Nudge (campaign:2)" | "Nudge (Eat Everything…)" |
| Error toasts (`services/*.py` ServiceError) | "campaign 2 is active; only suggested campaigns can be taken", "source 4 belongs to campaign 2", "clip 9 is not part of campaign 2" | the titles. "Campaign 99 not found" keeps the number, because there is no title to show |
| Alerts (`services/media.py`) | "x.mp4 in the campaign 2 folder is older than…" | "…in the Eat Everything… folder…" |
| Guard blocks, shown in Activity as "Blocked …" (`agents/hooks.py`) | "this session owns campaign 2; it may not act on campaign 3", "campaign 2 does not allow tiktok", "…is not on campaign 2's source whitelist", "post 5 was made for campaign 2, not 3" | the title first, then the id in brackets (see decision 3) |
| Messages to agents, visible in the Agents transcript (`supervisor/messages.py`) | "Campaign 2 was taken by…", "The user joined campaign 2…", "Campaign 2 is ending…", "The user edited the spec of campaign 2" | the same as the guard blocks |
| Discord `/clipper nudge` when the text matches several campaigns | "That matches several campaigns: 3 Cinematic edits, 15 Cinematic edits. Use the number." | "That matches 2 campaigns: Cinematic edits (Vyro, ended), Cinematic edits (Vyro, waiting for you to join). Pick one from the list." The autocomplete already shows titles. |
| **Source folders** | `C:\ClipperData\sources\campaign_2\` | `C:\ClipperData\sources\Eat Everything In A Grocery Store, Win $1,000,000\` |

Already correct, no change: the Overview and Campaigns grids, the Needs you list, the Library filter, Ctrl+K, Earnings breakdowns, the Agents slot board and its context pane, Discord campaign cards and review posts.

### Your folders after the change

| Now | After |
|---|---|
| `C:\ClipperData\sources\campaign_1` | `…\sources\5 Guys Face Their Crush` |
| `…\sources\campaign_2` | `…\sources\Eat Everything In A Grocery Store, Win $1,000,000` |
| `…\sources\campaign_9` | `…\sources\[US} Double Date Island - Dating Show Clips` |
| `…\sources\campaign_15` | `…\sources\Cinematic edits` |

Campaign 3 is also called "Cinematic edits". It has no folder, so it would only get one ("Cinematic edits (2)") if it ever needed one.

## Decisions

1. **A name is looked up when it's shown, not stored in the log.** Events keep the campaign's id. The app turns the id into the title when it draws a line, so old lines in the log show titles too, and a campaign the marketplace renames shows its new name everywhere. Text the core builds once (queue reasons, alerts, errors) looks up the title when it builds the text.
2. **Same-title campaigns are told apart only where they appear side by side.** That covers the Discord match list, Ctrl+K and the Library filter: "Cinematic edits · Vyro · ended". Everywhere else it's just the title.
3. **Agents still get the id, after the title**, for example `"Eat Everything…" (campaign id 2)`. Their tools take ids, and an agent given only a title would have to guess. This text is in the Agents transcript and in "Blocked …" lines. To hide the id there as well, the transcript can strip the bracket when it draws the line.
4. **A campaign's folder name is fixed once and saved.** A new `campaign.folder` column (migration `0008`) holds the name, so a running download never has its folder renamed under it, and finding a folder no longer depends on its name pattern. The name is the title made safe for Windows:
   - The characters `< > : " / \ | ? *` and control characters become a space, and runs of spaces collapse.
   - Trailing dots and spaces are removed.
   - Reserved names (CON, NUL, COM1 …) get " campaign" added.
   - An empty result becomes "Untitled campaign".
   - The name is cut to 60 characters at a word boundary, which leaves room for long video file names under Windows' 260-character path limit.
   - If two campaigns would get the same name, the second gets " (2)", the next " (3)". The check ignores case and also looks at folders already on disk.
5. **Old folders are renamed once, when the core starts**, before any download or import can start:
   - A `campaign_<id>` folder is renamed, then every stored path under it is rewritten in the database: `source.path` and `proxy_path`, the analysis paths, and the job errors and results that quote the folder.
   - Every move is logged in `data\logs\folder-moves.jsonl`, so it can be undone by hand.
   - Folders are only renamed, never copied or deleted. A rename on the same drive is instant, even for the 1.5 GB source.
   - If Windows refuses (a video in that folder is open in a player or an Explorer window), the folder keeps working under its old name. A one-line info alert says so, and the core tries again at the next start.
   - The same step renames a folder when the marketplace changes the campaign's title.

## Milestones

### T1: titles in the app
- `describeEvent(ev, names)` takes a lookup from campaign id to title, from a new `useCampaignNames()` hook built on the campaigns query that is already cached. The Activity tab, Problems tab and toasts pass it in. While the list is still loading, a line says "a campaign" and redraws when it arrives.
- The `attention.changed` line says what the item was about: the campaign's title, or for other items "a question", "footage" and so on.
- `QuestionOut.campaign_title` (API) is used by the question panel header.
- `JobOut.campaign_title` is shown in the Jobs tab.
- `just gen-api`, then update describe.test.ts, the attention tests and the OutputPanel test.

### T2: titles in the core's text and Discord
- Add a `campaign_name(session, id)` helper, plus a title map for the places that need many.
- `explain_wait` (pool.py) and the lease-blocked text (supervisor.py) use titles. `event_text` for `nudge.sent` prints the target's name.
- ServiceErrors and the drop-folder alert use titles. Guard denials (hooks.py) and agent messages (messages.py) use the title followed by `(campaign id N)`.
- Discord: the ambiguous `/clipper nudge` reply lists titles with marketplace and status.
- Tests: update test_stalls (`explain_wait`), the guard tests, the message tests and the bot's nudge test.

### T3: folders named by title
- Migration `0008_campaign_folder`: `campaign.folder` (text, nullable).
- `clipper/folders.py`:
  - `safe_name(title)`.
  - `assign_folder(tx, campaign)` checks for clashes against the database and the disk.
  - `campaign_folder(core, id)` returns the saved name, or else a `campaign_<id>` folder that hasn't been moved yet, or else assigns a new name.
  - `tidy_folders(core)` does the start-up move from decision 5.
- `media.drop_folder`, the download handler and `scan_drop_folders` use `campaign_folder`. The scan goes through campaigns that have a folder instead of matching `campaign_*`.
- `Core.start` runs `tidy_folders` before the workers and the supervisor start.
- Update the seed, the fixture export and the regenerated UI fixtures (their `drop_folder` paths).
- Tests:
  - Names: each forbidden character, reserved names, trailing dots, length, an empty title, a clash getting " (2)", a mixed-case clash, and non-ASCII characters kept.
  - The move: a legacy folder is renamed and its paths rewritten. A locked folder stays where it is, is still used and is retried. A changed title renames the folder at the next start. A second start does nothing.
  - Downloads and the scan use the titled folder.

### T4 (optional, recommended): finished clips grouped by campaign
Final renders sit loose in `D:\Clipper.io\data\clips\` today (`clip_9_v1_final.mp4`), with no campaign in their path. With this step they go to `data\clips\<campaign folder>\clip_9_v1_final.mp4`:
- The render handler writes there, and the start-up step moves the existing finals and rewrites `clip.path`.
- Previews, thumbnails and `work\` stay as they are: they're caches you never open.
- The daily purge is unaffected, because it deletes by the stored path.

### T5: docs and checks
- Update UI.md (the Activity and Jobs wording), README (the drop folder is now the campaign's name) and HANDOFF (the decisions and a LOCAL-VERIFY row for the first start-up move).
- Take screenshots of the Activity tab, the Jobs tab and a Needs you question, in dark and light at 1280×800 and 1920×1080.
- Run the full checks: ruff, pyright, `tsc -b`, eslint, pytest, vitest, Playwright e2e.

## Things to know before starting

- **The shared database again.** Migration `0008` goes into the same real database the worktree core already upgraded to `0007`, so the old code in `D:\Clipper.io` stays locked out. Ship this together with the decision to merge the branch into the main checkout.
- **Campaign 9's folder will look wrong once it has a name.** Its only file is `5 Guys Face Their Crush.mp4`, but "5 Guys Face Their Crush" is campaign 1's title. Campaign 9 is "[US} Double Date Island". Source 3 was probably attached to the wrong campaign. Worth checking before the folder is renamed.
- **Campaign 8's title has a broken character** ("S�o Paulo" instead of "São Paulo") from how the marketplace page was read. It will show that way in the folder name and the app until the scrape's text encoding is fixed, which is a separate small fix.
- `campaign_1` still holds the fixture files flagged in the previous plan (`youtube_dQw4w9WgXcQ.mp4`, `youtube_ext101xxxxx.mp4`). They move with the folder. Removing them is still your call.

## Out of scope

Clips, posts, sessions and jobs have no title, so they keep their numbers ("Clip 9", "session 4", "job 12"). If those numbers bother you too, a follow-up could name each of them by what it is about, for example a clip by its hook and its campaign.
