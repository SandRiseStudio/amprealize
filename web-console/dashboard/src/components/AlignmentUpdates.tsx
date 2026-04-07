import { FunctionalComponent } from 'preact';
import { AlignmentEntry } from '../data';
import './AlignmentUpdates.css';

interface AlignmentUpdatesProps {
  entries: AlignmentEntry[];
}

export const AlignmentUpdates: FunctionalComponent<AlignmentUpdatesProps> = ({ entries }) => {
  return (
    <ul class="alignment-updates">
      {entries.map((entry, index) => (
        <li key={`${index}-${entry.text}`}>{entry.text}</li>
      ))}
    </ul>
  );
};
