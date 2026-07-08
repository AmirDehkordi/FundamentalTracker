import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/api/client";
import type { CompanyOut, FreshnessOut, ValuationOut } from "@/api/contracts";

/** The tracked universe for the sidebar. Live endpoint. */
export function useCompanies() {
  return useQuery<CompanyOut[], ApiError>({
    queryKey: ["companies"],
    queryFn: () => apiFetch<CompanyOut[]>("/api/companies"),
  });
}

/** Data freshness for the footer / top bar. 501 stub until the backend wires it. */
export function useFreshness() {
  return useQuery<FreshnessOut, ApiError>({
    queryKey: ["freshness"],
    queryFn: () => apiFetch<FreshnessOut>("/api/meta/freshness"),
  });
}

/** Trailing P/E and P/S for the selected company. 501 stub until the backend wires it. */
export function useValuation(ticker: string | null) {
  return useQuery<ValuationOut, ApiError>({
    queryKey: ["valuation", ticker],
    queryFn: () => apiFetch<ValuationOut>(`/api/companies/${ticker}/valuation`),
    enabled: ticker != null,
  });
}
