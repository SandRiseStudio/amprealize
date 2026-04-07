import type { ReactNode } from 'react';
import {
  Bot,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { PRODUCT_DISPLAY_NAME } from '../../config/branding';
import './AuthStage.css';

interface AuthStageProps {
  panelEyebrow: string;
  panelTitle: string;
  panelSubtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}

const supportingNotes = [
  {
    icon: Sparkles,
    title: 'Fast handoff',
    description: 'Sign in without losing momentum.',
  },
  {
    icon: Bot,
    title: 'Human-first',
    description: 'Agents stay available, never overwhelming.',
  },
  {
    icon: ShieldCheck,
    title: 'Clear recovery',
    description: 'Errors stay understandable and actionable.',
  },
] as const;

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
              <Sparkles size={18} strokeWidth={2} />
            </div>
            <div className="auth-stage-brand-copy">
              <span className="auth-stage-brand-name">{PRODUCT_DISPLAY_NAME}</span>
              <span className="auth-stage-brand-meta">Web Console</span>
            </div>
          </div>
          <p className="auth-stage-tagline">Projects, boards, runs, and agents in one fast place.</p>
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

        <div className="auth-stage-support" aria-label={`${PRODUCT_DISPLAY_NAME} sign-in principles`}>
          {supportingNotes.map(({ icon: Icon, title, description }) => (
            <div key={title} className="auth-stage-support-item">
              <div className="auth-stage-support-icon" aria-hidden="true">
                <Icon size={16} strokeWidth={2} />
              </div>
              <div className="auth-stage-support-copy">
                <span>{title}</span>
                <small>{description}</small>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default AuthStage;
