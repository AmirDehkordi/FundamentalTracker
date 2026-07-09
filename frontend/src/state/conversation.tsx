import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { ApiError } from "@/api/client";
import type { AskRequest, FinalAnswer, Message } from "@/api/contracts";
import { useAsk } from "@/api/queries";

/** A completed question -> answer pair. Only settled exchanges live here (see `pending`). */
export interface Exchange {
  id: string;
  question: string;
  answer: FinalAnswer;
}

interface ConversationValue {
  exchanges: Exchange[];
  /** The in-flight OR last-failed question. Kept out of `exchanges` so history stays well-formed. */
  pending: string | null;
  isThinking: boolean;
  isError: boolean;
  error: ApiError | null;
  send: (question: string) => void;
  retry: () => void;
}

const ConversationContext = createContext<ConversationValue | null>(null);

function toHistory(exchanges: Exchange[]): Message[] {
  return exchanges.flatMap((x): Message[] => [
    { role: "user", content: x.question },
    { role: "assistant", content: x.answer.answer_md },
  ]);
}

// The id is only a React key. crypto.randomUUID throws outside a secure context (plain HTTP on a
// non-localhost host), so fall back rather than crash the render and drop the answer.
function newExchangeId(): string {
  return (
    crypto.randomUUID?.() ??
    `ex-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

/**
 * Owns the Q&A conversation AND the ask mutation, mounted above the Sheet so both survive its
 * unmount on close (a request fired then closed still lands its answer). One request is in flight at
 * a time (the input disables while pending), so the mutation's own status IS the per-message state.
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const { mutate, isPending, isError, error } = useAsk();
  const lastReq = useRef<AskRequest | null>(null);

  const fire = useCallback(
    (req: AskRequest) => {
      lastReq.current = req;
      setPending(req.question);
      mutate(req, {
        onSuccess: (answer) => {
          setExchanges((prev) => [
            ...prev,
            { id: newExchangeId(), question: req.question, answer },
          ]);
          setPending(null);
        },
        // onError: leave `pending` set so the failed question + a Retry stay on screen.
      });
    },
    [mutate],
  );

  const send = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q || isPending) return;
      fire({ question: q, history: toHistory(exchanges) });
    },
    [exchanges, fire, isPending],
  );

  const retry = useCallback(() => {
    if (isPending || !lastReq.current) return;
    fire(lastReq.current);
  }, [fire, isPending]);

  return (
    <ConversationContext.Provider
      value={{
        exchanges,
        pending,
        isThinking: isPending,
        isError,
        error: error ?? null,
        send,
        retry,
      }}
    >
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversation(): ConversationValue {
  const ctx = useContext(ConversationContext);
  if (!ctx)
    throw new Error(
      "useConversation must be used within a ConversationProvider",
    );
  return ctx;
}
