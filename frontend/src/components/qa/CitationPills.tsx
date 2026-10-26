import { ExternalLink } from "lucide-react";

import type { Citation } from "@/api/contracts";
import { citationDetailHint, citationLabel } from "@/components/qa/labels";

const PILL =
  "inline-flex items-center gap-1 rounded-md border border-border bg-surface-2 px-2 py-0.5 text-xs tabular-nums";

// The citation url is model-controlled (the LLM fills it), so only link it when it is genuinely an
// SEC Archives https URL — never trust a raw href (javascript:/data:/off-site) from model output.
function secHref(url: string | null | undefined): string | null {
  return typeof url === "string" && /^https:\/\/(www\.)?sec\.gov\//i.test(url)
    ? url
    : null;
}

/** Grounding pills under an answer: linked to the SEC filing when a valid SEC url is present. */
export function CitationPills({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  // Same-FY same-accession citations (q1 cites revenue and net income separately) would render
  // identical faces; disambiguate colliding faces with the leading words of each detail.
  const faces = citations.map(citationLabel);
  const collisions = new Set(
    faces.filter((face, i) => faces.indexOf(face) !== i),
  );
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((c, i) => {
        const base = faces[i];
        const hint = collisions.has(base) ? citationDetailHint(c.detail) : null;
        const label = hint ? `${base} · ${hint}` : base;
        const href = secHref(c.url);
        return (
          <li key={i}>
            {href ? (
              <a
                href={href}
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
