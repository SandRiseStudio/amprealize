import { FunctionalComponent } from 'preact';
import { ProgressItem } from '../data';
import './ProgressOverview.css';

interface ProgressOverviewProps {
  items: ProgressItem[];
}

const statusWeight = (status: string) => {
  if (status.includes('✅')) return 3;
  if (status.includes('⏳')) return 2;
  return 1;
};

export const ProgressOverview: FunctionalComponent<ProgressOverviewProps> = ({ items }) => {
  const milestoneMap = new Map<string, ProgressItem[]>();

  for (const item of items) {
    if (!milestoneMap.has(item.section)) {
      milestoneMap.set(item.section, []);
    }
    milestoneMap.get(item.section)!.push(item);
  }

  const milestones = Array.from(milestoneMap.entries());

  return (
    <div class="progress-overview">
      {milestones.map(([section, sectionItems]) => (
        <article class="progress-panel" key={section}>
          <header>
            <h3>{section}</h3>
            <span class="progress-panel__status">
              {sectionItems.filter((item) => item.status.includes('✅')).length}/
              {sectionItems.length}
            </span>
          </header>
          <ul>
            {sectionItems
              .slice()
              .sort((a, b) => statusWeight(b.status) - statusWeight(a.status))
              .map((item) => (
                <li key={item.workItem}>
                  <div class="progress-item__title">{item.workItem}</div>
                  <div class="progress-item__meta">
                    <span>{item.owner}</span>
                    <span class={item.status.includes('✅') ? 'status-done' : 'status-pending'}>
                      {item.status}
                    </span>
                  </div>
                  <div class="progress-item__evidence">{item.evidence}</div>
                </li>
              ))}
          </ul>
        </article>
      ))}
    </div>
  );
};
