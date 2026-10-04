import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import * as Tip from "@radix-ui/react-tooltip";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { useAppearance } from "@/lib/theme";
import { router } from "@/routes/router";
import "./styles/index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1 } },
});

function App() {
  useAppearance();
  return (
    <QueryClientProvider client={queryClient}>
      <Tip.Provider>
        <RouterProvider router={router} />
      </Tip.Provider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
