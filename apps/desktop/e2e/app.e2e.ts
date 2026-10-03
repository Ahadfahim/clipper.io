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
