import { ExternalLink, Minus, Plus } from "lucide-react";

import type { FilingRef, RiskDiffOut, RiskThemeItem } from "@/api/contracts";
import { useRiskDiff, useRiskDiffThemes } from "@/api/queries";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useSelection } from "@/state/selection";

// Tint backgrounds need alpha over the token hue (mirrors DeltaChip.tsx's TONE map).
const CHIP_TONE = {
  pos: { text: "text-pos", bg: "rgba(69,200,138,0.14)" },
  neg: { text: "text-neg", bg: "rgba(229,115,107,0.14)" },
} as const;

function ParagraphCountChip({
  count,
  tone,
}: {
  count: number;
  tone: "pos" | "neg";
}) {
  const t = CHIP_TONE[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium tabular-nums",
        t.text,
      )}
      style={{ backgroundColor: t.bg }}
    >
      {count} {count === 1 ? "paragraph" : "paragraphs"}
    </span>
  );
}

/** One side's up-to-3 theme cards (title + summary + source-paragraph count), plus the SEC link-out
 *  for the fiscal year those themes were clustered from. */
function ThemeGroup({
  title,
  tone,
  themes,
  filing,
}: {
  title: string;
  tone: "pos" | "neg";
  themes: RiskThemeItem[];
  filing: FilingRef | null;
}) {
  const Icon = tone === "pos" ? Plus : Minus;
  return (
    <div className="border-b border-border py-2.5 last:border-b-0">
      <div className="mb-1.5 text-xs font-medium text-fg-1">{title}</div>
      {themes.length === 0 ? (
        <p className="text-xs text-fg-3">No themes {title.toLowerCase()}.</p>
      ) : (
        <ul className="space-y-2">
          {themes.map((theme, i) => (
            <li key={i} className="text-xs leading-snug">
              <div className="flex flex-wrap items-center gap-1.5">
                <Icon
                  className={cn(
                    "size-3 shrink-0",
                    tone === "pos" ? "text-pos" : "text-neg",
                  )}
                  aria-hidden
                />
                <span className="font-medium text-fg-1">{theme.title}</span>
                <ParagraphCountChip count={theme.paragraph_count} tone={tone} />
              </div>
              {/* Indent to the title's start, not the icon's — size-3 (12px) + gap-1.5 (6px). */}
              <span className="mt-1 block pl-[18px] text-fg-3">
                {theme.summary}
              </span>
            </li>
          ))}
        </ul>
      )}
      {filing && (
        <a
          href={filing.primary_doc_url}
          target="_blank"
          rel="noopener noreferrer"
          className="focus-ring mt-2 inline-flex items-center gap-1 rounded text-xs text-brand hover:underline"
        >
          Read the FY{filing.fiscal_year} 10-K on SEC.gov
          <ExternalLink className="size-3" aria-hidden />
        </a>
      )}
    </div>
  );
}

/**
 * Top-3 added / top-3 removed risk THEMES for the Item 1A diff — the card's primary content. Unlike
 * the old raw-paragraph list, there is no fallback content to fall back to on failure, so this shows
 * a real skeleton/empty/error state via AsyncBoundary rather than hiding on a non-200.
 */
function RiskThemesSection({
  ticker,
  latest,
  prior,
}: {
  ticker: string;
  latest: FilingRef | null;
  prior: FilingRef | null;
}) {
  const query = useRiskDiffThemes(ticker);
  return (
    <AsyncBoundary
      query={query}
      skeleton={
        <div className="space-y-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      }
      isEmpty={(d) =>
        d.added_themes.length === 0 && d.removed_themes.length === 0
      }
      empty={
        <p className="text-xs leading-snug text-fg-3">
          No material change in the risk factors this year.
        </p>
      }
      errorTitle="Couldn't load risk themes"
    >
      {(data) => (
        <div className="border-t border-border">
          <ThemeGroup
            title="Added"
            tone="pos"
            themes={data.added_themes}
            filing={latest}
          />
          <ThemeGroup
            title="Removed"
            tone="neg"
            themes={data.removed_themes}
            filing={prior}
          />
        </div>
      )}
    </AsyncBoundary>
  );
}

function RiskDiffBody({ data }: { data: RiskDiffOut }) {
  if (!data.available) {
    return (
      <p className="text-xs leading-snug text-fg-3">
        {data.note ?? "Year-over-year risk-factor diff is unavailable."}
      </p>
    );
  }
  const { latest, prior } = data;
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-fg-2">
        <span className="whitespace-nowrap tabular-nums">
          {latest ? `FY${latest.fiscal_year}` : "—"} vs{" "}
          {prior ? `FY${prior.fiscal_year}` : "—"}
        </span>
      </div>
      <RiskThemesSection ticker={data.ticker} latest={latest} prior={prior} />
    </div>
  );
}

/** Top-3 risk THEMES added/removed between the two most recent 10-Ks, with SEC link-outs. */
export function RiskDiffCard() {
  const { ticker } = useSelection();
  const query = useRiskDiff(ticker);

  return (
    <Panel
      title="Risk factors: what changed"
      info="Top 3 themes clustered from a deterministic year-over-year diff of 10-K Item 1A paragraphs (added/removed, not editorial)."
      fillHeight={false}
    >
      <AsyncBoundary
        query={query}
        skeleton={
          <div className="space-y-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        }
        errorTitle="Couldn't load risk-factor diff"
      >
        {(data) => <RiskDiffBody data={data} />}
      </AsyncBoundary>
    </Panel>
  );
}
