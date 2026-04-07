import { useContext, useEffect } from 'react';
import { ShellContext } from './shellContextValue';
import type { ShellMode } from './shellContextValue';

/** Set document title from a page component. */
export function useShellTitle(title: string) {
  const { setDocumentTitle } = useContext(ShellContext);
  useEffect(() => {
    setDocumentTitle(title);
  }, [title, setDocumentTitle]);
}

/** Set shell mode from a page component. Resets to 'default' on unmount. */
export function useShellMode(mode: ShellMode) {
  const { setMode } = useContext(ShellContext);
  useEffect(() => {
    setMode(mode);
    return () => setMode('default');
  }, [mode, setMode]);
}

export function useShellContext() {
  return useContext(ShellContext);
}
