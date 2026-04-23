/**
 * Amprealize web console — main application
 *
 * Full-featured SaaS console with authentication, dashboard,
 * collaborative workspaces, and behavior-conditioned inference.
 *
 * Routes:
 * - /login: Authentication (device flow + OAuth)
 * - /auth/callback: OAuth redirect handler
 * - /: Dashboard (protected)
 * - /agents: Agent registry (protected)
 * - /bci: BCI Query panel (protected)
 * - /extraction: Behavior extraction (protected)
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 * - behavior_prototype_consent_ux (Teacher)
 */

import { lazy, Suspense, useState, useCallback } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { AuthProvider, useIsLoggedIn } from './auth';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AppLayout } from './components/workspace/AppLayout';
import { useModules } from './api/modules';
import type { ReflectionCandidate } from './api/reflection';
import './styles/design-system.css';
import './App.css';

const LoginPage = lazy(() => import('./components/LoginPage').then((module) => ({ default: module.LoginPage })));
const OAuthCallback = lazy(() => import('./components/OAuthCallback').then((module) => ({ default: module.OAuthCallback })));
const Dashboard = lazy(() => import('./components/Dashboard').then((module) => ({ default: module.Dashboard })));
const BCIResponsePanel = lazy(() => import('./components/BCIResponsePanel').then((module) => ({ default: module.BCIResponsePanel })));
const ExtractionCandidates = lazy(() => import('./components/ExtractionCandidates').then((module) => ({ default: module.ExtractionCandidates })));
const NotFoundPage = lazy(() => import('./components/NotFoundPage').then((module) => ({ default: module.NotFoundPage })));
const SecuritySettings = lazy(() => import('./components/SecuritySettings').then((module) => ({ default: module.SecuritySettings })));
const FeatureFlagsPage = lazy(() => import('./components/FeatureFlagsPage').then((module) => ({ default: module.FeatureFlagsPage })));
const ProjectsPage = lazy(() => import('./components/projects/ProjectsPage').then((module) => ({ default: module.ProjectsPage })));
const NewProjectPage = lazy(() => import('./components/projects/NewProjectPage').then((module) => ({ default: module.NewProjectPage })));
const ProjectPage = lazy(() => import('./components/projects/ProjectPage').then((module) => ({ default: module.ProjectPage })));
const ProjectSettingsPage = lazy(() => import('./components/projects/ProjectSettingsPage').then((module) => ({ default: module.ProjectSettingsPage })));
const BoardPage = lazy(() => import('./components/boards/BoardPage').then((module) => ({ default: module.BoardPage })));
const OrganizationsPage = lazy(() => import('./components/orgs/OrganizationsPage').then((module) => ({ default: module.OrganizationsPage })));
const AgentsPage = lazy(() => import('./components/agents/AgentsPage').then((module) => ({ default: module.AgentsPage })));
const GitHubAppCallbackPage = lazy(() => import('./pages/GitHubAppCallbackPage').then((module) => ({ default: module.GitHubAppCallbackPage })));
const WikiPage = lazy(() => import('./components/wiki/WikiPage').then((module) => ({ default: module.WikiPage })));
const WhiteboardPage = lazy(() => import('./components/whiteboard/WhiteboardPage').then((module) => ({ default: module.WhiteboardPage })));

function RouteFallback() {
  return <div className="app-route-fallback animate-fade-in-up">Loading…</div>;
}

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 2,
    },
  },
});

/**
 * BCI Tools Layout - for BCI and Extraction routes (notifications only)
 */
function BCILayout() {
  const [notifications, setNotifications] = useState<string[]>([]);

  const handleAutoApproved = useCallback((candidates: ReflectionCandidate[]) => {
    const message = `✓ Auto-approved ${candidates.length} behavior(s): ${candidates.map(c => c.slug).join(', ')}`;
    setNotifications((prev) => [...prev, message]);
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n !== message));
    }, 5000);
  }, []);

  const handleCandidateApproved = useCallback((candidate: ReflectionCandidate, behaviorId: string) => {
    const message = `✓ Approved behavior "${candidate.display_name}" (ID: ${behaviorId})`;
    setNotifications((prev) => [...prev, message]);
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n !== message));
    }, 5000);
  }, []);

  return (
    <>
      {notifications.length > 0 && (
        <div className="notifications">
          {notifications.map((notification, i) => (
            <div key={i} className="notification">
              {notification}
            </div>
          ))}
        </div>
      )}
      <Routes>
        <Route index element={<BCIResponsePanel />} />
        <Route
          path="extraction"
          element={
            <ExtractionCandidates
              onAutoApproved={handleAutoApproved}
              onCandidateApproved={handleCandidateApproved}
            />
          }
        />
      </Routes>
    </>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<RouteFallback />}>
            <AnimatedRoutes />
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function AnimatedRoutes() {
  const location = useLocation();
  const isLoggedIn = useIsLoggedIn();
  const { isModuleEnabled } = useModules({ enabled: isLoggedIn });

  return (
    <div className="app-route-stage">
      <Routes location={location}>
              {/* Public routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/auth/callback" element={<OAuthCallback />} />
              <Route path="/auth/github-app/callback" element={<GitHubAppCallbackPage />} />

              {/* All protected routes share one WorkspaceShell via AppLayout */}
              <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
                <Route index element={<Dashboard />} />
                {isModuleEnabled('behaviors') && (
                  <Route path="/bci/*" element={<BCILayout />} />
                )}
                <Route path="/settings" element={<SecuritySettings />} />
                <Route path="/settings/feature-flags" element={<FeatureFlagsPage />} />
                <Route path="/orgs" element={<OrganizationsPage />} />
                {isModuleEnabled('agents') && (
                  <Route path="/agents" element={<AgentsPage />}>
                    <Route path="new" element={null} />
                    <Route path=":agentId" element={null} />
                  </Route>
                )}
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/new" element={<NewProjectPage />} />
                <Route path="/projects/:projectId" element={<ProjectPage />} />
                <Route path="/projects/:projectId/settings" element={<ProjectSettingsPage />} />
                <Route path="/projects/:projectId/boards/:boardId" element={<BoardPage />} />
                <Route path="/projects/:projectId/boards/:boardId/items/:itemId" element={<BoardPage />} />
                <Route path="/wiki" element={<WikiPage />} />
                <Route path="/wiki/:domain" element={<WikiPage />} />
                <Route path="/wiki/:domain/*" element={<WikiPage />} />
                {isModuleEnabled('whiteboard') && (
                  <>
                    <Route path="/whiteboard" element={<WhiteboardPage />} />
                    <Route path="/whiteboard/:roomId" element={<WhiteboardPage />} />
                  </>
                )}
              </Route>

              {/* Catch-all */}
              <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </div>
  );
}

export default App;
