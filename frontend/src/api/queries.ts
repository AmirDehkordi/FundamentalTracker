import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/api/client";
import type {
  CompanyOut,
  CompareOut,
  FreshnessOut,
  FundamentalsOut,
  InsiderSummaryOut,
  PricesOut,
  RiskDiffOut,
  ValuationOut,
} from "@/api/contracts";

/** Backend-supported price windows. MAX in the UI maps to "2y" (the widest window stored). */
export type PriceRange = "1m" | "6m" | "1y" | "2y";

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

/** Annual fundamentals matrix (levels + derived) with YoY, for the selected company. */
export function useFundamentals(ticker: string | null) {
  return useQuery<FundamentalsOut, ApiError>({
    queryKey: ["fundamentals", ticker],
    queryFn: () =>
      apiFetch<FundamentalsOut>(`/api/companies/${ticker}/fundamentals`),
    enabled: ticker != null,
  });
}

/**
 * Daily prices + 10-K markers. Always fetches the full 2y window; the chart slices it client-side per
 * range selector, so switching ranges is instant and re-uses one cache entry.
 */
export function usePrices(ticker: string | null) {
  return useQuery<PricesOut, ApiError>({
    queryKey: ["prices", ticker],
    queryFn: () =>
      apiFetch<PricesOut>(`/api/companies/${ticker}/prices?range=2y`),
    enabled: ticker != null,
  });
}

/** Item 1A year-over-year risk-factor diff for the selected company. */
export function useRiskDiff(ticker: string | null) {
  return useQuery<RiskDiffOut, ApiError>({
    queryKey: ["risk-diff", ticker],
    queryFn: () => apiFetch<RiskDiffOut>(`/api/companies/${ticker}/risk-diff`),
    enabled: ticker != null,
  });
}

/** Form 4 insider summary (90d / 365d windows) for the selected company. */
export function useInsider(ticker: string | null) {
  return useQuery<InsiderSummaryOut, ApiError>({
    queryKey: ["insider", ticker],
    queryFn: () =>
      apiFetch<InsiderSummaryOut>(`/api/companies/${ticker}/insider`),
    enabled: ticker != null,
  });
}

/** Cross-company comparison of one metric on the latest-reported-FY-per-company basis. */
export function useCompare(metric: string) {
  return useQuery<CompareOut, ApiError>({
    queryKey: ["compare", metric],
    queryFn: () =>
      apiFetch<CompareOut>(`/api/compare?metric=${encodeURIComponent(metric)}`),
  });
}
