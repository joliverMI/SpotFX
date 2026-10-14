/** One dropdown group in the grouped top menu (Artifacts ▾ / Engine ▾).
 * UI declutter plan §2 — behaviour exactly as specified there:
 *
 * - Touch: tap the group to open; tap an item to navigate (closes the
 *   menu); tap outside, tap the group again, or Esc to close. Never
 *   hover-only.
 * - Mouse: click opens; while one menu is open, pointing at the other
 *   group switches menus (standard menubar feel) — handled by
 *   `NavMenuBar` below via `openId`/`setOpenId` lifted one level up.
 * - Keyboard: `aria-haspopup="menu"`, `aria-expanded`, roving focus with
 *   ↑/↓, Enter/Space to go, Esc returns focus to the group button, Tab
 *   leaves the menu (closes it rather than trapping focus).
 * - The dropdown renders INLINE (an absolute-positioned child of the
 *   group), NEVER portalled to `<body>` — App.tsx's unsaved-changes guard
 *   is a capture-phase click handler on `<nav>` itself (`a.closest('a')`),
 *   so every item must stay a real `<Link>` rendered inside `<nav>` or the
 *   guard silently stops covering it. */
import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import type { NavGroup } from './navGroups';

export default function NavMenu({
  group, pathname, open, onOpen, onClose, isActiveGroup, anyOpen,
}: {
  group: NavGroup;
  pathname: string;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  isActiveGroup: boolean;
  /** True while ANY group's dropdown is open — lets pointing at this
   * group's trigger switch straight to it (the standard menubar feel),
   * without opening on a plain, nothing-else-open hover. */
  anyOpen: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const items = group.items ?? [];

  useEffect(() => {
    if (!open) return undefined;
    const onDocDown = (e: MouseEvent) => {
      if (rootRef.current?.contains(e.target as Node)) return;
      onClose();
    };
    document.addEventListener('mousedown', onDocDown);
    return () => document.removeEventListener('mousedown', onDocDown);
  }, [open, onClose]);

  const focusItem = (i: number) => {
    const n = items.length;
    const clamped = ((i % n) + n) % n;
    itemRefs.current[clamped]?.focus();
  };

  const onTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen();
      // Focus the first item on the next tick, once the menu has mounted.
      requestAnimationFrame(() => focusItem(0));
    } else if (e.key === 'Escape') {
      onClose();
    }
  };

  const onItemKeyDown = (e: React.KeyboardEvent, i: number) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(i + 1); } else if (e.key === 'ArrowUp') {
      e.preventDefault(); focusItem(i - 1);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      triggerRef.current?.focus();
    } else if (e.key === 'Tab') {
      onClose();
    }
  };

  return (
    <div className="nav-group" ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`nav-group-trigger${isActiveGroup ? ' active' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? onClose() : onOpen())}
        onMouseEnter={() => { if (anyOpen && !open) onOpen(); }}
        onKeyDown={onTriggerKeyDown}
      >
        <Icon name={group.icon} size={15} />
        <span className="nav-group-label">{group.label}</span>
        <Icon name="chevronDown" size={12} className={`nav-group-caret${open ? ' nav-group-caret-open' : ''}`} />
      </button>
      {open && (
        <div className="nav-group-menu" role="menu">
          {items.map((it, i) => (
            <Link
              key={it.to}
              to={it.to}
              role="menuitem"
              ref={(el) => { itemRefs.current[i] = el; }}
              className={`nav-group-item${it.match(pathname) ? ' active' : ''}`}
              onClick={onClose}
              onKeyDown={(e) => onItemKeyDown(e, i)}
            >
              {it.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
