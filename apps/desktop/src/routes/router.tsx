import { createRootRoute, createRoute, createRouter, Outlet, redirect, type RouterHistory } from "@tanstack/react-router";
import { AppShell } from "@/shell/AppShell";
import { AgentsScreen } from "@/screens/AgentsScreen";
import { CampaignsScreen } from "@/screens/CampaignsScreen";
import { ClipDetailScreen } from "@/screens/ClipDetailScreen";
import { EarningsScreen } from "@/screens/EarningsScreen";
import { EditScreen } from "@/screens/EditScreen";
import { GalleryScreen } from "@/screens/GalleryScreen";
import { LibraryScreen } from "@/screens/LibraryScreen";
import { OverviewScreen } from "@/screens/OverviewScreen";
import { PublishingScreen } from "@/screens/PublishingScreen";
import { ReviewIndex, ReviewScreen } from "@/screens/ReviewScreen";
import { SetupWizard } from "@/screens/SetupWizard";
import { useUi } from "@/state/ui";

const num = (v: unknown): number | undefined => {
  const n = Number(v);
  return v === undefined || v === null || v === "" || Number.isNaN(n) ? undefined : n;
};
const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);

const root = createRootRoute({ component: Outlet });
const shell = createRoute({ getParentRoute: () => root, id: "shell", component: AppShell });

const overview = createRoute({ getParentRoute: () => shell, path: "/", component: OverviewScreen });
const agents = createRoute({
  getParentRoute: () => shell,
  path: "/agents",
  validateSearch: (s: Record<string, unknown>): { session?: number } => ({ session: num(s["session"]) }),
  component: AgentsScreen,
});
const campaigns = createRoute({
  getParentRoute: () => shell,
  path: "/campaigns",
  validateSearch: (
    s: Record<string, unknown>,
  ): { market?: "vyro" | "whop"; tab?: "suggested" | "active" | "ended" | "skipped"; open?: number; detail?: string; paste?: number } => ({
    market: str(s["market"]) as "vyro" | "whop" | undefined,
    tab: str(s["tab"]) as "suggested" | "active" | "ended" | "skipped" | undefined,
    open: num(s["open"]),
    detail: str(s["detail"]),
    paste: num(s["paste"]),
  }),
  component: CampaignsScreen,
});
const library = createRoute({
  getParentRoute: () => shell,
  path: "/library",
  validateSearch: (s: Record<string, unknown>): { campaign?: number; status?: string } => ({ campaign: num(s["campaign"]), status: str(s["status"]) }),
  component: LibraryScreen,
});
const clipDetail = createRoute({
  getParentRoute: () => shell,
  path: "/library/$clipId",
  validateSearch: (s: Record<string, unknown>): { tab?: string } => ({ tab: str(s["tab"]) }),
  component: ClipDetailScreen,
});
const reviewIndex = createRoute({ getParentRoute: () => shell, path: "/review", component: ReviewIndex });
const review = createRoute({ getParentRoute: () => shell, path: "/review/$batchId", component: ReviewScreen });
const edit = createRoute({ getParentRoute: () => shell, path: "/edit/$clipId", component: EditScreen });
const publishing = createRoute({
  getParentRoute: () => shell,
  path: "/publishing",
  validateSearch: (s: Record<string, unknown>): { tab?: "calendar" | "accounts" | "recipes" | "queue"; account?: number } => ({
    tab: str(s["tab"]) as "calendar" | "accounts" | "recipes" | "queue" | undefined,
    account: num(s["account"]),
  }),
  component: PublishingScreen,
});
const earnings = createRoute({ getParentRoute: () => shell, path: "/earnings", component: EarningsScreen });
const settings = createRoute({
  getParentRoute: () => shell,
  path: "/settings",
  validateSearch: (s: Record<string, unknown>): { section?: string } => ({ section: str(s["section"]) }),
  beforeLoad: ({ search }) => {
    useUi.getState().openSettings(search.section);
  },
  component: OverviewScreen,
});

// windows without the main shell
const setup = createRoute({
  getParentRoute: () => root,
  path: "/setup",
  validateSearch: (s: Record<string, unknown>): { step?: number } => ({ step: num(s["step"]) }),
  component: SetupWizard,
});
const gallery = createRoute({ getParentRoute: () => root, path: "/dev/gallery", component: GalleryScreen });
const popReview = createRoute({
  getParentRoute: () => root,
  path: "/popout/review/$batchId",
  component: () => <ReviewScreen popout />,
});
const popEdit = createRoute({ getParentRoute: () => root, path: "/popout/edit/$clipId", component: () => <EditScreen popout /> });
const notFound = createRoute({
  getParentRoute: () => root,
  path: "$",
  beforeLoad: () => {
    throw redirect({ to: "/" });
  },
});

export const routeTree = root.addChildren([
  shell.addChildren([overview, agents, campaigns, library, clipDetail, reviewIndex, review, edit, publishing, earnings, settings]),
  setup,
  gallery,
  popReview,
  popEdit,
  notFound,
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history, defaultPreload: false, scrollRestoration: false });
}

export const router = createAppRouter();

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
