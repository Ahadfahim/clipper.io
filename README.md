# Clipper.io

Agent-run clipping system for the Vyro and Whop Content Rewards marketplaces. It is Windows desktop software driven by Claude Code agents: they find campaigns, download the source videos, pick and cut the clips, ask you to review them, then post them through your own logged-in Chrome.

Everything starts in **dry run**: nothing is uploaded or submitted until you turn dry run off.

- [PLAN.md](PLAN.md): architecture and phases (source of truth)
- [UI.md](UI.md): every screen of the desktop app
- [HANDOFF.md](HANDOFF.md): what was built, the LOCAL-VERIFY checklist, known gaps
- [CLAUDE.md](CLAUDE.md): rules for Claude Code sessions in this repo
- [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md): the target machine
- [docs/plans/needs-you-nudge-links.md](docs/plans/needs-you-nudge-links.md): the plan behind Needs you items, nudges, campaign links, footage drop and scrapping clips

## What you need

Windows 11 with these installed (the versions in brackets are what the project was built against):

| Tool | Used for |
|---|---|
| [uv](https://docs.astral.sh/uv/) (0.12) | Python 3.12 and the core's dependencies |
| Node 24 with corepack | the dashboard (pnpm 10.28 comes with `corepack enable`) |
| `just` | the task runner: `uv tool install rust-just` |
| Rust and WebView2 | only for the desktop window (`just dev-app`) |
| ffmpeg (8.1, with `h264_nvenc` and libass) | all video work; expected at `C:\ffmpeg\bin` |
| yt-dlp | downloading sources |
| Google Chrome | Clipper's own browser profile, where the Companion extension runs |
| Claude Code, logged in with your plan | the agents. **Do not set `ANTHROPIC_API_KEY`**: Clipper strips it, and there is no API billing |
| NVIDIA GPU with current drivers | WhisperX transcription and NVENC encoding (the RTX 5080 needs the `cu128` PyTorch build, which `just gpu-setup` installs) |

You can try the app without a GPU, Chrome profiles or any account: see "Try it with demo data".

## Set up once

Run these in PowerShell from the repository folder (`D:\Clipper.io`).

```powershell
corepack enable
Copy-Item config\settings.example.toml config\settings.toml   # then open it and check the [paths]
just setup            # installs the Python and JS dependencies
just doctor           # checks the machine; each WARN row says what is missing
just migrate          # creates the database (D:\Clipper.io\data\clipper.sqlite)
just seed             # base switches and platforms (not demo data)
```

For real transcription, create the GPU environment once, then run `just doctor` again:

```powershell
just gpu-setup
```

`config\settings.toml` is gitignored. Every key is optional and the example file lists the defaults. The ones people usually change:

- `[paths] data_dir`: where the database, clips and logs live (`D:\Clipper.io\data`).
- `[paths] sources_dir`: where source videos go (`C:\ClipperData\sources`). A one-hour 1080p source is 1 to 3 GB, so keep this on a big disk.
- `[agents] slots`: how many agents run at once (2 suits a Claude Pro plan; 0 grows with the campaigns).

## Try it with demo data

This needs no accounts and starts no agents. The demo has its own database, so it never touches your real data.

Terminal 1, the API with demo data:

```powershell
just dev-api-fixtures
```

Terminal 2, the dashboard:

```powershell
just dev-ui
```

Open <http://127.0.0.1:1420>. You will see Needs you items to open (a footage item you can drop a video onto, things that look stuck, a question to answer in your own words), campaigns with links to their marketplace pages, the Library with scrap and undo, and the Agents screen with the slot board.

To look at the screens with no API at all, run `just dev-ui-fixtures` instead of both commands: it serves a static copy of the demo data and saves nothing.

## Run it for real

The core (API, agents and job workers) and the app are separate programs. Start the core first.

Terminal 1, the core:

```powershell
just dev-api
```

It listens on `127.0.0.1:8765` (the API) and `127.0.0.1:8766` (the bridge to the Chrome extension). Check <http://127.0.0.1:8765/api/health>.

Terminal 2, the window. Pick one:

```powershell
just dev-app          # the desktop app (Tauri dev build)
just dev-ui           # or the same dashboard in a browser tab: http://127.0.0.1:1420
```

The desktop app does not start the core for you. The installer, which would bundle and start the core itself, is not built yet.

Optional, terminal 3, the Discord bot (it needs the core running and the bot token saved in Settings → Discord):

```powershell
just dev-bot
```

### First run

Open the setup wizard (`/setup`, or Run setup wizard in the File menu). It walks through:

1. **Claude login.** Run `claude` once in a terminal and sign in with your plan. Agents use that login; Clipper removes any API key from their environment.
2. **GPU and media tools.** Checks ffmpeg, yt-dlp and the CUDA environment (`just gpu-setup` creates it).
3. **Chrome and the Companion extension.** Clipper has its own Chrome profile (it runs hidden; **Show browser** brings it up). Log in to Vyro, Whop, YouTube Studio, TikTok Studio and Instagram there. Then run `just build`, open `chrome://extensions` in that Chrome, turn on Developer mode, choose **Load unpacked** and pick `apps\extension\dist`. In Settings → Accounts and browser press **Create token** and paste it into the extension's options page. The status bar then shows the extension connected.
4. **First account.** Add a social account you post to, with its niche tags, so campaigns can be matched to it.
5. **Discord** (optional). Enable the Message Content intent for the bot in the Discord Developer Portal, invite it, and save its token.
6. **Marketplaces and socials.** Choose which ones are switched on.

Secrets (the Discord token, the extension token, the Hugging Face token for speaker labels) are saved in Windows Credential Manager, not in a file.

### Turning real posting on

The toolbar's **Dry run** box is checked on a new install, and a yellow banner says so. In dry run the agents do everything except the last step: uploads and marketplace submissions are only logged, so you can watch a whole campaign go through safely.

When you trust it, uncheck Dry run (Ctrl+Shift+D). Posting still follows the safety rules in code: only clips you approved are published, daily caps and gaps per account apply, and each marketplace and social has an on/off switch in the toolbar.

### Stopping

- **Pause all** (Ctrl+Shift+P) stops new agent work; running posts finish.
- **Stop all…** in the Agents menu interrupts every agent.
- Closing the window only hides it to the tray. **File → Exit** quits and stops the agents.
- Ctrl+C in the terminals stops the core and the dev server.

## Day to day

- **Needs you** on Overview is where Clipper asks for you: questions, review batches, campaigns to take or join, footage it couldn't download, accounts that hit a challenge screen, and anything that looks stuck. Click a row to open everything about it.
- **Nudge** an agent that seems stuck from the Agents screen, from a campaign's drawer, or with Ctrl+K and typing "nudge".
- **Review** is where you approve or reject clips. A Discord reviewer can do the same from the forum posts.
- **Ctrl+K** is the command bar: jump to any campaign or clip, flip a switch ("turn off whop"), or start with `>` to message the Director.

## When something is wrong

| What you see | What to do |
|---|---|
| `just doctor` shows WARN or FAIL | Each row says what is missing and how to fix it. |
| A port is already in use | The API uses 8765, the extension bridge 8766 and the dev dashboard 1420. Stop the other copy of Clipper first. |
| Downloads fail with "isn't supported" or a 403 | Settings → Media → Update yt-dlp. For a Frame.io or WeTransfer link, drop the video on the item in Needs you. |
| "Claude usage limit reached" | Agents pause until the reset time shown in the status bar; jobs and uploads keep running. |
| Clipper's Chrome window looks black or stuck | Hide browser, then Show browser (Ctrl+Shift+B). If that doesn't help, end its `chrome.exe` in Task Manager: Clipper starts it again, hidden. |
| `just dev-app` fails to build | Check that Rust and WebView2 are installed, and that `apps\desktop\src-tauri\binaries` has the placeholder sidecar named in its README. |
| `just seed fixtures` is refused | By design: demo data in the real database would be picked up by real workers. Use `just dev-api-fixtures`. |

## For developers

```powershell
just lint             # ruff, pyright, eslint, tsc
just test             # pytest and vitest
pnpm --filter @clipper/desktop exec playwright test --project=e2e   # UI flows on the fixture build
just screenshots      # every screen, dark and light, into docs\screenshots
just gen-api          # after changing an API route: openapi.json, UI fixtures and the TS client
just local-verify     # the checks that need this machine (GPU, NVENC, Chrome, Credential Manager)
just ci               # everything CI runs
```

Run `just` with no arguments to list every recipe. The UI is built from the tokens in `apps\desktop\src\styles\tokens.css` and the components shown at `/dev/gallery`.
