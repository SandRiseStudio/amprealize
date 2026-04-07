/**
 * ShellContext Provider
 *
 * Lightweight context for child pages to control WorkspaceShell props
 * (document title, shell mode) without remounting the shell.
 */

import { useCallback, useState, type ReactNode } from 'react';
import { ShellContext } from './shellContextValue';
import type { ShellMode } from './shellContextValue';

export type { ShellMode };
export { ShellContext };

export function ShellContextProvider({ children }: { children: ReactNode }) {
  const [documentTitle, setDocumentTitleRaw] = useState('');
  const [mode, setModeRaw] = useState<ShellMode>('default');

  const setDocumentTitle = useCallback((title: string) => {
    setDocumentTitleRaw(title);
  }, []);

  const setMode = useCallback((m: ShellMode) => {
    setModeRaw(m);
  }, []);

  return (
    <ShellContext.Provider value={{ documentTitle, setDocumentTitle, mode, setMode }}>
      {children}
    </ShellContext.Provider>
  );
}
