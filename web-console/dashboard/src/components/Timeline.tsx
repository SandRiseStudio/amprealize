import { FunctionalComponent } from 'preact';
import { TimelineEntry } from '../data';
import './Timeline.css';

interface TimelineProps {
  entries: TimelineEntry[];
}

export const Timeline: FunctionalComponent<TimelineProps> = ({ entries }) => {
  return (
    <ol class="timeline">
      {entries.map((entry) => (
        <li key={`${entry.order}-${entry.artifact}`} class="timeline__entry">
          <div class="timeline__badge">{entry.order}</div>
          <div class="timeline__content">
            <h3>{entry.artifact}</h3>
            <p>{entry.description}</p>
            <span>{entry.date}</span>
          </div>
        </li>
      ))}
    </ol>
  );
};
