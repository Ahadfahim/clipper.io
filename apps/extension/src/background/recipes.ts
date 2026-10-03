// Every recipe shipped with the extension (bundled at build time). All are UNVERIFIED until run
// against the real sites on the user's machine (see HANDOFF.md, LOCAL-VERIFY).
import type { Recipe } from "../shared/recipe";
import instagramUpload from "../../recipes/instagram.upload_reel.json";
import tiktokUpload from "../../recipes/tiktok.upload.json";
import vyroGet from "../../recipes/vyro.get_campaign.json";
import vyroList from "../../recipes/vyro.list_campaigns.json";
import vyroSession from "../../recipes/vyro.session_check.json";
import vyroSubmit from "../../recipes/vyro.submit_url.json";
import whopList from "../../recipes/whop.list_campaigns.json";
import whopSession from "../../recipes/whop.session_check.json";
import whopSubmit from "../../recipes/whop.submit_url.json";
import youtubeUpload from "../../recipes/youtube.upload_short.json";

export const RECIPES: Record<string, Recipe> = Object.fromEntries(
  [youtubeUpload, tiktokUpload, instagramUpload, vyroList, vyroGet, vyroSubmit, vyroSession, whopList, whopSubmit, whopSession].map((r) => [r.name, r as unknown as Recipe]),
);
