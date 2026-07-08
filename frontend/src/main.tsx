import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { App } from "@/App";
import { ApiError } from "@/api/client";
import { SelectionProvider } from "@/state/selection";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Deterministic responses (4xx, 501 not-ready) never recover on retry — surface them at once.
      // Transient failures (network, 5xx) get a couple of retries.
      retry: (failureCount, error) => {
        if (
          error instanceof ApiError &&
          (error.status === 501 || (error.status >= 400 && error.status < 500))
        ) {
          return false;
        }
        return failureCount < 2;
      },
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SelectionProvider>
        <App />
      </SelectionProvider>
    </QueryClientProvider>
  </StrictMode>,
);
