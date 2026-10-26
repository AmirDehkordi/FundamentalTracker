import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";

import type { ApiError } from "@/api/client";
import { ErrorState } from "@/components/states";

type QueryLike<T> = Pick<
  UseQueryResult<T, ApiError>,
  "data" | "isPending" | "isError" | "isFetching" | "error" | "refetch"
>;

interface AsyncBoundaryProps<T> {
  query: QueryLike<T>;
  /** Pulse blocks matching the final content geometry. */
  skeleton: ReactNode;
  children: (data: T) => ReactNode;
  /** Per-endpoint emptiness (domain-specific, never guessed). Defaults to never-empty. */
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  errorTitle?: string;
  /** Rendered instead of the error state when the query fails with a not-ready status (default 501). */
  notReady?: ReactNode;
  notReadyStatuses?: number[];
  onRetry?: () => void;
  className?: string;
}

/** Emptiness helper for list endpoints. */
export function isEmptyArray<T>(a: T[]): boolean {
  return a.length === 0;
}

/**
 * Renders exactly one of skeleton | not-ready | error+retry | empty | content over a single query.
 * `children` only ever sees defined data. Gating the error branch on `data === undefined` keeps stale
 * data on screen if a live endpoint errors on a background refetch (stale-while-error).
 */
export function AsyncBoundary<T>({
  query,
  skeleton,
  children,
  isEmpty = () => false,
  empty,
  errorTitle = "Something went wrong",
  notReady,
  notReadyStatuses = [501],
  onRetry,
  className,
}: AsyncBoundaryProps<T>) {
  const { data, isPending, isError, isFetching, error, refetch } = query;

  if (isPending) return <>{skeleton}</>;

  if (isError && data === undefined) {
    if (notReady && error && notReadyStatuses.includes(error.status)) {
      return <>{notReady}</>;
    }
    return (
      <ErrorState
        title={errorTitle}
        busy={isFetching}
        onRetry={onRetry ?? (() => void refetch())}
        className={className}
      />
    );
  }

  if (data === undefined) return <>{skeleton}</>;
  if (isEmpty(data)) return <>{empty ?? null}</>;
  return <>{children(data)}</>;
}
