# Set up the Clipper Chrome profile

The agents do everything on Vyro, Whop, YouTube Studio, TikTok and Instagram through **Clipper's own Chrome**, a separate Chrome data folder that you log into once. Do this setup once.

> **Clipper runs this Chrome itself, hidden.** When the core starts it launches `C:\ClipperData\chrome\main` with no window or taskbar button, and keeps it running. To see it (to watch the agents, log in, or clear a "verify it's you" screen), use **Show browser** in the toolbar, the "Browser hidden" item in the status bar, **Tools → Show / hide browser**, or **Ctrl+Shift+B**. Per account: Publishing → Accounts → **Show browser**. Closing the shown window is fine: Clipper starts it again, hidden. Settings → Accounts and browser → *Clipper's own browser* controls this. The desktop shortcut below is only needed for the very first login, before Clipper is running.

## Why a separate Chrome data folder (not just a new profile)
Chrome blocks automation tools (the Playwright backup, PLAN §5) from attaching to your **default** Chrome data folder. Using its own data folder keeps Clipper completely apart from your personal browsing, and it means the backup works if the extension ever breaks.

## 1. Create the shortcut
1. Right-click the desktop → **New → Shortcut**.
2. Location (one line):
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\ClipperData\chrome\main" --profile-directory=Default
   ```
3. Name it **Clipper Chrome**. Optionally pin it to the taskbar.
4. Open it. You should see a fresh Chrome with no bookmarks and no extensions.

The data lives on C: on purpose: D: has limited space.

## 2. Settings inside Clipper Chrome
- **Sync:** leave it off (no Google account sign-in to Chrome itself is needed).
- **On startup:** "Continue where you left off".
- **Downloads:** turn off "Ask where to save each file".
- **Passwords:** let Chrome remember the logins below, so sessions survive restarts. Clipper never reads or types passwords; you log in yourself.
- **Notifications** from these sites: block them (fewer pop-ups that could confuse the upload scripts).
- **Extensions:** install nothing except the Companion extension later. Other extensions can interfere with page layouts.

## 3. Log in (you do this by hand, once)
Log in to each site **with the accounts Clipper should use**, and finish any 2FA:

| Site | URL | Notes |
|---|---|---|
| Vyro | vyro.com | The clipper account that will take campaigns |
| Whop | whop.com | The same account you'll use for Content Rewards |
| YouTube Studio | studio.youtube.com | Choose the channel that will post Shorts |
| TikTok | tiktok.com/tiktokstudio | The posting account |
| Instagram | instagram.com | Must be able to post Reels from the web |

Tick "stay signed in" or "remember me" wherever it's offered.

## 4. More than one account per platform
Each set of accounts (for example a second TikTok in a different niche) gets **its own data folder and shortcut**:
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\ClipperData\chrome\podcastcuts" --profile-directory=Default
```
Each folder is its own Chrome profile in Clipper (PLAN §5). One upload runs at a time per profile.

## 5. When Clipper pauses an account
If a site shows a login page, CAPTCHA or "verify it's you" screen, Clipper **pauses that account** and alerts you in `#alerts` and the app. Press **Show browser**, complete it yourself, then click **Resume** on the account in the app (and hide the browser again if you like). Clipper never tries to solve these itself.

## 6. Installing the Companion extension
Run `just build`, then press **Show browser** in Clipper (or use the shortcut) and in that window: `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → choose `D:\Clipper.io\apps\extension\dist`. Then pair it using the token from Settings → Accounts and browser. Chrome no longer accepts extensions from the command line, so this one step is manual; the extension stays installed in the profile afterwards.
