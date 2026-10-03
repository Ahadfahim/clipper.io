// Sites the Companion may open or act on. Mirrors the core's browser.domain_allowlist default;
// the core's guard enforces it too. Lookalike hosts (youtube.com.evil.example) don't match.
export const DOMAIN_ALLOWLIST: Record<string, string[]> = {
  youtube: ["studio.youtube.com", "youtube.com"],
  tiktok: ["tiktok.com"],
  instagram: ["instagram.com"],
  x: ["x.com"],
  vyro: ["vyro.com"],
  whop: ["whop.com"],
};

export function hostAllowed(url: string, allow: Record<string, string[]> = DOMAIN_ALLOWLIST): boolean {
  let host: string;
  try {
    const u = new URL(url);
    if (u.protocol !== "https:") return false;
    host = u.hostname.toLowerCase();
  } catch {
    return false;
  }
  return Object.values(allow)
    .flat()
    .some((d) => host === d || host.endsWith(`.${d}`));
}

/** Files are only ever fetched from the local core. */
export function isLocalFileUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return (u.protocol === "http:" || u.protocol === "https:") && (u.hostname === "127.0.0.1" || u.hostname === "localhost") && u.pathname.startsWith("/api/files/");
  } catch {
    return false;
  }
}
