/**
 * AppLayout
 *
 * Shared layout route that renders WorkspaceShell once for all protected pages.
 * The sidebar and header persist across route changes — no remounting,
 * no SSE reconnection, no polling restarts.
 */

import { Outlet, useNavigate } from 'react-router-dom';
import { WorkspaceShell } from './WorkspaceShell';
import { ConsoleSidebar } from '../ConsoleSidebar';
import { ShellContextProvider } from './ShellContext';
import { useShellContext } from './useShell';

function AppLayoutInner() {
  const navigate = useNavigate();
  const { documentTitle, mode } = useShellContext();

  return (
    <WorkspaceShell
      sidebarContent={<ConsoleSidebar selectedId="dashboard" onNavigate={(path) => navigate(path)} />}
      documentTitle={documentTitle}
      mode={mode}
    >
      <Outlet />
    </WorkspaceShell>
  );
}

export function AppLayout() {
  return (
    <ShellContextProvider>
      <AppLayoutInner />
    </ShellContextProvider>
  );
}
