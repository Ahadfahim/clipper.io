// TanStack Query hooks for every screen. Keys are shared with the live event stream (live.ts),
// which invalidates them when the server says something changed.
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api, FIXTURE_MODE, fixtureManifest, unwrap, type Schemas } from "./client";

export const qk = {
  status: ["status"],
  overview: ["overview"],
  switches: ["switches"],
  switchPreview: (level: string, name: string) => ["switch-preview", level, name],
  events: ["events"],
  jobs: ["jobs"],
  questions: ["questions"],
  notes: ["notes"],
  board: ["board"],
  models: ["models"],
  sessions: ["sessions"],
  session: (id: number) => ["session", id],
  director: ["director"],
  campaigns: ["campaigns"],
  campaign: (id: number) => ["campaign", id],
  clips: ["clips"],
  clip: (id: number) => ["clip", id],
  batches: ["batches"],
  batch: (id: number) => ["batch", id],
  autoApprove: ["auto-approve"],
  edit: (id: number) => ["edit", id],
  accounts: ["accounts"],
  calendar: ["calendar"],
  recipes: ["recipes"],
  earnings: ["earnings"],
  settings: ["settings"],
  lessons: ["lessons"],
  tools: ["tools"],
  prompts: ["prompts"],
  doctor: ["doctor"],
  manifest: ["fixture-manifest"],
} as const;

const live = { refetchOnWindowFocus: !FIXTURE_MODE };

export const useStatus = () =>
  useQuery({ queryKey: qk.status, queryFn: () => unwrap(api.GET("/api/status")), refetchInterval: FIXTURE_MODE ? false : 15_000, ...live });
export const useOverview = () => useQuery({ queryKey: qk.overview, queryFn: () => unwrap(api.GET("/api/overview")), ...live });
export const useSwitches = () => useQuery({ queryKey: qk.switches, queryFn: () => unwrap(api.GET("/api/switches")), ...live });
export const useSwitchPreview = (level: "marketplace" | "social" | "account", name: string, enabled: boolean) =>
  useQuery({
    queryKey: qk.switchPreview(level, name),
    queryFn: () => unwrap(api.GET("/api/switches/preview", { params: { query: { level, name } } })),
    enabled,
  });
export const useJobs = () => useQuery({ queryKey: qk.jobs, queryFn: () => unwrap(api.GET("/api/jobs")), ...live });
export const useQuestions = () => useQuery({ queryKey: qk.questions, queryFn: () => unwrap(api.GET("/api/questions")), ...live });
export const useNotes = () => useQuery({ queryKey: qk.notes, queryFn: () => unwrap(api.GET("/api/notes")), ...live });
export const useModels = () => useQuery({ queryKey: qk.models, queryFn: () => unwrap(api.GET("/api/agents/models")) });
export const useBoard = () =>
  useQuery({ queryKey: qk.board, queryFn: () => unwrap(api.GET("/api/agents/board")), refetchInterval: FIXTURE_MODE ? false : 5_000, ...live });
export const useSessions = () => useQuery({ queryKey: qk.sessions, queryFn: () => unwrap(api.GET("/api/agents/sessions")), ...live });
export const useSession = (id: number | undefined) =>
  useQuery({
    queryKey: qk.session(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/agents/sessions/{session_id}", { params: { path: { session_id: id ?? 0 } } })),
    enabled: id !== undefined,
    ...live,
  });
export const useDirector = () =>
  useQuery({ queryKey: qk.director, queryFn: () => unwrap(api.GET("/api/agents/director/messages")), ...live });
export const useCampaigns = () => useQuery({ queryKey: qk.campaigns, queryFn: () => unwrap(api.GET("/api/campaigns")), ...live });
export const useCampaign = (id: number | undefined) =>
  useQuery({
    queryKey: qk.campaign(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/campaigns/{campaign_id}", { params: { path: { campaign_id: id ?? 0 } } })),
    enabled: id !== undefined,
    ...live,
  });
export const useClips = () => useQuery({ queryKey: qk.clips, queryFn: () => unwrap(api.GET("/api/clips")), ...live });
export const useClip = (id: number | undefined) =>
  useQuery({
    queryKey: qk.clip(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/clips/{clip_id}", { params: { path: { clip_id: id ?? 0 } } })),
    enabled: id !== undefined,
    ...live,
  });
export const useBatches = () => useQuery({ queryKey: qk.batches, queryFn: () => unwrap(api.GET("/api/review/batches")), ...live });
export const useBatch = (id: number | undefined) =>
  useQuery({
    queryKey: qk.batch(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/review/batches/{batch_id}", { params: { path: { batch_id: id ?? 0 } } })),
    enabled: id !== undefined,
    ...live,
  });
export const useAutoApprove = () =>
  useQuery({ queryKey: qk.autoApprove, queryFn: () => unwrap(api.GET("/api/review/auto-approve")), ...live });
export const useEditState = (id: number | undefined) =>
  useQuery({
    queryKey: qk.edit(id ?? 0),
    queryFn: () => unwrap(api.GET("/api/edit/{clip_id}", { params: { path: { clip_id: id ?? 0 } } })),
    enabled: id !== undefined,
    ...live,
  });
export const useAccounts = () =>
  useQuery({ queryKey: qk.accounts, queryFn: () => unwrap(api.GET("/api/publishing/accounts")), ...live });
export const useCalendar = () =>
  useQuery({ queryKey: qk.calendar, queryFn: () => unwrap(api.GET("/api/publishing/calendar")), ...live });
export const useRecipes = () => useQuery({ queryKey: qk.recipes, queryFn: () => unwrap(api.GET("/api/publishing/recipes")), ...live });
export const useEarnings = () => useQuery({ queryKey: qk.earnings, queryFn: () => unwrap(api.GET("/api/earnings")), ...live });
export const useSettings = () => useQuery({ queryKey: qk.settings, queryFn: () => unwrap(api.GET("/api/settings")) });
export const useLessons = () => useQuery({ queryKey: qk.lessons, queryFn: () => unwrap(api.GET("/api/settings/lessons")) });
export const useTools = () => useQuery({ queryKey: qk.tools, queryFn: () => unwrap(api.GET("/api/settings/tools")) });
export const usePrompts = () => useQuery({ queryKey: qk.prompts, queryFn: () => unwrap(api.GET("/api/settings/prompts")) });
export const useDoctor = () => useQuery({ queryKey: qk.doctor, queryFn: () => unwrap(api.GET("/api/doctor")) });

/** Fixture manifest (maps /api/files/... to exported media); null outside fixture mode. */
export const useManifest = () =>
  useQuery({ queryKey: qk.manifest, queryFn: () => (FIXTURE_MODE ? fixtureManifest() : Promise.resolve(null)), staleTime: Infinity });

/**
 * A mutation that refreshes the given keys on success. Pass `optimistic` to update the cache
 * right away (Review decisions, switches): the screen moves first, the server confirms after.
 * In fixture mode nothing is saved, so the optimistic state is kept instead of refetching.
 */
export function useAction<TVars>(opts: {
  run: (vars: TVars) => Promise<unknown>;
  invalidate?: (vars: TVars) => QueryKey[];
  optimistic?: (vars: TVars, qc: ReturnType<typeof useQueryClient>) => void;
}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (vars: TVars) => {
      opts.optimistic?.(vars, qc);
      return opts.run(vars);
    },
    onSettled: (_data, _err, vars) => {
      if (FIXTURE_MODE) return;
      for (const key of opts.invalidate?.(vars) ?? []) void qc.invalidateQueries({ queryKey: key });
    },
  });
}

export type { Schemas };
