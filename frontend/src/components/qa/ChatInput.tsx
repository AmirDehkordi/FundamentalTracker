import { SendHorizontal } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";

/** The question box: auto-growing textarea, Enter to send, Shift+Enter for a newline. */
export function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (question: string) => void;
  disabled?: boolean;
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
    <div className="flex items-end gap-2 rounded-md border border-border bg-surface-2 px-3 py-2 focus-within:ring-2 focus-within:ring-ring">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          setValue(e.target.value);
          grow(e.target);
        }}
        onKeyDown={onKeyDown}
        placeholder="Ask about fundamentals, filings, prices, or insider activity"
        aria-label="Ask a question"
        className="max-h-32 flex-1 resize-none bg-transparent text-13 text-fg-1 outline-none placeholder:text-fg-3 disabled:opacity-60"
      />
      <Button
        size="icon"
        onClick={submit}
        disabled={disabled || value.trim() === ""}
        aria-label="Send"
        className="size-8 shrink-0"
      >
        <SendHorizontal className="size-4" aria-hidden />
      </Button>
    </div>
  );
}
