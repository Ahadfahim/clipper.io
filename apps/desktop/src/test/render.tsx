import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import * as Tip from "@radix-ui/react-tooltip";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createAppRouter } from "@/routes/router";

export function freshClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
}

/** Renders the real app (shell + screens) at `path`, answering API calls from the fixture export. */
export function renderApp(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const qc = freshClient();
  const utils = render(
    <QueryClientProvider client={qc}>
      <Tip.Provider>
        <RouterProvider router={router} />
      </Tip.Provider>
    </QueryClientProvider>,
  );
  return { ...utils, router, qc };
}

export function withProviders(ui: ReactNode) {
  const qc = freshClient();
  return render(
    <QueryClientProvider client={qc}>
      <Tip.Provider>{ui}</Tip.Provider>
    </QueryClientProvider>,
  );
}
