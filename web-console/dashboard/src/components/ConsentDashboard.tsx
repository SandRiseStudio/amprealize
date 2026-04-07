import { FunctionalComponent } from 'preact';
import { ConsentMetric } from '../data';
import './ConsentDashboard.css';

interface ConsentDashboardProps {
  metrics: ConsentMetric[];
  updatedAt: string;
}

interface Aggregates {
  prompts: number;
  approvals: number;
  denials: number;
  snoozes: number;
  mfaRequired: number;
  mfaCompleted: number;
  weightedAvgLatency: number;
  maxP95Latency: number;
}

const computeAggregates = (metrics: ConsentMetric[]): Aggregates => {
  return metrics.reduce<Aggregates>(
    (acc, metric) => {
      acc.prompts += metric.prompts;
      acc.approvals += metric.approvals;
      acc.denials += metric.denials;
      acc.snoozes += metric.snoozes;
      acc.mfaRequired += metric.mfaRequired;
      acc.mfaCompleted += metric.mfaCompleted;
      acc.weightedAvgLatency += metric.averageLatencySeconds * metric.prompts;
      acc.maxP95Latency = Math.max(acc.maxP95Latency, metric.p95LatencySeconds);
      return acc;
    },
    {
      prompts: 0,
      approvals: 0,
      denials: 0,
      snoozes: 0,
      mfaRequired: 0,
      mfaCompleted: 0,
      weightedAvgLatency: 0,
      maxP95Latency: 0,
    }
  );
};

const formatPercent = (value: number): string => `${value.toFixed(1)}%`;

export const ConsentDashboard: FunctionalComponent<ConsentDashboardProps> = ({ metrics, updatedAt }) => {
  const aggregates = computeAggregates(metrics);
  const approvalRate = aggregates.prompts === 0 ? 0 : (aggregates.approvals / aggregates.prompts) * 100;
  const denialRate = aggregates.prompts === 0 ? 0 : (aggregates.denials / aggregates.prompts) * 100;
  const mfaCompletionRate = aggregates.mfaRequired === 0 ? 0 : (aggregates.mfaCompleted / aggregates.mfaRequired) * 100;
  const avgLatency = aggregates.prompts === 0 ? 0 : aggregates.weightedAvgLatency / aggregates.prompts;

  return (
    <div class="consent-dashboard">
      <div class="consent-dashboard__stats">
        <div class="stat-card">
          <span class="stat-card__label">Total Prompts</span>
          <span class="stat-card__value">{aggregates.prompts}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Approval Rate</span>
          <span class="stat-card__value">{formatPercent(approvalRate)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Denial Rate</span>
          <span class="stat-card__value">{formatPercent(denialRate)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">MFA Completion</span>
          <span class="stat-card__value">{formatPercent(mfaCompletionRate)}</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">Avg Latency</span>
          <span class="stat-card__value">{avgLatency.toFixed(1)}s</span>
        </div>
        <div class="stat-card">
          <span class="stat-card__label">p95 Latency</span>
          <span class="stat-card__value">{aggregates.maxP95Latency.toFixed(1)}s</span>
        </div>
      </div>

      <div class="consent-dashboard__table-wrapper">
        <table class="consent-dashboard__table">
          <thead>
            <tr>
              <th scope="col">Surface</th>
              <th scope="col">Prompts</th>
              <th scope="col">Approvals</th>
              <th scope="col">Denials</th>
              <th scope="col">Snoozes</th>
              <th scope="col">MFA Required</th>
              <th scope="col">MFA Completed</th>
              <th scope="col">Avg Latency (s)</th>
              <th scope="col">p95 Latency (s)</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.surface}>
                <th scope="row">{metric.surface}</th>
                <td>{metric.prompts}</td>
                <td>{metric.approvals}</td>
                <td>{metric.denials}</td>
                <td>{metric.snoozes}</td>
                <td>{metric.mfaRequired}</td>
                <td>{metric.mfaCompleted}</td>
                <td>{metric.averageLatencySeconds.toFixed(1)}</td>
                <td>{metric.p95LatencySeconds.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer class="consent-dashboard__footer">
        <span>Updated {updatedAt}</span>
      </footer>
    </div>
  );
};
