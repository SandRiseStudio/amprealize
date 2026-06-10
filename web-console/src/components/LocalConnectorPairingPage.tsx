/**
 * Local execution connector — pairing codes and device revoke (REST parity).
 *
 * Following behavior_lock_down_security_surface (Student): uses authenticated API client.
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { apiClient, ApiError } from '../api/client';
import './LocalConnectorPairingPage.css';

interface PairingCodeResponse {
  code: string;
  expires_at: number;
}

export function LocalConnectorPairingPage() {
  const navigate = useNavigate();
  const { actor } = useAuth();
  const userId = actor?.id;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairing, setPairing] = useState<PairingCodeResponse | null>(null);
  const [revokeToken, setRevokeToken] = useState('');
  const [revokeDone, setRevokeDone] = useState(false);

  const createCode = useCallback(async () => {
    if (!userId) {
      setError('You must be signed in to create a pairing code.');
      return;
    }
    setError(null);
    setBusy(true);
    setPairing(null);
    try {
      const q = new URLSearchParams({ user_id: userId });
      const res = await apiClient.post<PairingCodeResponse>(
        `/v1/execution-connector/pairing-codes?${q.toString()}`,
        {}
      );
      setPairing(res);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Request failed';
      setError(msg);
    } finally {
      setBusy(false);
    }
  }, [userId]);

  const revokeDevice = useCallback(async () => {
    const token = revokeToken.trim();
    if (!token) {
      setError('Paste a device token to revoke.');
      return;
    }
    setError(null);
    setBusy(true);
    setRevokeDone(false);
    try {
      await apiClient.post<unknown>('/v1/execution-connector/devices:revoke', { device_token: token });
      setRevokeDone(true);
      setRevokeToken('');
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Request failed';
      setError(msg);
    } finally {
      setBusy(false);
    }
  }, [revokeToken]);

  return (
    <div className="lec-pairing-page">
      <header className="lec-pairing-header">
        <button type="button" className="lec-back-link" onClick={() => navigate('/settings/profile')}>
          ← Back to profile
        </button>
        <h1>Local execution connector</h1>
        <p>
          Pair the optional local daemon with your account. Use the code in{' '}
          <code>amprealize connector pair</code> (or the standalone daemon) before it expires.
        </p>
      </header>

      {error && (
        <div className="lec-error" role="alert">
          {error}
        </div>
      )}

      <section className="lec-card" aria-labelledby="lec-pair-title">
        <h2 id="lec-pair-title">Pairing code</h2>
        <p className="lec-muted">Creates a one-time code bound to your signed-in user.</p>
        <button type="button" className="lec-btn-primary" disabled={busy || !userId} onClick={createCode}>
          {busy ? 'Working…' : 'Generate pairing code'}
        </button>
        {pairing && (
          <div className="lec-pair-result">
            <div className="lec-code">{pairing.code}</div>
            <p className="lec-muted">
              Expires{' '}
              <time dateTime={new Date(pairing.expires_at * 1000).toISOString()}>
                {new Date(pairing.expires_at * 1000).toLocaleString()}
              </time>
            </p>
          </div>
        )}
      </section>

      <section className="lec-card" aria-labelledby="lec-revoke-title">
        <h2 id="lec-revoke-title">Revoke device</h2>
        <p className="lec-muted">Disconnect a daemon by revoking its device token (paste full token).</p>
        <label className="lec-label" htmlFor="lec-revoke-input">
          Device token
        </label>
        <textarea
          id="lec-revoke-input"
          className="lec-textarea"
          rows={3}
          value={revokeToken}
          onChange={(e) => setRevokeToken(e.target.value)}
          placeholder="lec_…"
          autoComplete="off"
        />
        <button type="button" className="lec-btn-secondary" disabled={busy} onClick={revokeDevice}>
          Revoke device
        </button>
        {revokeDone && <p className="lec-success">Device revoked.</p>}
      </section>
    </div>
  );
}
