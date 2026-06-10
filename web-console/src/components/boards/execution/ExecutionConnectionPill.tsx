import React from 'react';
import { ConnectionState } from '../../../lib/collab-client';

export interface ExecutionConnectionPillProps {
  connectionState: ConnectionState;
  isConnected: boolean;
  /** When true, REST is polling execution status (e.g. every 2s) */
  isPolling: boolean;
}

/**
 * Honest connection indicator: WebSocket live vs HTTP polling vs disconnected.
 * Following behavior_validate_accessibility (Student): concise labels + focus styles via CSS.
 */
export function ExecutionConnectionPill({
  connectionState,
  isConnected,
  isPolling,
}: ExecutionConnectionPillProps): React.JSX.Element {
  let label = 'Disconnected';
  let tone: 'live' | 'poll' | 'off' = 'off';

  if (isConnected) {
    label = 'Live';
    tone = 'live';
  } else if (isPolling) {
    label = 'Polling 2s';
    tone = 'poll';
  } else if (connectionState === ConnectionState.Connecting || connectionState === ConnectionState.Reconnecting) {
    label = 'Connecting…';
    tone = 'poll';
  }

  return (
    <span
      className={`execution-connection-pill execution-connection-pill--${tone}`}
      title="Execution updates: WebSocket when live, otherwise REST polling while active."
    >
      <span className="execution-connection-pill-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
