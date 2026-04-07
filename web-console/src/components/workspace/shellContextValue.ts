import { createContext } from 'react';

export type ShellMode = 'default' | 'board';

export interface ShellContextValue {
  documentTitle: string;
  setDocumentTitle: (title: string) => void;
  mode: ShellMode;
  setMode: (mode: ShellMode) => void;
}

export const ShellContext = createContext<ShellContextValue>({
  documentTitle: '',
  setDocumentTitle: () => {},
  mode: 'default',
  setMode: () => {},
});
