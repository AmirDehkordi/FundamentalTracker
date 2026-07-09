import { Loader2, SendHorizontal } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";

/** The question box: auto-growing textarea, Enter to send, Shift+Enter for a newline. */
export function ChatInput({
  onSend,
  disabled,
  loading,
}: {
  onSend: (question: string) => void;
  disabled?: boolean;
  loading?: boolean;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const grow = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  };

  const submit = () => {
    const q = value.trim();
    if (!q || disabled) return;
    onSend(q);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // isComposing: don't send on the Enter that commits an IME candidate.
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex items-end gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2.5 focus-within:ring-2 focus-within:ring-ring">
      <textarea
        ref={ref}
        rows={2}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          setValue(e.target.value);
          grow(e.target);
        }}
        onKeyDown={onKeyDown}
        placeholder="Ask about fundamentals, filings, prices, or insider activity"
        aria-label="Ask a question"
        // Taller default (min-h) with a larger cap; the internal scrollbar is hidden so it stays clean
        // next to the send button (Enter sends before it ever needs to scroll far anyway).
        className="max-h-52 min-h-[60px] flex-1 resize-none bg-transparent text-13 leading-relaxed text-fg-1 outline-none [scrollbar-width:none] placeholder:text-fg-3 disabled:opacity-60 [&::-webkit-scrollbar]:hidden"
      />
      <Button
        size="icon"
        onClick={submit}
        disabled={disabled || value.trim() === ""}
        aria-label="Send"
        className="size-8 shrink-0"
      >
        {loading ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : (
          <SendHorizontal className="size-4" aria-hidden />
        )}
      </Button>
    </div>
  );
}
