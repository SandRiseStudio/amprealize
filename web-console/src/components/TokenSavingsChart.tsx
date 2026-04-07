/**
 * TokenSavingsChart - Visualizes token savings from BCI
 */

import './TokenSavingsChart.css';

interface TokenSavingsChartProps {
  originalTokens: number;
  optimizedTokens: number;
  savingsPercentage: number;
  targetPercentage?: number; // PRD target is 30%
}

export function TokenSavingsChart({
  originalTokens,
  optimizedTokens,
  savingsPercentage,
  targetPercentage = 30,
}: TokenSavingsChartProps) {
  const savingsTokens = originalTokens - optimizedTokens;
  const meetsTarget = savingsPercentage >= targetPercentage;

  // Calculate bar widths
  const originalWidth = 100;
  const optimizedWidth = Math.max(5, (optimizedTokens / originalTokens) * 100);

  return (
    <div className="token-savings-chart">
      <div className="chart-header">
        <h3>Token Savings</h3>
        <span className={`savings-badge ${meetsTarget ? 'meets-target' : ''}`}>
          {savingsPercentage.toFixed(1)}% saved
          {meetsTarget && <span className="target-met">✓ Meets {targetPercentage}% target</span>}
        </span>
      </div>

      <div className="chart-bars">
        <div className="bar-row">
          <span className="bar-label">Original</span>
          <div className="bar-container">
            <div
              className="bar bar-original"
              style={{ width: `${originalWidth}%` }}
            >
              <span className="bar-value">{originalTokens.toLocaleString()}</span>
            </div>
          </div>
        </div>

        <div className="bar-row">
          <span className="bar-label">Optimized</span>
          <div className="bar-container">
            <div
              className="bar bar-optimized"
              style={{ width: `${optimizedWidth}%` }}
            >
              <span className="bar-value">{optimizedTokens.toLocaleString()}</span>
            </div>
            <div
              className="bar bar-savings"
              style={{ width: `${originalWidth - optimizedWidth}%` }}
            >
              <span className="bar-value">-{savingsTokens.toLocaleString()}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="chart-stats">
        <div className="stat">
          <span className="stat-value">{savingsTokens.toLocaleString()}</span>
          <span className="stat-label">Tokens Saved</span>
        </div>
        <div className="stat">
          <span className="stat-value">{savingsPercentage.toFixed(1)}%</span>
          <span className="stat-label">Reduction</span>
        </div>
        <div className="stat">
          <span className="stat-value">${((savingsTokens / 1000) * 0.002).toFixed(4)}</span>
          <span className="stat-label">Est. Cost Saved</span>
        </div>
      </div>
    </div>
  );
}

export default TokenSavingsChart;
