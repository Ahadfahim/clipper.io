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
  { name: "agents", path: "/agents?session=1", ready: "Live transcript" },
  { name: "campaigns", path: "/campaigns", ready: "Paste campaign URL" },
  { name: "campaign-detail", path: "/campaigns?open=1", ready: "Why this score" },
  { name: "library", path: "/library", ready: "12 of 12 clips" },
  { name: "clip-detail", path: "/library/1?tab=why", ready: "Signal timeline" },
  { name: "review", path: "/review/1", ready: "Decisions sync with Discord" },
  { name: "edit", path: "/edit/3", ready: "Your notes" },
  { name: "publishing", path: "/publishing", ready: "Drag a scheduled post" },
  { name: "publishing-accounts", path: "/publishing?tab=accounts", ready: "Open Chrome window" },
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
