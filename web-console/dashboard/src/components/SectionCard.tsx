import { FunctionalComponent, ComponentChildren } from 'preact';
import { JSX } from 'preact/jsx-runtime';
import './SectionCard.css';

interface SectionCardProps {
  title: string;
  subtitle?: string;
  action?: JSX.Element;
  children: ComponentChildren;
}

export const SectionCard: FunctionalComponent<SectionCardProps> = ({
  title,
  subtitle,
  action,
  children,
}) => {
  return (
    <section class="section-card">
      <header class="section-card__header">
        <div>
          <h2>{title}</h2>
          {subtitle && <p class="section-card__subtitle">{subtitle}</p>}
        </div>
        {action && <div class="section-card__action">{action}</div>}
      </header>
      <div class="section-card__body">{children}</div>
    </section>
  );
};
