/** A subtle 3-dot pulse shown while the answer is in flight. Static under prefers-reduced-motion. */
export function ThinkingRow() {
  return (
    <div className="flex items-center gap-1 px-1 py-2" aria-live="polite">
      <span className="sr-only">Thinking</span>
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 animate-pulse rounded-full bg-fg-3"
          style={{ animationDelay: `${delay}ms` }}
          aria-hidden
        />
      ))}
    </div>
  );
}
