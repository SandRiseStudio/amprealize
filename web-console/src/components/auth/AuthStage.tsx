import type { ReactNode } from 'react';
import { BrandLogo } from '../branding/BrandLogo';
import { PRODUCT_DISPLAY_NAME } from '../../config/branding';
import './AuthStage.css';

interface AuthStageProps {
  panelEyebrow: string;
  panelTitle: string;
  panelSubtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function AuthStage({
  panelEyebrow,
  panelTitle,
  panelSubtitle,
  children,
  footer,
}: AuthStageProps): React.JSX.Element {
  return (
    <div className="auth-stage-page">
      <div className="auth-stage-shell animate-scale-in">
        <div className="auth-stage-ambient" aria-hidden="true">
          <span className="auth-stage-orbit auth-stage-orbit-a" />
          <span className="auth-stage-orbit auth-stage-orbit-b" />
          <span className="auth-stage-node auth-stage-node-a" />
          <span className="auth-stage-node auth-stage-node-b" />
          <span className="auth-stage-node auth-stage-node-c" />
          <span className="auth-stage-line auth-stage-line-a" />
          <span className="auth-stage-line auth-stage-line-b" />
        </div>

        <header className="auth-stage-header">
          <div className="auth-stage-brand">
            <div className="auth-stage-brand-mark" aria-hidden="true">
              <BrandLogo variant="icon" decorative className="auth-stage-brand-icon" />
            </div>
            <div className="auth-stage-brand-copy">
              <BrandLogo variant="wordmark" alt={PRODUCT_DISPLAY_NAME} className="auth-stage-brand-wordmark" />
              <span className="auth-stage-brand-meta">Behavior engine</span>
            </div>
          </div>
          <p className="auth-stage-tagline">Reusable behaviors for agents, tools, and workflows.</p>
        </header>

        <section className="auth-stage-panel" aria-label={panelTitle}>
          <div className="auth-stage-panel-inner">
            <header className="auth-stage-panel-header">
              <span className="auth-stage-panel-eyebrow">{panelEyebrow}</span>
              <h1 className="auth-stage-panel-title">{panelTitle}</h1>
              <p className="auth-stage-panel-subtitle">{panelSubtitle}</p>
            </header>

            <div className="auth-stage-panel-body">{children}</div>
            {footer}
          </div>
        </section>
      </div>
    </div>
  );
}

export default AuthStage;
