import { FunctionalComponent } from 'preact';
import { OnboardingMetric } from '../data';
import './OnboardingDashboard.css';

interface OnboardingDashboardProps {
  metrics: OnboardingMetric[];
  updatedAt: string;
}

interface Aggregates {
  sampleSize: number;
  totalTime: number;
  checklistCompleted: number;
  behaviorSearchEvents: number;
  behaviorInsertions: number;
  behaviorReuseHits: number;
  tokenSavingsTotal: number;
  taskCompleted: number;
  complianceLogged: number;
}

const computeAggregates = (metrics: OnboardingMetric[]): Aggregates => {
  return metrics.reduce<Aggregates>(
    (acc, metric) => {
      acc.sampleSize += metric.sampleSize;
      acc.totalTime += metric.averageTimeToFirstBehaviorMinutes * metric.sampleSize;
      acc.checklistCompleted += (metric.checklistCompletionRate / 100) * metric.sampleSize;
      acc.behaviorSearchEvents += metric.sampleSize;
      acc.behaviorInsertions += (metric.behaviorSearchToInsertRate / 100) * metric.sampleSize;
      acc.behaviorReuseHits += (metric.behaviorReuseRate / 100) * metric.sampleSize;
      acc.tokenSavingsTotal += metric.tokenSavingsAverage * metric.sampleSize;
      acc.taskCompleted += (metric.taskCompletionRate / 100) * metric.sampleSize;
      acc.complianceLogged += (metric.complianceCoverage / 100) * metric.sampleSize;
      return acc;
    },
    {
      sampleSize: 0,
      totalTime: 0,
      checklistCompleted: 0,
      behaviorSearchEvents: 0,
      behaviorInsertions: 0,
      behaviorReuseHits: 0,
      tokenSavingsTotal: 0,
      taskCompleted: 0,
      complianceLogged: 0,
    }
  );
};

const formatPercent = (value: number): string => `${value.toFixed(1)}%`;

export const OnboardingDashboard: FunctionalComponent<OnboardingDashboardProps> = ({ metrics, updatedAt }) => {
  const aggregates = computeAggregates(metrics);
  const sampleSize = aggregates.sampleSize || 0;
  const avgTime = sampleSize === 0 ? 0 : aggregates.totalTime / sampleSize;
  const checklistCompletion = sampleSize === 0 ? 0 : (aggregates.checklistCompleted / sampleSize) * 100;
  const behaviorSearchInsert =
    aggregates.behaviorSearchEvents === 0
      ? 0
      : (aggregates.behaviorInsertions / aggregates.behaviorSearchEvents) * 100;
  const behaviorReuse = sampleSize === 0 ? 0 : (aggregates.behaviorReuseHits / sampleSize) * 100;
  const tokenSavings = sampleSize === 0 ? 0 : aggregates.tokenSavingsTotal / sampleSize;
  const taskCompletion = sampleSize === 0 ? 0 : (aggregates.taskCompleted / sampleSize) * 100;
  const complianceCoverage = sampleSize === 0 ? 0 : (aggregates.complianceLogged / sampleSize) * 100;

  return (
    <div class="onboarding-dashboard">
      <div class="onboarding-dashboard__stats">
        <div class="stat-card">
          <span class="stat-card__label">Avg Time to First Behavior</span>
          <span class="stat-card__value">{avgTime.toFixed(1)} min</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Checklist Completion</span>
          <span class="stat-card__value">{formatPercent(checklistCompletion)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Behavior Search→Insert</span>
          <span class="stat-card__value">{formatPercent(behaviorSearchInsert)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Behavior Reuse</span>
          <span class="stat-card__value">{formatPercent(behaviorReuse)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Token Savings</span>
          <span class="stat-card__value">{formatPercent(tokenSavings)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Task Completion</span>
          <span class="stat-card__value">{formatPercent(taskCompletion)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Compliance Coverage</span>
          <span class="stat-card__value">{formatPercent(complianceCoverage)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Sample Size</span>
          <span class="stat-card__value">{sampleSize}</span>
        </div>
      </div>

      <div class="onboarding-dashboard__table-wrapper">
        <table class="onboarding-dashboard__table">
          <thead>
            <tr>
              <th scope="col">Surface</th>
              <th scope="col">Sample Size</th>
              <th scope="col">Avg Time to First Behavior (min)</th>
              <th scope="col">Checklist Completion %</th>
              <th scope="col">Behavior Search→Insert %</th>
              <th scope="col">Behavior Reuse %</th>
              <th scope="col">Token Savings %</th>
              <th scope="col">Task Completion %</th>
              <th scope="col">Compliance Coverage %</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.surface}>
                <th scope="row">{metric.surface}</th>
                <td>{metric.sampleSize}</td>
                <td>{metric.averageTimeToFirstBehaviorMinutes.toFixed(1)}</td>
                <td>{metric.checklistCompletionRate.toFixed(1)}</td>
                <td>{metric.behaviorSearchToInsertRate.toFixed(1)}</td>
                <td>{metric.behaviorReuseRate.toFixed(1)}</td>
                <td>{metric.tokenSavingsAverage.toFixed(1)}</td>
                <td>{metric.taskCompletionRate.toFixed(1)}</td>
                <td>{metric.complianceCoverage.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer class="onboarding-dashboard__footer">
        <span>Updated {updatedAt}</span>
      </footer>
    </div>
  );
};
