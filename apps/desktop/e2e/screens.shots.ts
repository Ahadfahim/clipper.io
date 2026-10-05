// Screenshots of every screen in dark and light at 1280×800 and 1920×1080 (CLAUDE.md UI rule 6).
// Output: docs/screenshots/<screen>-<theme>-<size>.png, committed so reviewers can see the UI.
import { test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../../../docs/screenshots");
mkdirSync(outDir, { recursive: true });

const sizes = [
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1920x1080", width: 1920, height: 1080 },
] as const;
const themes = ["dark", "light"] as const;
type Shot = { name: string; path: string; ready: string; then?: (page: Page) => Promise<void>; size?: { name: string; width: number; height: number } };
const screens: Shot[] = [
  { name: "overview", path: "/", ready: "Needs you" },
  { name: "needs-you-footage", path: "/?item=footage:5", ready: "Drop the video file here" },
  { name: "needs-you-footage-copying", path: "/?item=footage:6", ready: "Adding your file" },
  { name: "needs-you-stuck", path: "/?item=stuck:request_blocked:3", ready: "Nudge with a message" },
  { name: "jobs-stalled", path: "/", ready: "Needs you", then: async (p) => {
      await p.getByRole("tab", { name: /^Jobs/ }).click();
      await p.getByRole("table", { name: "Jobs" }).getByText("Stalled").waitFor();
    } },
  { name: "agents-nudge", path: "/agents?session=1", ready: "Live transcript", then: async (p) => {
      await p.getByRole("button", { name: "Nudge" }).first().click();
      await p.getByLabel("Message (optional)").waitFor();
    } },
  { name: "agents", path: "/agents?session=1", ready: "Live transcript" },
  { name: "campaigns", path: "/campaigns", ready: "Paste campaign URL" },
  { name: "campaign-detail", path: "/campaigns?open=1", ready: "Why this score" },
  { name: "campaign-sources", path: "/campaigns?open=1", ready: "Why this score", then: async (p) => {
      await p.getByRole("tab", { name: /^Sources/ }).click();
      await p.getByRole("button", { name: "Add file…" }).click();
      await p.getByRole("group", { name: "Drop the video file here" }).waitFor();
    } },
  { name: "library", path: "/library", ready: "11 of 11 clips" },
  { name: "library-scrapped", path: "/library?status=scrapped", ready: "Deleted in 5 days" },
  { name: "library-scrap", path: "/library", ready: "11 of 11 clips", then: async (p) => {
      const cards = p.getByRole("group", { name: "Clips" }).getByRole("button", { name: /^Clip \d+/ });
      await cards.nth(1).click();
      await cards.nth(3).click({ modifiers: ["Control"] });
      await p.keyboard.press("Delete");
      await p.getByRole("dialog", { name: "Scrap 2 clips?" }).waitFor();
    } },
  { name: "library-cleanup", path: "/library", ready: "11 of 11 clips", then: async (p) => {
      await p.getByRole("button", { name: "Clean up…" }).click();
      await p.getByRole("dialog", { name: "Clean up the Library" }).waitFor();
    } },
  { name: "clip-detail", path: "/library/1?tab=why", ready: "Signal timeline" },
  { name: "review", path: "/review/1", ready: "Decisions sync with Discord" },
  { name: "edit", path: "/edit/3", ready: "Your notes" },
  { name: "publishing", path: "/publishing", ready: "Drag a scheduled post" },
  { name: "publishing-accounts", path: "/publishing?tab=accounts", ready: "@clipsdaily" },
  { name: "earnings", path: "/earnings", ready: "Earnings per day" },
  { name: "settings", path: "/settings?section=markets", ready: "Socials and accounts" },
  { name: "settings-agents", path: "/settings?section=agents", ready: "Effort and turn limits" },
  { name: "switch-off", path: "/", ready: "Needs you", then: async (p) => {
      await p.getByRole("toolbar", { name: "Main toolbar" }).getByLabel("Whop").click();
      await p.getByRole("dialog", { name: "Turn off Whop?" }).getByText(/Active campaigns \(\d+\)/).waitFor();
    } },
  { name: "command-box", path: "/", ready: "Needs you", then: async (p) => {
      await p.keyboard.press("Control+k");
      await p.getByRole("dialog", { name: "Search and commands" }).waitFor();
    } },
  { name: "setup", path: "/setup?step=2", ready: "Claude login" },
  { name: "gallery", path: "/dev/gallery", ready: "Component gallery" },
];

for (const screen of screens) {
  for (const theme of themes) {
    for (const size of sizes) {
      test(`${screen.name} ${theme} ${size.name}`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
        await page.setViewportSize({ width: size.width, height: size.height });
        await page.goto(screen.path);
        await page.getByText(screen.ready).first().waitFor();
        if (screen.then) await screen.then(page);
        await page.waitForTimeout(400); // images, charts
        const full = screen.name === "gallery" && size.name === "1920x1080";
        await page.screenshot({ path: `${outDir}/${screen.name}-${theme}-${size.name}.png`, animations: "disabled", fullPage: full });
      });
    }
  }
}

// The pop-out Review window on the 1080×1920 portrait monitor.
for (const theme of themes) {
  test(`review-popout ${theme} 1080x1920`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.setViewportSize({ width: 1080, height: 1920 });
    await page.goto("/popout/review/1");
    await page.getByText("Decisions sync with Discord").waitFor();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${outDir}/review-popout-${theme}-1080x1920.png`, animations: "disabled" });
  });
}
