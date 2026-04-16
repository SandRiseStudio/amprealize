import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { OAuthCallback } from '../components/OAuthCallback';
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

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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

describe('OAuthCallback', () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue(makeAuthMock() as never);
  });

  afterEach(() => {
    vi.useRealTimers();
    mockNavigate.mockReset();
    vi.clearAllMocks();
  });

  it('shows a processing state and redirects immediately after successful OAuth completion', async () => {
    const exchange = deferred<void>();
    const completeOAuthLogin = vi.fn().mockReturnValue(exchange.promise);
    const logout = vi.fn().mockResolvedValue(undefined);

    vi.mocked(useAuth).mockReturnValue(
      makeAuthMock({ completeOAuthLogin, logout }) as never,
    );

    render(
      <MemoryRouter initialEntries={['/auth/callback?code=abc123&state=xyz']}>
        <Routes>
          <Route path="/auth/callback" element={<OAuthCallback />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText(/verifying your credentials/i)).toBeInTheDocument();
    expect(screen.getByText(/preparing your Amprealize session/i)).toBeInTheDocument();

    exchange.resolve();

    await waitFor(() => {
      expect(screen.getByText(/sign-in successful/i)).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(completeOAuthLogin).toHaveBeenCalledWith('abc123', 'xyz');
      expect(mockNavigate).toHaveBeenCalledWith('/', { replace: true });
    }, { timeout: 1500 });
  });

  it('shows a recovery action when OAuth completion fails', async () => {
    const user = userEvent.setup();
    const completeOAuthLogin = vi.fn().mockRejectedValue(new Error('Token exchange failed'));

    vi.mocked(useAuth).mockReturnValue(
      makeAuthMock({ completeOAuthLogin }) as never,
    );

    render(
      <MemoryRouter initialEntries={['/auth/callback?code=abc123&state=xyz']}>
        <Routes>
          <Route path="/auth/callback" element={<OAuthCallback />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/authentication did not complete/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /return to sign in/i }));

    expect(mockNavigate).toHaveBeenCalledWith('/login', { replace: true });
  });
});
