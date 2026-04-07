/**
 * Console Sidebar
 *
 * Shared sidebar navigation used across console pages.
 */

import { memo } from 'react';
import { SidebarNav } from './sidebar/SidebarNav';

export type ConsoleSidebarSelectedId =
  | 'dashboard'
  | 'orgs'
  | 'projects'
  | 'projects-new'
  | 'agents'
  | 'bci'
  | 'extraction';

interface ConsoleSidebarProps {
  selectedId: ConsoleSidebarSelectedId;
  onNavigate: (path: string) => void;
}

export const ConsoleSidebar = memo(function ConsoleSidebar({ selectedId, onNavigate }: ConsoleSidebarProps) {
  return <SidebarNav selectedId={selectedId} onNavigate={onNavigate} />;
});
