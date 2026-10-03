import { createContext, useCallback, useMemo, useState, type ReactNode } from 'react';

interface AccountContextValue {
  isOpen: boolean;
  error: string | null;
  pendingSave: boolean;
  open: () => void;
  close: () => void;
  setError: (message: string | null) => void;
  setPendingSave: (pending: boolean) => void;
}

export const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState(false);

  const open = useCallback(() => {
    setError(null);
    setIsOpen(true);
  }, []);
  const close = useCallback(() => {
    setIsOpen(false);
    setError(null);
    setPendingSave(false);
  }, []);

  const value = useMemo<AccountContextValue>(
    () => ({ isOpen, error, pendingSave, open, close, setError, setPendingSave }),
    [isOpen, error, pendingSave, open, close],
  );

  return <AccountContext.Provider value={value}>{children}</AccountContext.Provider>;
}
