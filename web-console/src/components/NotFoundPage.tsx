import { useNavigate } from 'react-router-dom';
import './NotFoundPage.css';

export function NotFoundPage(): React.JSX.Element {
  const navigate = useNavigate();

  return (
    <div className="not-found">
      <div className="not-found-card animate-fade-in-up">
        <h1 className="not-found-title">Page not found</h1>
        <p className="not-found-description">
          No routes matched this location. Return to the dashboard to continue.
        </p>
        <div className="not-found-actions">
          <button
            type="button"
            className="not-found-button primary pressable"
            onClick={() => navigate('/')}
            data-haptic="light"
          >
            Go to Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
