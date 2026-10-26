import { useMutation, useQueries, useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/api/client";
import type {
  AskRequest,
  CompanyOut,
  CompareOut,
  FinalAnswer,
  FreshnessOut,
  FundamentalsOut,
  InsiderSummaryOut,
  PricesOut,
  RiskDiffOut,
  RiskDiffThemesOut,
  ValuationOut,
} from "@/api/contracts";

/** Backend-supported price windows. The chart fetches "3y" once (2y displayed + ~1y so the 150-day
 *  MA is defined from the first visible day) and slices client-side; the UI's MAX button shows 2y. */
export type PriceRange = "1m" | "6m" | "1y" | "2y" | "3y";

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
 * All companies' fundamentals in parallel, reusing the per-ticker ["fundamentals", t] cache so the
 * Compare tab shares the Overview tab's fetches. Partial failures degrade (a company drops out); only
 * an all-failed result is treated as an error. Powers the client-side per-company YoY on Compare.
 */
export function useAllFundamentals(tickers: string[]) {
  return useQueries({
    queries: tickers.map((t) => ({
      queryKey: ["fundamentals", t],
      queryFn: () =>
        apiFetch<FundamentalsOut>(`/api/companies/${t}/fundamentals`),
    })),
    combine: (results) => ({
      byTicker: Object.fromEntries(
        tickers.map((t, i) => [t, results[i]?.data]),
      ) as Record<string, FundamentalsOut | undefined>,
      isPending: results.some((r) => r.isPending),
      allError: results.length > 0 && results.every((r) => r.isError),
    }),
  });
}

/**
 * Daily prices + 10-K markers. Fetches 3y (2y displayed + ~1y of MA warmup); the chart computes the
 * 150-day MA over the full series then slices it client-side per range selector, so the overlay is
 * defined across the whole visible window and switching ranges is instant on one cache entry.
 */
export function usePrices(ticker: string | null) {
  return useQuery<PricesOut, ApiError>({
    queryKey: ["prices", ticker],
    queryFn: () =>
      apiFetch<PricesOut>(`/api/companies/${ticker}/prices?range=3y`),
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

/**
 * Top-3 added / top-3 removed risk THEMES for the Item 1A diff — the card's primary content. Always
 * fetches (not feature-flagged) and the card shows a real error state on failure.
 */
export function useRiskDiffThemes(ticker: string | null) {
  return useQuery<RiskDiffThemesOut, ApiError>({
    queryKey: ["risk-diff-themes", ticker],
    queryFn: () =>
      apiFetch<RiskDiffThemesOut>(`/api/companies/${ticker}/risk-diff/themes`),
    enabled: ticker != null,
    retry: false,
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

/**
 * Grounded natural-language Q&A. The endpoint always answers 200 (declines/refusals arrive as a
 * `declined` FinalAnswer), so `retry: false`: a real transport error won't recover on retry, and a
 * declined answer isn't an error. The server caps latency at ~75s, so no client-side timeout.
 */
export function useAsk() {
  return useMutation<FinalAnswer, ApiError, AskRequest>({
    mutationFn: (req) =>
      apiFetch<FinalAnswer>("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      }),
    retry: false,
  });
}
