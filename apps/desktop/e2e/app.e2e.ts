import { expect, test, type Page } from "@playwright/test";

const errors: string[] = [];
test.beforeEach(async ({ page }) => {
  errors.length = 0;
  page.on("pageerror", (e) => errors.push(String(e)));
});
test.afterEach(() => {
  expect(errors, "no uncaught page errors").toEqual([]);
});

async function open(page: Page, path: string) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(path);
}

test("overview shows what needs you, campaigns, slots and health", async ({ page }) => {
  await open(page, "/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Earned today")).toBeVisible();
  const needs = page.getByRole("table", { name: "Needs you" });
  await expect(needs.getByText("TikTok @clipsdaily paused")).toBeVisible();
  await expect(page.getByRole("table", { name: "Active campaigns" }).getByText("MrBeast #42 clipping")).toBeVisible();
  await expect(page.getByRole("table", { name: "Agent slots" })).toBeVisible();
  await expect(page.getByLabel("Health").getByText("Discord bot")).toBeVisible();
  // answering a question removes it from the list
  await needs.getByRole("button", { name: "Skip campaign" }).click();
  await expect(needs.getByText("Rules unclear")).toHaveCount(0);
});

test("needs you: open a question, see every option, answer in your own words", async ({ page }) => {
  await open(page, "/");
  const needs = page.getByRole("table", { name: "Needs you" });
  await needs.getByRole("row", { name: /Rules unclear/ }).click();
  const detail = needs.getByRole("region", { name: /Details: Rules unclear/ });
  await expect(detail.getByText("Your answer")).toBeVisible();
  await expect(detail.getByRole("button", { name: /Skip campaign/ })).toBeVisible();
  await expect(detail.getByText(/the hook lands late/)).toBeVisible(); // what the agent said just before asking
  const box = detail.getByPlaceholder("Answer in your own words");
  await box.fill("Use the trailer, but only the first minute");
  await detail.getByRole("button", { name: /Send answer/ }).click();
  await expect(box).toHaveValue("");
  // the link in the address bar opens an item directly, and a failure shows the full output
  await page.goto("/?item=failure:job:6");
  const failure = page.getByRole("region", { name: /Details: Download failed/ });
  await expect(failure.getByText("The video isn't available").first()).toBeVisible();
  await failure.getByText("Full output").click();
  await expect(failure.getByText(/ERROR: \[youtube\] gone/)).toBeVisible();
  await failure.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("region", { name: /Details: Download failed/ })).toHaveCount(0);
});

/** Drop files on the newest drop zone, as the desktop app would (fixture builds expose the hook). */
const dropFiles = (page: Page, paths: string[]) =>
  page.evaluate((p) => (globalThis as unknown as { __clipperTestDrop?: (x: string[]) => boolean }).__clipperTestDrop?.(p), paths);

