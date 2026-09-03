'use client';

import { useCallback, useState } from 'react';
import type { AuthMode } from '@/components/auth/AuthCard';
import AuthModal from './AuthModal';
import LandingHeader from './LandingHeader';

interface MarketingShellProps {
  children: React.ReactNode;
}

/**
 * The chrome that outlives a navigation.
 *
 * The header lives in the route group's layout rather than in each page for one
 * concrete reason: the tab underline slides between tabs, and an element cannot
 * animate from a position it was not occupying a moment ago. With a header per
 * page, every tab click unmounted the bar and mounted a new one already at its
 * destination — the transition was declared, correct, and never once ran.
 *
 * Auth state comes with it. It has to live above the pages anyway now that the
 * control that opens the modal does, and it means a page can no longer forget to
 * wire it up.
 */
export default function MarketingShell({ children }: MarketingShellProps) {
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [authTrigger, setAuthTrigger] = useState<HTMLElement | null>(null);

  const openAuth = useCallback((mode: AuthMode, trigger: HTMLElement) => {
    setAuthTrigger(trigger);
    setAuthMode(mode);
  }, []);

  const closeAuth = useCallback(() => setAuthMode(null), []);

  return (
    <>
      <LandingHeader onOpenAuth={openAuth} />
      {children}
      <AuthModal mode={authMode} onClose={closeAuth} returnFocusTo={authTrigger} />
    </>
  );
}
