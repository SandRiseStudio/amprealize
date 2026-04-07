/**
 * ProfileMenu Component
 *
 * Reusable profile avatar with dropdown menu.
 * Used in sidebar footer (primary) and header (non-board modes).
 * Supports compact mode for collapsed sidebar.
 */

import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth';
import './ProfileMenu.css';

export interface ProfileMenuProps {
  /** Render in compact (avatar-only) mode */
  compact?: boolean;
  /** Position of the dropdown relative to trigger */
  dropdownPosition?: 'top' | 'bottom';
  /** Additional class names */
  className?: string;
}

export const ProfileMenu = memo(function ProfileMenu({
  compact = false,
  dropdownPosition = 'top',
  className = '',
}: ProfileMenuProps) {
  const { actor, logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const displayName = actor?.displayName ?? actor?.email ?? actor?.id ?? 'Profile';
  const initials = displayName
    .split(' ')
    .map((segment) => segment[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();

  // Click outside to close
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }

    if (menuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [menuOpen]);

  const focusMenuItem = useCallback((target: 'first' | 'last' | number) => {
    const items = menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
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
    setMenuOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    window.requestAnimationFrame(() => focusMenuItem('first'));
  }, [focusMenuItem, menuOpen]);

  const handleTriggerKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setMenuOpen(true);
        window.requestAnimationFrame(() =>
          focusMenuItem(event.key === 'ArrowDown' ? 'first' : 'last')
        );
        return;
      }

      if (event.key === 'Escape' && menuOpen) {
        event.preventDefault();
        closeMenu(true);
      }
    },
    [closeMenu, focusMenuItem, menuOpen]
  );

  const handleMenuKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const items = menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
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
    },
    [closeMenu]
  );

  if (!isAuthenticated) return null;

  return (
    <div
      className={`profile-menu-standalone ${compact ? 'profile-menu-compact' : ''} ${className}`}
      ref={menuRef}
    >
      <button
        ref={triggerRef}
        type="button"
        className="profile-menu-trigger pressable"
        onClick={() => setMenuOpen((prev) => !prev)}
        onKeyDown={handleTriggerKeyDown}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        data-haptic="light"
        title={compact ? displayName : undefined}
      >
        <span className="profile-menu-avatar">
          {actor?.avatarUrl ? (
            <img
              src={actor.avatarUrl}
              alt={displayName}
              className="profile-menu-avatar-image"
            />
          ) : (
            <span className="profile-menu-avatar-initials">{initials}</span>
          )}
        </span>
        {!compact && (
          <>
            <span className="profile-menu-name">{displayName}</span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
              className="profile-menu-chevron"
            >
              <path
                d={dropdownPosition === 'top' ? 'M3 7.5L6 4.5L9 7.5' : 'M3 4.5L6 7.5L9 4.5'}
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </>
        )}
      </button>
      {menuOpen && (
        <div
          className={`profile-menu-dropdown animate-scale-in profile-menu-dropdown-${dropdownPosition}`}
          role="menu"
          aria-label="Profile menu"
          onKeyDown={handleMenuKeyDown}
        >
          <div className="profile-menu-dropdown-header">
            <span className="profile-menu-dropdown-name">{displayName}</span>
            {actor?.email && (
              <span className="profile-menu-dropdown-subtitle">{actor.email}</span>
            )}
          </div>
          <button
            type="button"
            className="profile-menu-item"
            role="menuitem"
            onClick={() => {
              closeMenu();
              navigate('/settings');
            }}
          >
            Profile
          </button>
          <button
            type="button"
            className="profile-menu-item profile-menu-item-logout"
            role="menuitem"
            onClick={async () => {
              closeMenu();
              await logout();
            }}
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
});

export default ProfileMenu;
