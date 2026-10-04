// Bundles the service worker and content script into dist/ and copies the manifest, recipes and icons.
import { build } from "esbuild";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

// Chrome keeps an unpacked extension's service worker registered across restarts and only reads the
// new one when the manifest version changes, so every build gets its own version:
// <major>.<minor>.<days since 2026-01-01>.<2-second slot of the day>. version_name keeps the readable one.
const manifest = JSON.parse(readFileSync("manifest.json", "utf8"));
const [major, minor] = manifest.version.split(".");
const now = new Date();
const days = Math.floor((now.getTime() - Date.UTC(2026, 0, 1)) / 86_400_000);
const slot = Math.floor((now.getUTCHours() * 3600 + now.getUTCMinutes() * 60 + now.getUTCSeconds()) / 2);
const version = `${major}.${minor}.${days}.${slot}`;

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });
const common = { bundle: true, target: "chrome120", sourcemap: true, logLevel: "warning", define: { __EXTENSION_VERSION__: JSON.stringify(version) } };
await build({ ...common, entryPoints: ["src/background/service_worker.ts"], outfile: "dist/service_worker.js", format: "esm" });
await build({ ...common, entryPoints: ["src/content/content.ts"], outfile: "dist/content.js", format: "iife" });
await build({ ...common, entryPoints: ["src/options/options.ts"], outfile: "dist/options.js", format: "iife" });
writeFileSync("dist/manifest.json", JSON.stringify({ ...manifest, version, version_name: `${manifest.version} (build ${version})` }, null, 2));
for (const [src, dest] of [["options.html", "dist/options.html"], ["options.css", "dist/options.css"], ["recipes", "dist/recipes"], ["icons", "dist/icons"]]) {
  if (existsSync(src)) cpSync(src, dest, { recursive: true });
}
console.log(`built dist/ (version ${version})`);
