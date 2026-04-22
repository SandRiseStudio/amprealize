import { FunctionalComponent } from 'preact';
import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  parseProgressTracker,
  parseBuildTimeline,
  parseAlignmentLog,
  parseConsentSnapshot,
  parseOnboardingSnapshot,
  parseStreamingMetrics,
  ProgressItem,
} from './data';
import ProgressTrackerMarkdown from '#docs/docs/PROGRESS_TRACKER.md?raw';
import BuildTimelineMarkdown from '#docs/BUILD_TIMELINE.md?raw';
import AlignmentLogMarkdown from '#docs/docs/archive/PRD_ALIGNMENT_LOG.md?raw';
import ConsentSnapshotMarkdown from '#docs/docs/analytics/consent_mfa_snapshot.md?raw';
import OnboardingSnapshotMarkdown from '#docs/docs/analytics/onboarding_adoption_snapshot.md?raw';
import { SectionCard } from './components/SectionCard';
import { ProgressOverview } from './components/ProgressOverview';
import { Timeline } from './components/Timeline';
import { AlignmentUpdates } from './components/AlignmentUpdates';
import { ConsentDashboard } from './components/ConsentDashboard';
import { OnboardingDashboard } from './components/OnboardingDashboard';
import { StreamingMetrics } from './components/StreamingMetrics';
import { BehaviorAccuracyDashboard } from './components/BehaviorAccuracyDashboard';
import { emitTelemetry, ensureTelemetrySession } from './telemetry';
import { useConsentTelemetry } from './hooks/useConsentTelemetry';
import { useOnboardingTelemetry } from './hooks/useOnboardingTelemetry';
import { DASHBOARD_SOURCE_REPO_URL, readStoredTheme, writeStoredTheme } from './constants';

