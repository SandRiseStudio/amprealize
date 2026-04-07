import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LoginPage } from '../components/LoginPage';
import { useAuth } from '../contexts/AuthContext';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}));

function makeAuthMock(overrides: Record<string, unknown> = {}) {
  return {
    isAuthenticated: false,
    isInitialized: true,
    isLoading: false,
    actor: null,
    error: null,
    deviceFlowStatus: 'idle',
    deviceCode: null,
    startLogin: vi.fn().mockResolvedValue(undefined),
    cancelLogin: vi.fn(),
    loginWithClientCredentials: vi.fn().mockResolvedValue(undefined),
    completeOAuthLogin: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    refreshToken: vi.fn().mockResolvedValue(false),
    hasPendingConsent: false,
    nextConsentRequest: null,
    respondToConsent: vi.fn().mockResolvedValue(undefined),
    getAccessToken: vi.fn().mockReturnValue(null),
    getValidAccessToken: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue(makeAuthMock() as never);
  });

  afterEach(() => {
    mockNavigate.mockReset();
    vi.clearAllMocks();
  });

  it('renders human sign-in actions first and keeps agent credentials hidden initially', () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('button', { name: /continue with github/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use browser code instead/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/client id/i)).not.toBeInTheDocument();
  });

  it('reveals agent credentials only after the secondary entry is chosen', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole('button', { name: /signing in an agent or service account/i }));

    expect(screen.getByLabelText(/client id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/client secret/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /continue with github/i })).not.toBeInTheDocument();
  });

  it('preserves the intended redirect destination after authentication', async () => {
    vi.mocked(useAuth).mockReturnValue(
      makeAuthMock({ isAuthenticated: true }) as never,
    );

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/login',
            state: { from: '/projects/demo?view=board' },
          } as never,
        ]}
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/projects/demo?view=board', { replace: true });
    });
  });
});
