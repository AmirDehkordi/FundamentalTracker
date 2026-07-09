import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// react-markdown escapes raw HTML by default (no rehype-raw here) -> safe to render untrusted model
// output. Element styling rides on Tailwind arbitrary child-variants on the wrapper; only <a> and
// <table> get real components (target/rel, horizontal scroll). Reading props.* instead of spreading
// keeps react-markdown's internal `node` prop off the DOM.
const components: Components = {
  a: (props) => (
    <a
      href={typeof props.href === "string" ? props.href : undefined}
      target="_blank"
      rel="noopener noreferrer"
      className="focus-ring rounded text-brand hover:underline"
    >
      {props.children}
    </a>
  ),
  table: (props) => (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full border-collapse text-13 tabular-nums">
        {props.children}
      </table>
    </div>
  ),
};

const PROSE = [
  "text-13 leading-relaxed text-fg-2",
  "[&>*:first-child]:mt-0",
  "[&_p]:mt-2",
  "[&_strong]:font-semibold [&_strong]:text-fg-1",
  "[&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-4",
  "[&_ol]:mt-2 [&_ol]:list-decimal [&_ol]:pl-4",
  "[&_li]:mt-1 [&_li]:leading-snug",
  "[&_h1]:mt-2 [&_h1]:text-sm [&_h1]:font-semibold [&_h1]:text-fg-1",
  "[&_h2]:mt-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-fg-1",
  "[&_h3]:mt-2 [&_h3]:text-13 [&_h3]:font-semibold [&_h3]:text-fg-1",
  "[&_code]:rounded [&_code]:bg-surface-2 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-xs [&_code]:text-fg-1",
  "[&_pre]:mt-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-surface-2 [&_pre]:p-3 [&_pre]:text-xs",
  "[&_blockquote]:mt-2 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-fg-3",
  "[&_th]:border-b [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:text-xs [&_th]:uppercase [&_th]:tracking-wide [&_th]:text-fg-2",
  "[&_td]:border-b [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_td]:tabular-nums [&_td]:text-fg-2",
].join(" ");

/** Renders a trusted-but-untrusted-markdown answer with GFM tables, on-theme and XSS-safe. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className={PROSE}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
