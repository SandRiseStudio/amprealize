/**
 * Organization Switcher (shared)
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import type { Organization } from '../api/dashboard';
import { PERSONAL_SCOPE_LABEL, resolveScopeLabel } from '../copy/scopeLabels';
import './OrgSwitcher.css';

interface OrgSwitcherProps {
  organizations: Organization[];
  currentOrgId: string | null;
  onSelect: (orgId: string | null) => void;
}

const ChevronDownIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path
      d="M3 4.5L6 7.5L9 4.5"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const OrgSwitcher = memo(function OrgSwitcher({
  organizations,
  currentOrgId,
  onSelect,
}: OrgSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const currentOrg = organizations.find((o) => o.id === currentOrgId);
  const currentLabel = resolveScopeLabel(currentOrg?.name);

  const focusMenuItem = useCallback((target: 'first' | 'last' | number) => {
    const items = wrapperRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    if (!items?.length) return;

    if (target === 'first') {
      items[0]?.focus();
      return;
    }

    if (target === 'last') {
      items[items.length - 1]?.focus();
      return;
    }

    items[target]?.focus();
  }, []);

  const closeMenu = useCallback((restoreFocus = false) => {
    setIsOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: Event) => {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('touchstart', handlePointerDown);
    window.requestAnimationFrame(() => focusMenuItem('first'));

    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('touchstart', handlePointerDown);
    };
  }, [focusMenuItem, isOpen]);

  const handleTriggerKeyDown = useCallback((event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setIsOpen(true);
      window.requestAnimationFrame(() => focusMenuItem('first'));
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setIsOpen(true);
      window.requestAnimationFrame(() => focusMenuItem('last'));
      return;
    }

    if (event.key === 'Escape' && isOpen) {
      event.preventDefault();
      closeMenu(true);
    }
  }, [closeMenu, focusMenuItem, isOpen]);

  const handleMenuKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const items = wrapperRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    if (!items?.length) return;
    const currentIndex = Array.from(items).indexOf(document.activeElement as HTMLButtonElement);

    if (event.key === 'Escape') {
      event.preventDefault();
      closeMenu(true);
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
      items[nextIndex]?.focus();
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      const nextIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
      items[nextIndex]?.focus();
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      items[0]?.focus();
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      items[items.length - 1]?.focus();
      return;
    }

    if (event.key === 'Tab') {
      closeMenu();
    }
  }, [closeMenu]);

  return (
    <div className="org-switcher" ref={wrapperRef}>
      <button
        ref={triggerRef}
        type="button"
        className="org-switcher-trigger pressable"
        onClick={() => setIsOpen(!isOpen)}
        onKeyDown={handleTriggerKeyDown}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={`Current scope: ${currentLabel}. Select a different scope.`}
        data-haptic="light"
      >
        <span className="org-switcher-label" title={currentLabel}>{currentLabel}</span>
        <ChevronDownIcon />
      </button>
      {isOpen && (
        <div className="org-switcher-dropdown animate-scale-in" role="menu" aria-label="Scope options" onKeyDown={handleMenuKeyDown}>
          <button
            type="button"
            role="menuitem"
            className={`org-switcher-option ${!currentOrgId ? 'active' : ''}`}
            onClick={() => {
              onSelect(null);
              closeMenu(true);
            }}
          >
            {PERSONAL_SCOPE_LABEL}
          </button>
          {organizations.map((org) => (
            <button
              type="button"
              role="menuitem"
              key={org.id}
              className={`org-switcher-option ${currentOrgId === org.id ? 'active' : ''}`}
              onClick={() => {
                onSelect(org.id);
                closeMenu(true);
              }}
            >
              {org.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
});