const getInitialTheme = (): 'light' | 'dark' => {
  if (typeof window === 'undefined') {
    return 'light';
  }

  const stored = readStoredTheme();
  if (stored === 'dark' || stored === 'light') {
    return stored;
  }

  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

export const App: FunctionalComponent = () => {
  const [theme, setTheme] = useState<'light' | 'dark'>(getInitialTheme);

  useEffect(() => {
    if (typeof document === 'undefined' || typeof window === 'undefined') return;
    document.body.classList.toggle('dark', theme === 'dark');
    writeStoredTheme(theme);
  }, [theme]);

  useEffect(() => {
    ensureTelemetrySession();
  }, []);

  const progressData = useMemo<ReturnType<typeof parseProgressTracker>>(
    () => parseProgressTracker(ProgressTrackerMarkdown),
    []
  );
  const timelineEntries = useMemo<ReturnType<typeof parseBuildTimeline>>(
    () => parseBuildTimeline(BuildTimelineMarkdown),
    []
  );
  const alignmentEntries = useMemo<ReturnType<typeof parseAlignmentLog>>(
    () => parseAlignmentLog(AlignmentLogMarkdown),
    []
  );
  const streamingMetrics = useMemo(() => parseStreamingMetrics(ProgressTrackerMarkdown), []);
  const initialConsentSnapshot = useMemo(() => parseConsentSnapshot(ConsentSnapshotMarkdown), []);
  const initialOnboardingSnapshot = useMemo(() => parseOnboardingSnapshot(OnboardingSnapshotMarkdown), []);
  const { metrics: consentMetrics, updatedAt: consentUpdatedAt } = useConsentTelemetry(initialConsentSnapshot);
  const { metrics: onboardingMetrics, updatedAt: onboardingUpdatedAt } = useOnboardingTelemetry(initialOnboardingSnapshot);

  const consentTotals = useMemo(
    () =>
      consentMetrics.reduce<{
        prompts: number;
        approvals: number;
        denials: number;
        mfaRequired: number;
        mfaCompleted: number;
        weightedLatency: number;
      }>((acc, metric) => {
        acc.prompts += metric.prompts;
        acc.approvals += metric.approvals;
        acc.denials += metric.denials;
        acc.mfaRequired += metric.mfaRequired;
        acc.mfaCompleted += metric.mfaCompleted;
        acc.weightedLatency += metric.averageLatencySeconds * metric.prompts;
        return acc;
      }, {
        prompts: 0,
        approvals: 0,
        denials: 0,
        mfaRequired: 0,
        mfaCompleted: 0,
        weightedLatency: 0,
      }),
    [consentMetrics]
  );

  const consentApprovalRate = consentTotals.prompts === 0
    ? 0
    : (consentTotals.approvals / consentTotals.prompts) * 100;
  const consentMfaCompletion = consentTotals.mfaRequired === 0
    ? 0
    : (consentTotals.mfaCompleted / consentTotals.mfaRequired) * 100;

  type Stat = { label: string; value: string };

  const stats = useMemo<Stat[]>(() => {
    const items: ProgressItem[] = progressData.sections;
    const total = items.length;
    const completed = items.filter((item: ProgressItem) => item.status.includes('✅')).length;
    const inFlight = items.filter((item: ProgressItem) => item.status.includes('⏳')).length;
    const owners = Array.from(new Set(items.map((item: ProgressItem) => item.owner))).filter(Boolean).length;
    const completion = total === 0 ? 0 : Math.round((completed / total) * 100);

    const onboardingSample = onboardingMetrics.reduce((sum, metric) => sum + metric.sampleSize, 0);
    const onboardingAvgTime = onboardingSample === 0
      ? 0
      : onboardingMetrics.reduce(
          (sum, metric) => sum + metric.averageTimeToFirstBehaviorMinutes * metric.sampleSize,
          0
        ) / onboardingSample;
    const onboardingBehaviorReuse = onboardingSample === 0
      ? 0
      : onboardingMetrics.reduce(
          (sum, metric) => sum + metric.behaviorReuseRate * metric.sampleSize,
          0
        ) / onboardingSample;
    const onboardingCompliance = onboardingSample === 0
      ? 0
      : onboardingMetrics.reduce(
          (sum, metric) => sum + metric.complianceCoverage * metric.sampleSize,
          0
        ) / onboardingSample;

    return [
      { label: 'Scope Complete', value: `${completed}/${total}` },
      { label: 'Completion', value: `${completion}%` },
      { label: 'Active Tracks', value: inFlight.toString() },
      { label: 'Contributors', value: owners.toString() },
      { label: 'Sprint 3 Progress', value: streamingMetrics ? `${streamingMetrics.completion}%` : 'N/A' },
      { label: 'Kafka Throughput', value: streamingMetrics ? `${streamingMetrics.kafkaBurstRate.toLocaleString()}/s` : 'N/A' },
      { label: 'Consent Approval', value: `${consentApprovalRate.toFixed(1)}%` },
      { label: 'MFA Completion', value: `${consentMfaCompletion.toFixed(1)}%` },
      { label: 'Avg Time→Behavior', value: `${onboardingAvgTime.toFixed(1)}m` },
      { label: 'Behavior Reuse', value: `${onboardingBehaviorReuse.toFixed(1)}%` },
      { label: 'Compliance Coverage', value: `${onboardingCompliance.toFixed(1)}%` },
    ];
  }, [progressData.sections, streamingMetrics, consentApprovalRate, consentMfaCompletion, onboardingMetrics]);

  const isDark = theme === 'dark';

  useEffect(() => {
    emitTelemetry('dashboard_loaded', {
      last_sync: progressData.lastUpdated,
      total_artifacts: timelineEntries.length,
      consent_surfaces: consentMetrics.length,
      consent_prompts: consentTotals.prompts,
      consent_approval_rate: consentApprovalRate / 100,
      mfa_completion_rate: consentMfaCompletion / 100,
      completion_rate: stats.find((stat) => stat.label === 'Completion')?.value,
      consent_updated_at: consentUpdatedAt,
      onboarding_surfaces: onboardingMetrics.length,
      onboarding_updated_at: onboardingUpdatedAt,
    });
  }, [
    progressData.lastUpdated,
    timelineEntries.length,
    consentMetrics.length,
    consentTotals.prompts,
    consentApprovalRate,
    consentMfaCompletion,
    stats,
    consentUpdatedAt,
    onboardingMetrics.length,
    onboardingUpdatedAt,
  ]);

  const renderStat = (stat: Stat) => (
    <div class="stat-card" key={stat.label}>
      <span class="stat-card__label">{stat.label}</span>
      <span class="stat-card__value">{stat.value}</span>
    </div>
  );

  return (
    <div class="app-shell">
      <header class="hero">
        <div class="hero__text">
          <span class="hero__eyebrow">Amprealize program tracker</span>
          <h1>Milestone Zero Dashboard</h1>
          <p>
            Live status across our documentation, implementation parity, and governance artifacts.
            Everything here updates whenever the repo changes.
          </p>
          <div class="hero__meta">
            <span class="hero__meta-item">
              <strong>Last sync:</strong> {progressData.lastUpdated}
            </span>
            <span class="hero__meta-item">
              <strong>Total artifacts tracked:</strong> {timelineEntries.length}
            </span>
            <span class="hero__meta-item">
              <strong>Consent surfaces:</strong> {consentMetrics.length}
            </span>
            <span class="hero__meta-item">
              <strong>Consent updated:</strong> {consentUpdatedAt}
            </span>
            <span class="hero__meta-item">
              <strong>Onboarding surfaces:</strong> {onboardingMetrics.length}
            </span>
            <span class="hero__meta-item">
              <strong>Onboarding updated:</strong> {onboardingUpdatedAt}
            </span>
          </div>
        </div>
        <div class="hero__actions">
          <button
            class="theme-toggle"
            type="button"
            onClick={() => {
              const nextTheme = isDark ? 'light' : 'dark';
              setTheme(nextTheme);
              emitTelemetry('dashboard_theme_toggled', { theme: nextTheme });
            }}
            aria-label="Toggle dark mode"
          >
            {isDark ? '☀️ Light Mode' : '🌙 Dark Mode'}
          </button>
          <a
            class="hero__cta"
            href={DASHBOARD_SOURCE_REPO_URL}
            target="_blank"
            rel="noreferrer"
            onClick={() => emitTelemetry('dashboard_cta_clicked', { target: 'github' })}
          >
            View source
          </a>
        </div>
      </header>

      <section class="stats-grid">{stats.map(renderStat)}</section>

      {streamingMetrics && <StreamingMetrics metrics={streamingMetrics} />}

      <main class="layout-grid">
        <SectionCard
          title="Milestone Progress"
          subtitle="Pulled directly from PROGRESS_TRACKER.md via amprealize record-action"
        >
          <ProgressOverview items={progressData.sections} />
        </SectionCard>

        <SectionCard
          title="Build Timeline"
          subtitle="Sequence of shipped artifacts from BUILD_TIMELINE.md"
        >
          <Timeline entries={timelineEntries} />
        </SectionCard>

        <SectionCard
          title="Alignment Updates"
          subtitle="Latest highlights from PRD_ALIGNMENT_LOG.md"
        >
          <AlignmentUpdates entries={alignmentEntries} />
        </SectionCard>

        <SectionCard
          title="Consent & MFA Dashboard"
          subtitle="Telemetry-backed metrics seeded from docs/analytics/consent_mfa_snapshot.md"
        >
          <ConsentDashboard metrics={consentMetrics} updatedAt={consentUpdatedAt} />
        </SectionCard>

        <SectionCard
          title="Onboarding & Adoption"
          subtitle="Telemetry-backed metrics seeded from docs/analytics/onboarding_adoption_snapshot.md"
        >
          <OnboardingDashboard metrics={onboardingMetrics} updatedAt={onboardingUpdatedAt} />
        </SectionCard>

        <SectionCard
          title="Behavior Accuracy & Effectiveness"
          subtitle="Track behavior retrieval accuracy, token reduction, and curator feedback"
        >
          <BehaviorAccuracyDashboard />
        </SectionCard>
      </main>
    </div>
  );
};
