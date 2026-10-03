import { test } from "@playwright/test";
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
const screens = [{ name: "shell", path: "/" }] as const;

for (const screen of screens) {
  for (const theme of themes) {
    for (const size of sizes) {
      test(`${screen.name} ${theme} ${size.name}`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: theme });
        await page.setViewportSize({ width: size.width, height: size.height });
        await page.goto(screen.path);
        await page.screenshot({ path: `${outDir}/${screen.name}-${theme}-${size.name}.png` });
      });
    }
  }
}
