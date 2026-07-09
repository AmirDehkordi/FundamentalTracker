/** A question turn: a right-aligned bubble so the thread reads as a conversation. */
export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-lg rounded-br-sm bg-surface-2 px-3 py-2 text-13 text-fg-1">
        {text}
      </p>
    </div>
  );
}
