import type { Exchange } from "@/state/conversation";
import { AssistantMessage } from "@/components/qa/AssistantMessage";
import { UserMessage } from "@/components/qa/UserMessage";

/** The settled thread: each exchange as a question bubble followed by its answer. */
export function ExchangeList({ exchanges }: { exchanges: Exchange[] }) {
  return (
    <>
      {exchanges.map((x) => (
        <div key={x.id} className="flex flex-col gap-2">
          <UserMessage text={x.question} />
          <AssistantMessage answer={x.answer} />
        </div>
      ))}
    </>
  );
}
