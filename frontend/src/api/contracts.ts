/*
 * Wire types for the API. Two sources:
 *   A. Generated — re-exported from the openapi-typescript output (src/api/types.ts). Permanent.
 *   B. TEMPORARY hand mirrors of FROZEN contracts that openapi.json does not yet expose, because
 *      their routes are 501 stubs with no response_model. The source of truth is
 *      backend/src/tracker/api/schemas.py. Delete each mirror and move its type up into section A the
 *      moment the matching route registers a response_model and `npm run gen:types` re-emits it.
 *      Pydantic `date` fields serialize as ISO strings on the wire, so they are typed `string` here.
 */
import type { components } from "@/api/types";

// --- A. Generated (permanent) ------------------------------------------------------------------
export type CompanyOut = components["schemas"]["CompanyOut"];
export type ErrorOut = components["schemas"]["ErrorOut"];

// --- B. Temporary mirrors (delete per-route as the backend registers response models) -----------
export type MetricUnit = "USD" | "USD/shares" | "shares" | "percent" | "ratio";

export interface MetricValue {
  value: number | null;
  unit: MetricUnit;
  reason?: string | null;
  accession?: string | null;
  superseded_value?: number | null;
  superseded_filed?: string | null;
}

export interface EpsSource {
  fiscal_year: number;
  period_end: string;
  accession: string;
  label: string;
}

export interface ValuationOut {
  ticker: string;
  cik: number;
  trailing_pe: MetricValue;
  trailing_ps: MetricValue;
  close: number;
  price_as_of: string;
  eps_source: EpsSource;
  basis_note?: string | null;
}

export interface FreshnessOut {
  max_price_date: string | null;
  max_filed_date: string | null;
  source_counts: Record<string, number>;
  company_count: number;
}
