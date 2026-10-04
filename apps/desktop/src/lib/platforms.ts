export const PLATFORM_ORDER = ["youtube", "tiktok", "instagram", "x"] as const;
export type Platform = (typeof PLATFORM_ORDER)[number];

export const PLATFORM_LABEL: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
  x: "X",
};

export const PLATFORM_SHORT: Record<string, string> = { youtube: "YT", tiktok: "TT", instagram: "IG", x: "X" };

export const MARKET_ORDER = ["vyro", "whop"] as const;
export type Market = (typeof MARKET_ORDER)[number];
export const MARKET_LABEL: Record<string, string> = { vyro: "Vyro", whop: "Whop" };

/** Series slot per marketplace (color follows the entity, never its rank). */
export const MARKET_SERIES: Record<string, string> = { vyro: "var(--series-1)", whop: "var(--series-2)" };

export const ROLE_LABEL: Record<string, string> = {
  scout: "Scout",
  campaign: "Campaign",
  analyst: "Analyst",
  director: "Director",
};

/** "claude-sonnet-5-5" -> "Sonnet 5.5" for tables; unknown ids pass through. */
export function modelLabel(id: string | null | undefined): string {
  if (!id) return "";
  const m = /^claude-(opus|sonnet|haiku|fable)-(\d+)-(\d+)/.exec(id);
  return m ? `${m[1]![0]!.toUpperCase()}${m[1]!.slice(1)} ${m[2]}.${m[3]}` : id;
}

export const REJECT_REASONS = [
  { value: "bad_hook", label: "Bad hook" },
  { value: "boring", label: "Boring" },
  { value: "broken", label: "Broken" },
  { value: "off_brief", label: "Off-brief" },
  { value: "other", label: "Other" },
] as const;
