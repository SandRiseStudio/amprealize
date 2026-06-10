/**
 * Agent workspace & local connector preferences (pairing link + local_workspace toggle).
 */

import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient, ApiError } from '../../api/client';
import { useAuth } from '../../auth';
import {
  readUseLocalWorkspaceExecution,
  setUseLocalWorkspaceExecution,
} from '../../utils/executionWorkspacePreference';
import '../SecuritySettings.css';
import './LocalExecutionWorkspaceSettings.css';

interface ConnectorConnectionStatusResponse {
  connected: boolean;
  depth?: string;
  tool_invoke_ok?: boolean | null;
  tool_invoke_error?: string | null;
}

export function LocalExecutionWorkspaceSettings() {
  const navigate = useNavigate();
  const { actor } = useAuth();
  const userId = actor?.id;

  const [useLocalWorkspaceExecution, setUseLocalWorkspaceExecutionPref] = useState(
    () => readUseLocalWorkspaceExecution(),
  );
  const [socketBusy, setSocketBusy] = useState(false);
  const [socketError, setSocketError] = useState<string | null>(null);
  const [socketConnected, setSocketConnected] = useState<boolean | null>(null);

  const [probeBusy, setProbeBusy] = useState(false);
  const [probeHttpError, setProbeHttpError] = useState<string | null>(null);
  const [probeConnected, setProbeConnected] = useState<boolean | null>(null);
  const [probeToolOk, setProbeToolOk] = useState<boolean | null>(null);
  const [probeToolError, setProbeToolError] = useState<string | null>(null);

  const handleToggleLocalWorkspaceExecution = useCallback(() => {
    if (!useLocalWorkspaceExecution) {
      const ok = window.confirm(
        'Work item and chat runs will send execution_workspace_kind=local_connector: file and shell tools run on this machine through the paired connector daemon. Enable only if you trust this device and have completed pairing.',
      );
      if (!ok) {
        return;
      }
    }
    const next = !useLocalWorkspaceExecution;
    setUseLocalWorkspaceExecution(next);
    setUseLocalWorkspaceExecutionPref(next);
  }, [useLocalWorkspaceExecution]);

  const checkSocketOnly = useCallback(async () => {
    if (!userId) {
      setSocketError('Sign in to check connector status.');
      setSocketConnected(null);
      return;
    }
    setSocketError(null);
    setSocketConnected(null);
    setSocketBusy(true);
    try {
      const q = new URLSearchParams({ user_id: userId, depth: 'socket' });
      const res = await apiClient.get<ConnectorConnectionStatusResponse>(
        `/v1/execution-connector/connection-status?${q.toString()}`,
      );
      setSocketConnected(res.connected);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Request failed';
      setSocketError(msg);
      setSocketConnected(null);
    } finally {
      setSocketBusy(false);
    }
  }, [userId]);

  const checkToolProbe = useCallback(async () => {
    if (!userId) {
      setProbeHttpError('Sign in to check connector status.');
      setProbeConnected(null);
      setProbeToolOk(null);
      setProbeToolError(null);
      return;
    }
    setProbeHttpError(null);
    setProbeConnected(null);
    setProbeToolOk(null);
    setProbeToolError(null);
    setProbeBusy(true);
    try {
      const q = new URLSearchParams({ user_id: userId, depth: 'invoke' });
      const res = await apiClient.get<ConnectorConnectionStatusResponse>(
        `/v1/execution-connector/connection-status?${q.toString()}`,
      );
      setProbeConnected(res.connected);
      if (res.tool_invoke_ok !== undefined && res.tool_invoke_ok !== null) {
        setProbeToolOk(res.tool_invoke_ok);
      }
      setProbeToolError(res.tool_invoke_error ?? null);
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Request failed';
      setProbeHttpError(msg);
    } finally {
      setProbeBusy(false);
    }
  }, [userId]);

  return (
    <section
      className="settings-section lec-workspace-settings"
      aria-labelledby="lec-workspace-heading"
    >
      <h2 id="lec-workspace-heading">Agent workspace &amp; local execution</h2>
      <div className="lec-workspace-intro">
        <p>
          <strong>Remote workspace</strong> (default) runs agents against an isolated repository clone in the cloud (
          <code>cloud_git</code>) — not files on this laptop.
        </p>
        <p>
          <strong>Local workspace</strong> (<code>local_connector</code>) keeps reasoning on Amprealize but runs file
          and shell tools on <strong>this machine</strong> through the paired connector daemon.
        </p>
      </div>
      <p className="section-description">
        Pairing codes and device revoke use the same API as the CLI. Requires the server feature flag, a running daemon,
        and API <strong>background</strong> dispatch (hybrid runs do not use the Redis worker path).
      </p>
      <button
        type="button"
        className="btn-primary"
        onClick={() => navigate('/settings/local-connector')}
        data-haptic="light"
      >
        Manage pairing
      </button>
      <div className="lec-connect-verify">
        <p className="lec-connect-verify-intro">
          Confirm connectivity before enabling local workspace runs. Use <strong>Quick check</strong> for WebSocket
          registration only, or <strong>Verify tool delegation</strong> for a full <code>list_dir</code> probe over the
          same path hybrid agents use (may take up to ~15s).
        </p>
        <div className="lec-connect-verify-actions">
          <button
            type="button"
            className="btn-secondary"
            onClick={checkSocketOnly}
            disabled={socketBusy || !userId}
            data-haptic="light"
          >
            {socketBusy ? 'Checking…' : 'Quick check (socket)'}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={checkToolProbe}
            disabled={probeBusy || !userId}
            data-haptic="light"
          >
            {probeBusy ? 'Probing…' : 'Verify tool delegation'}
          </button>
        </div>
        {!userId && (
          <p className="lec-connect-verify-hint" role="status">
            Sign in to run these checks.
          </p>
        )}
        {socketError && (
          <div className="lec-connect-status lec-connect-status--error" role="alert">
            {socketError}
          </div>
        )}
        {socketConnected === true && (
          <div className="lec-connect-status lec-connect-status--ok" role="status">
            Quick check: this server has an active connector WebSocket for your account.
          </div>
        )}
        {socketConnected === false && (
          <div className="lec-connect-status lec-connect-status--warn" role="status">
            Quick check: no connector WebSocket — start your paired daemon (for example{' '}
            <code>amprealize connector listen</code>). Multiple API instances each keep separate connector state.
          </div>
        )}
        {probeHttpError && (
          <div className="lec-connect-status lec-connect-status--error" role="alert">
            Tool delegation check failed: {probeHttpError}
          </div>
        )}
        {probeConnected !== null && probeToolOk === true && (
          <div className="lec-connect-status lec-connect-status--ok" role="status">
            Tool delegation: <code>list_dir</code> probe succeeded on your connector workdir.
          </div>
        )}
        {probeConnected !== null && probeToolOk === false && (
          <div className="lec-connect-status lec-connect-status--warn" role="status">
            <strong>Tool delegation:</strong>{' '}
            {probeConnected ? (
              <>
                probe did not succeed
                {probeToolError ? (
                  <>
                    {' '}
                    (<code>{probeToolError}</code>)
                  </>
                ) : null}
                . Ensure the daemon is running and its workdir allows listing <code>.</code>
              </>
            ) : (
              <>
                no connector WebSocket on this API instance
                {probeToolError ? (
                  <>
                    {' '}
                    (<code>{probeToolError}</code>)
                  </>
                ) : null}
                . Run <strong>Quick check</strong> or start <code>amprealize connector listen</code>.
              </>
            )}
          </div>
        )}
      </div>
      <div className="local-workspace-opt-in">
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={useLocalWorkspaceExecution}
            onChange={handleToggleLocalWorkspaceExecution}
            aria-describedby="local-workspace-opt-in-desc"
          />
          <span id="local-workspace-opt-in-desc">
            Use <strong>local workspace</strong> for work item and chat agent runs (sends{' '}
            <code>execution_workspace_kind=local_connector</code> from this browser).
          </span>
        </label>
      </div>
    </section>
  );
}
