export interface OAuthStatePayload {
  provider: 'github' | 'google';
  nonce: string;
  ts: number;
  returnTo?: string;
  popup?: boolean;
}

export function createOAuthState(payload: Omit<OAuthStatePayload, 'nonce' | 'ts'>): string {
  const completePayload: OAuthStatePayload = {
    ...payload,
    nonce: typeof crypto?.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}_${Math.random().toString(36).slice(2)}`,
    ts: Date.now(),
  };

  const encoded = btoa(JSON.stringify(completePayload));
  return encoded.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

export function parseOAuthState(state: string | null | undefined): OAuthStatePayload | null {
  if (!state) return null;

  try {
    const normalized = state
      .replace(/-/g, '+')
      .replace(/_/g, '/')
      .padEnd(Math.ceil(state.length / 4) * 4, '=');
    return JSON.parse(atob(normalized)) as OAuthStatePayload;
  } catch {
    return null;
  }
}
