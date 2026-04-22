/**
 * Admin UI for server-side boolean feature flags (Postgres-backed).
 *
 * API: GET/PUT /api/v1/platform/feature-flags — requires ADMIN JWT or
 * X-Amprealize-Feature-Flags-Admin when AMPREALIZE_FEATURE_FLAGS_ADMIN_SECRET is set on the API.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { apiClient, ApiError } from '../api/client';
import './FeatureFlagsPage.css';

interface PlatformFlagRow {
  name: string;
  flag_type: string;
  description: string;
  effective_enabled: boolean;
  registry_enabled: boolean;
  source: string;
  percentage?: number;
}

interface FeatureFlagsResponse {
  database_configured: boolean;
  flags: PlatformFlagRow[];
}

export function FeatureFlagsPage() {
  const navigate = useNavigate();
  const { actor, getValidAccessToken } = useAuth();
  const [data, setData] = useState<FeatureFlagsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const json = await apiClient.get<FeatureFlagsResponse>('/v1/platform/feature-flags');
      setData(json);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Failed to load';
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = useCallback(
    async (flag: PlatformFlagRow, next: boolean) => {
      if (flag.flag_type !== 'boolean') return;
      setPending(flag.name);
      setError(null);
      try {
        await getValidAccessToken();
        await apiClient.put(`/v1/platform/feature-flags/${encodeURIComponent(flag.name)}`, {
          enabled: next,
        });
        await load();
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Update failed';
        setError(msg);
      } finally {
        setPending(null);
      }
    },
    [getValidAccessToken, load],
  );

  if (actor?.role !== 'ADMIN') {
    return (
      <div className="feature-flags-page">
        <header className="feature-flags-header">
          <h1>Feature flags</h1>
        </header>
        <p className="feature-flags-denied">You need an administrator account to manage feature flags.</p>
        <button type="button" className="feature-flags-back pressable" onClick={() => navigate('/settings')}>
          Back to settings
        </button>
      </div>
    );
  }

  return (
    <div className="feature-flags-page">
      <header className="feature-flags-header">
        <h1>Feature flags</h1>
        <p className="feature-flags-lede">
          Toggle boolean flags stored in Postgres (global scope). Percentage and allow-list flags are shown
          read-only; change those via environment or ops tooling.
        </p>
        <button type="button" className="feature-flags-back pressable" onClick={() => navigate('/settings')}>
          Back to settings
        </button>
      </header>

      {loading && <div className="feature-flags-status">Loading…</div>}
      {error && (
        <div className="feature-flags-error" role="alert">
          {error}
        </div>
      )}

      {data && (
        <>
          <p className="feature-flags-meta" role="status">
            Database persistence: {data.database_configured ? 'configured' : 'not configured (toggles will fail)'}
          </p>
          <div className="feature-flags-table-wrap">
            <table className="feature-flags-table">
              <thead>
                <tr>
                  <th scope="col">Flag</th>
                  <th scope="col">Type</th>
                  <th scope="col">On</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {data.flags.map((f) => (
                  <tr key={f.name}>
                    <td>
                      <div className="feature-flags-name">{f.name}</div>
                      {f.description ? <div className="feature-flags-desc">{f.description}</div> : null}
                    </td>
                    <td>{f.flag_type}</td>
                    <td>
                      {f.flag_type === 'boolean' ? (
                        <label className="feature-flags-toggle">
                          <input
                            type="checkbox"
                            checked={f.effective_enabled}
                            disabled={pending === f.name || !data.database_configured}
                            onChange={(ev) => void toggle(f, ev.target.checked)}
                            aria-label={`${f.name} enabled`}
                          />
                        </label>
                      ) : (
                        <span className="feature-flags-readonly">{f.effective_enabled ? 'yes' : 'no'}</span>
                      )}
                    </td>
                    <td>{f.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default FeatureFlagsPage;
