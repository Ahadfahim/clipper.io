// Local UI state (UI.md §7): panes, output panel, theme, filters, current review clip.
// Persisted per machine in localStorage; never holds server data.
import { create } from "zustand";
import { createJSONStorage, persist, type StateStorage } from "zustand/middleware";

export type OutputTab = "activity" | "agent" | "jobs" | "problems";
export type Theme = "system" | "light" | "dark";
export type Density = "compact" | "comfortable";

const safeStorage: StateStorage = {
  getItem: (k) => {
    try {
      return window.localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  setItem: (k, v) => {
    try {
      window.localStorage.setItem(k, v);
    } catch {
      /* private window or blocked storage: keep defaults */
    }
  },
  removeItem: (k) => {
    try {
      window.localStorage.removeItem(k);
    } catch {
      /* ignore */
    }
  },
};

type UiState = {
  theme: Theme;
  density: Density;
  accent: string | null; // user override; null = Windows accent
  systemAccent: string | null;
  outputOpen: boolean;
  outputTab: OutputTab;
  treeOpen: Record<string, boolean>;
  commandOpen: boolean;
  commandSeed: string;
  settingsOpen: boolean;
  settingsSection: string;
  stopOpen: boolean;
  reviewClip: Record<number, number>; // batch id → selected clip id
  campaignTab: "suggested" | "active" | "ended" | "skipped";
  campaignMarket: "all" | "vyro" | "whop";
  setTheme: (t: Theme) => void;
  setDensity: (d: Density) => void;
  setAccent: (a: string | null) => void;
  setSystemAccent: (a: string) => void;
  toggleOutput: (open?: boolean) => void;
  setOutputTab: (t: OutputTab) => void;
  toggleTree: (key: string) => void;
  openCommand: (seed?: string) => void;
  closeCommand: () => void;
  openSettings: (section?: string) => void;
  closeSettings: () => void;
  setStopOpen: (open: boolean) => void;
  setReviewClip: (batch: number, clip: number) => void;
  setCampaignTab: (t: UiState["campaignTab"]) => void;
  setCampaignMarket: (m: UiState["campaignMarket"]) => void;
};

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      density: "compact",
      accent: null,
      systemAccent: null,
      outputOpen: true,
      outputTab: "activity",
      treeOpen: { agents: true, campaigns: true, publishing: true },
      commandOpen: false,
      commandSeed: "",
      settingsOpen: false,
      settingsSection: "markets",
      stopOpen: false,
      reviewClip: {},
      campaignTab: "active",
      campaignMarket: "all",
      setTheme: (theme) => set({ theme }),
      setDensity: (density) => set({ density }),
      setAccent: (accent) => set({ accent }),
      setSystemAccent: (systemAccent) => set({ systemAccent }),
      toggleOutput: (open) => set((s) => ({ outputOpen: open ?? !s.outputOpen })),
      setOutputTab: (outputTab) => set({ outputTab, outputOpen: true }),
      toggleTree: (key) => set((s) => ({ treeOpen: { ...s.treeOpen, [key]: !s.treeOpen[key] } })),
      openCommand: (seed = "") => set({ commandOpen: true, commandSeed: seed }),
      closeCommand: () => set({ commandOpen: false, commandSeed: "" }),
      openSettings: (section) => set((s) => ({ settingsOpen: true, settingsSection: section ?? s.settingsSection })),
      closeSettings: () => set({ settingsOpen: false }),
      setStopOpen: (stopOpen) => set({ stopOpen }),
      setReviewClip: (batch, clip) => set((s) => ({ reviewClip: { ...s.reviewClip, [batch]: clip } })),
      setCampaignTab: (campaignTab) => set({ campaignTab }),
      setCampaignMarket: (campaignMarket) => set({ campaignMarket }),
    }),
    {
      name: "clipper.ui",
      storage: createJSONStorage(() => safeStorage),
      partialize: (s) => ({
        theme: s.theme,
        density: s.density,
        accent: s.accent,
        outputOpen: s.outputOpen,
        outputTab: s.outputTab,
        treeOpen: s.treeOpen,
        campaignTab: s.campaignTab,
        campaignMarket: s.campaignMarket,
      }),
    },
  ),
);
