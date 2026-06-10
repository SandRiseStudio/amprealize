import React, { useEffect, useMemo, useState } from 'react';

export interface LiveActivityStripProps {
  phaseLabel: string;
  stepLabel: string;
  elapsedMs: number;
  isRunning: boolean;
  /** When set and the run is active, elapsed time ticks from wall clock (fixes stale props between polls). */
  startedAtIso?: string | null;
}

function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

/**
 * Sticky one-liner with polite live region updates while running.
 * Following behavior_validate_accessibility (Student).
 */
export function LiveActivityStrip({
  phaseLabel,
  stepLabel,
  elapsedMs,
  isRunning,
  startedAtIso,
}: LiveActivityStripProps): React.JSX.Element {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!isRunning) {
      return undefined;
    }
    const id = window.setInterval(() => {
      setTick((n) => n + 1);
    }, 1000);
    return () => window.clearInterval(id);
  }, [isRunning]);

  const effectiveElapsed = useMemo(() => {
    if (isRunning && startedAtIso) {
      const t = Date.parse(startedAtIso);
      if (Number.isFinite(t)) {
        return Math.max(0, Date.now() - t);
      }
    }
    return elapsedMs;
  }, [elapsedMs, isRunning, startedAtIso, tick]);

  const text = useMemo(
    () => `${phaseLabel}: ${stepLabel} · ${formatElapsed(effectiveElapsed)}`,
    [effectiveElapsed, phaseLabel, stepLabel],
  );

  return (
    <div className="execution-live-strip" aria-live="polite" aria-atomic="true">
      <span className="execution-live-strip-visual" aria-hidden="true">
        {isRunning ? <span className="execution-live-spinner" /> : null}
      </span>
      <span className="execution-live-strip-text">{text}</span>
    </div>
  );
}
