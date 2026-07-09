import { ExternalLink } from "lucide-react";

import type { Citation } from "@/api/contracts";
import { citationLabel } from "@/components/qa/labels";

const PILL =
  "inline-flex items-center gap-1 rounded-md border border-border bg-surface-2 px-2 py-0.5 text-xs tabular-nums";

/** Grounding pills under an answer: linked to the SEC filing when a url is present. */
export function CitationPills({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((c, i) => {
        const label = citationLabel(c);
        return (
          <li key={i}>
            {c.url ? (
              <a
                href={c.url}
                target="_blank"
                rel="noopener noreferrer"
                title={c.detail}
                aria-label={`${label} — opens the SEC filing in a new tab`}
                className={`focus-ring ${PILL} text-brand hover:bg-accent-bg`}
              >
                {label}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : (
              <span title={c.detail} className={`${PILL} text-fg-2`}>
                {label}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
