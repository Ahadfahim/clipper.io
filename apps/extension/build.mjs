// Bundles the service worker and content script into dist/ and copies the manifest, recipes and icons.
import { build } from "esbuild";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });
const common = { bundle: true, target: "chrome120", sourcemap: true, logLevel: "warning" };
await build({ ...common, entryPoints: ["src/background/service_worker.ts"], outfile: "dist/service_worker.js", format: "esm" });
await build({ ...common, entryPoints: ["src/content/content.ts"], outfile: "dist/content.js", format: "iife" });
await build({ ...common, entryPoints: ["src/options/options.ts"], outfile: "dist/options.js", format: "iife" });
for (const [src, dest] of [["manifest.json", "dist/manifest.json"], ["options.html", "dist/options.html"], ["options.css", "dist/options.css"], ["recipes", "dist/recipes"], ["icons", "dist/icons"]]) {
  if (existsSync(src)) cpSync(src, dest, { recursive: true });
}
console.log("built dist/");
