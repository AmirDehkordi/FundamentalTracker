import { createContext, useContext, useState, type ReactNode } from "react";

interface SelectionValue {
  /** The active company's ticker, or null until the first company loads. */
  ticker: string | null;
  setTicker: (ticker: string) => void;
}

const SelectionContext = createContext<SelectionValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState<string | null>(null);
  return (
    <SelectionContext.Provider value={{ ticker, setTicker }}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): SelectionValue {
  const ctx = useContext(SelectionContext);
  if (!ctx)
    throw new Error("useSelection must be used within a SelectionProvider");
  return ctx;
}
