import { Button } from "@/components/ui/button";
import { EXAMPLE_QUESTIONS } from "@/components/qa/labels";

/** The onboarding chips shown in the empty state — one per brief example question. */
export function ExampleChips({
  onPick,
  disabled,
}: {
  onPick: (question: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      {EXAMPLE_QUESTIONS.map((ex) => (
        <Button
          key={ex.label}
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => onPick(ex.question)}
          className="h-auto justify-start whitespace-normal py-2 text-left text-13 font-normal text-fg-2"
        >
          {ex.label}
        </Button>
      ))}
    </div>
  );
}