test("needs you: a source that can't be downloaded has its link, and takes a dropped video file", async ({ page }) => {
  await page.goto("/?item=footage:5");
  const detail = page.getByRole("region", { name: /Details: Add the video from next.frame.io/ });
  await expect(detail.getByRole("button", { name: "Open on next.frame.io" })).toBeVisible();
  await expect(detail.getByRole("button", { name: "Try the download anyway" })).toBeVisible();
  await expect(detail.getByText("Recent downloads")).toBeVisible();
  // a file that isn't a video is turned away with the reason
  await dropFiles(page, ["C:/Users/you/Downloads/notes.txt"]);
  await expect(detail.getByText(/notes.txt isn't a video/)).toBeVisible();
  // a video is checked, then added: the box turns into its progress
  await dropFiles(page, ["C:/Users/you/Downloads/episode-212.mp4"]);
  await expect(detail.getByText("Adding episode-212.mp4")).toBeVisible();
  await expect(detail.getByRole("group", { name: "Drop the video file here" })).toHaveCount(0);
  // the other item is already copying a file: its row says how far
  await page.goto("/?item=footage:6");
  await expect(page.getByRole("row", { name: /Add the video from drive.google.com/ }).getByText("Adding your file: 40%")).toBeVisible();
});

test("needs you: a stalled job and a blocked request say what is wrong and offer the way out", async ({ page }) => {
  await open(page, "/?item=stuck:job_stalled:2");
  const job = page.getByRole("region", { name: /Details: Analysis of source 3 hasn't moved/ });
  await expect(job.getByText("Analysis of source 3: 70% done, last moved 38 min ago.")).toBeVisible();
  await job.getByRole("button", { name: "Cancel and retry" }).click();
  await expect(page.getByRole("status").filter({ hasText: "not saved" })).toBeVisible(); // fixture mode saves nothing
  await page.goto("/?item=stuck:request_blocked:3");
  const blocked = page.getByRole("region", { name: /Details: The agent request for Ali Abdaal/ });
  await expect(blocked.getByText(/held by session 4/).first()).toBeVisible();
  await expect(blocked.getByRole("button", { name: "Release lease" })).toBeVisible();
  await blocked.getByPlaceholder("Tell the agent what to try").fill("Carry on with the second source");
  await blocked.getByRole("button", { name: /Nudge agent/ }).click();
  await expect(blocked.getByText(/Nudged\./)).toBeVisible();
  // the campaign's stage bar says it too
  await open(page, "/");
  await expect(page.getByRole("table", { name: "Active campaigns" }).getByText(/Analyze · stuck|stuck/).first()).toBeVisible();
});

test("jobs: a stalled job is flagged and can be cancelled and retried", async ({ page }) => {
  await open(page, "/");
  await page.getByRole("tab", { name: /^Jobs/ }).click();
  const row = page.getByRole("table", { name: "Jobs" }).getByRole("row").filter({ hasText: "Stalled" });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("Tracking faces", { exact: false })).toBeVisible();
  await expect(row.getByRole("button", { name: "Cancel" })).toBeVisible();
  await expect(row.getByRole("button", { name: "Retry" })).toBeVisible();
});

test("agents: nudge an agent with a message from the Context pane", async ({ page }) => {
  await open(page, "/agents?session=1");
  await page.getByRole("button", { name: "Nudge" }).first().click();
  const box = page.getByLabel("Message (optional)");
  await box.fill("Check the second source");
  await page.getByRole("button", { name: /Nudge agent/ }).click();
  await expect(box).toHaveCount(0);
  await expect(page.getByText("This run 5 / 80 · total 46", { exact: false })).toBeVisible();
  await expect(page.getByText(/held by session 4/)).toBeVisible(); // why a queued request waits
  // the Director chat folds down to its input row, and back
  const chat = page.getByRole("region", { name: "Director chat" });
  await chat.getByRole("button", { name: "Collapse to the input" }).click();
  await expect(chat.getByRole("button", { name: "Show the conversation" })).toBeVisible();
  await expect(chat.getByPlaceholder(/Ask about earnings/)).toBeVisible();
  await chat.getByRole("button", { name: "Show the conversation" }).click();
  await expect(chat.getByRole("button", { name: "Collapse to the input" })).toBeVisible();
});

test("library: select cards like Explorer, scrap them with Delete, undo, and find them in Scrapped", async ({ page }) => {
  await open(page, "/library?status=in_review"); // clips waiting for review: nothing posted, so all can be scrapped
  const cards = page.getByRole("group", { name: "Clips" }).getByRole("button", { name: /^Clip \d+/ });
  await expect(cards.first()).toBeVisible();
  const before = await cards.count();
  expect(before).toBeGreaterThan(3);
  await cards.nth(0).click();
  await cards.nth(2).click({ modifiers: ["Control"] });
  await expect(page.getByText(/2 selected/)).toBeVisible();
  await expect(cards.nth(0)).toHaveAttribute("aria-pressed", "true");
  await expect(cards.nth(1)).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Delete");
  const dialog = page.getByRole("dialog", { name: "Scrap 2 clips?" });
  await expect(dialog.getByText(/files are deleted after 7 days/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Scrap 2 clips" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Scrap 2 clips" }).click();
  await expect(page.getByText("2 clips scrapped.")).toBeVisible();
  await expect(cards).toHaveCount(before - 2);
  await page.getByRole("button", { name: /^Undo/ }).click();
  await expect(page.getByText("2 clips scrapped.")).toHaveCount(0);
  // the Scrapped view lists clips thrown away earlier, greyed, with when their files go
  await page.getByLabel("Status").selectOption("scrapped");
  await expect(page.getByText("Deleted in 5 days")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete files now" })).toBeVisible();
});

test("library: a posted clip can't be scrapped, and the dialog says why", async ({ page }) => {
  await open(page, "/library?status=posted");
  const card = page.getByRole("group", { name: "Clips" }).getByRole("button", { name: /^Clip \d+/ }).first();
  await card.click();
  await page.keyboard.press("Delete");
  const dialog = page.getByRole("dialog", { name: "Scrap this clip?" });
  await expect(dialog.getByText(/Can't scrap a posted clip/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: /^Scrap 0 clips/ })).toBeDisabled();
});

test("tree navigation and keyboard page shortcuts", async ({ page }) => {
  await open(page, "/");
  await page.getByRole("tree").getByRole("link", { name: /^Library/ }).click();
  await expect(page.getByRole("heading", { name: "Library", exact: true })).toBeVisible();
  await page.keyboard.press("Control+7");
  await expect(page.getByRole("heading", { name: "Earnings", exact: true })).toBeVisible();
  await page.keyboard.press("Control+2");
  await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
});

test("review: A approves and moves on, R + number rejects, Shift+A approves the rest above the threshold", async ({ page }) => {
  await open(page, "/review/1");
  const list = page.getByRole("listbox", { name: "Clips in this batch" });
  await expect(list.locator('[aria-selected="true"]')).toContainText("He thought it was a prank");
  await page.keyboard.press("a");
  await expect(list.locator('[aria-selected="true"]')).toContainText("I can't believe he said yes");
  await expect(list.getByRole("option", { name: /He thought it was a prank/ })).toContainText("Approved");
  await page.keyboard.press("r");
  await page.keyboard.press("1");
  await expect(list.getByRole("option", { name: /I can't believe he said yes/ })).toContainText("Rejected");
  await page.keyboard.press("ArrowLeft");
  await expect(list.locator('[aria-selected="true"]')).toContainText("I can't believe he said yes");
  await expect(page.getByText(/9\/12 reviewed/)).toBeVisible();
  // re-cut mode shows trim handles and the layout picker
  await page.keyboard.press("c");
  await expect(page.getByRole("slider", { name: "Trim start" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("slider", { name: "Trim start" })).toHaveCount(0);
});

test("switching a marketplace off asks what to do with its campaigns", async ({ page }) => {
  await open(page, "/");
  const toolbar = page.getByRole("toolbar", { name: "Main toolbar" });
  await toolbar.getByLabel("Whop").click(); // the change waits for the dialog
  const dialog = page.getByRole("dialog", { name: "Turn off Whop?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(/Active campaigns/)).toContainText("(");
  await dialog.getByLabel("Pause them now").check();
  await dialog.getByRole("button", { name: "Turn off" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(toolbar.getByLabel("Whop")).not.toBeChecked();
  // switching on needs no dialog
  await toolbar.getByLabel("Whop").click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(toolbar.getByLabel("Whop")).toBeChecked();
});

test("command box: jump to a clip, and > messages the Director", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("Control+k");
  const box = page.getByRole("dialog", { name: "Search and commands" });
  await box.getByRole("combobox").fill("prank");
  await box.getByRole("option", { name: /He thought it was a prank/ }).click();
  await expect(page).toHaveURL(/\/library\/\d+/);
  await page.keyboard.press("Control+k");
  await page.keyboard.type("> pause tiktok until monday");
  await page.keyboard.press("Enter");
  await expect(box.getByText("pause tiktok until monday")).toBeVisible();
  await expect(box.getByText(/\$412\.60 this week/)).toBeVisible();
});

test("settings dialog: sections, OK/Cancel/Apply, shortcut", async ({ page }) => {
  await open(page, "/");
  await page.keyboard.press("Control+,");
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByRole("heading", { name: "Marketplaces and socials" })).toBeVisible();
  await dialog.getByRole("button", { name: "Automation" }).click();
  await dialog.getByLabel("Approve all at score").fill("85");
  await expect(dialog.getByText("1 unsaved change")).toBeVisible();
  await dialog.getByRole("button", { name: "Apply" }).click();
  await expect(dialog.getByText(/unsaved change/)).toHaveCount(0);
  await dialog.getByRole("button", { name: "Tools and MCP" }).click();
  await expect(dialog.getByText("Access matrix: tools per agent (max 25)")).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});

test("campaigns: drawer with untrusted brief and spec form", async ({ page }) => {
  await open(page, "/campaigns");
  await page.getByRole("grid", { name: "Campaigns" }).getByText("MrBeast #42 clipping").dblclick();
  const drawer = page.getByRole("complementary", { name: "Campaign detail" });
  // every campaign links to its page on the marketplace: in the grid, in the drawer header and body
  await expect(page.getByRole("grid", { name: "Campaigns" }).getByRole("button", { name: /^Open on / }).first()).toBeVisible();
  await expect(drawer.getByRole("button", { name: /^Open on / }).first()).toBeVisible();
  await expect(drawer.getByText("Page", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Copy link" })).toBeVisible();
  await drawer.getByRole("tab", { name: "Brief" }).click();
  await expect(drawer.getByRole("note")).toContainText("untrusted");
  await drawer.getByRole("tab", { name: "Spec" }).click();
  await expect(drawer.getByLabel("Maximum length (s)")).toHaveValue("60");
  await page.getByRole("tab", { name: /Suggested/ }).click();
  await expect(page.getByRole("grid", { name: "Campaigns" }).getByText("Diary of a CEO clips")).toBeVisible();
});

test("edit: take over, mark a range and delete it; history records it", async ({ page }) => {
  await open(page, "/edit/3");
  await expect(page.getByRole("status").filter({ hasText: "Claude is editing" })).toBeVisible();
  await page.keyboard.press("t");
  await expect(page.getByRole("button", { name: /Hand back to Claude/ })).toBeVisible();
  const history = page.getByRole("complementary", { name: "History", exact: true });
  await expect(history.getByText("delete range", { exact: true })).toHaveCount(0);
  await page.keyboard.press("i");
  await page.getByRole("region", { name: "Timeline" }).locator("div.cursor-pointer").first().click({ position: { x: 300, y: 10 } });
  await page.keyboard.press("o");
  await page.getByRole("button", { name: /Delete range/ }).click();
  await expect(history.getByText("delete range", { exact: true })).toBeVisible();
});

test("publishing: calendar lanes, accounts with paused reason, recipes", async ({ page }) => {
  await open(page, "/publishing");
  await expect(page.getByRole("grid", { name: "Posting calendar" })).toBeVisible();
  await page.getByRole("tab", { name: /Accounts/ }).click();
  await expect(page.getByRole("grid", { name: "Accounts" }).getByText("verification needed")).toBeVisible();
  await page.getByRole("tab", { name: "Recipes" }).click();
  await expect(page.getByRole("grid", { name: "Recipes" }).getByText("tiktok.upload")).toBeVisible();
});

test("setup wizard walks to the end", async ({ page }) => {
  await open(page, "/setup");
  for (let i = 0; i < 7; i++) await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "You're set" })).toBeVisible();
  await page.getByRole("button", { name: "Open Clipper" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
});
