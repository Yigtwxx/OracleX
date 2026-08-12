'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, MessageSquare } from 'lucide-react';

import EligibilityNotice from '@/components/social/EligibilityNotice';
import { dmRefusalReasons } from '@/lib/api';
import { useDmEligibility, useStartConversation } from '@/hooks/useSocial';

/**
 * "Message" on somebody else's profile.
 *
 * The refusal is rendered where the button was rather than as a toast: the
 * reasons are a checklist with links in them, and a toast that disappears after
 * four seconds is the wrong shape for something the user has to act on.
 *
 * Renders nothing on your own profile — there is a Preview tab for that.
 */
export default function MessageButton({
  userId,
  viewerId,
}: {
  userId: string;
  viewerId: string | undefined;
}) {
  const router = useRouter();
  const start = useStartConversation();
  const { data: eligibility } = useDmEligibility();
  const [reasons, setReasons] = useState<string[]>([]);
  const [error, setError] = useState<string>();

  if (!viewerId || viewerId === userId) return null;

  const open = async () => {
    setReasons([]);
    setError(undefined);
    try {
      await start.mutateAsync(userId);
      // The Social tab owns the thread view; this hands off rather than
      // duplicating it behind a second route.
      router.push('/social');
    } catch (caught) {
      const refusal = dmRefusalReasons(caught);
      if (refusal.length > 0) setReasons(refusal);
      else setError(caught instanceof Error ? caught.message : 'Could not open a conversation.');
    }
  };

  if (reasons.length > 0) {
    return <EligibilityNotice eligibility={eligibility} reasons={reasons} className="mt-3" />;
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => void open()}
        disabled={start.isPending}
        className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
      >
        {start.isPending ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <MessageSquare className="h-3.5 w-3.5" />
        )}
        Message
      </button>
      {error && <p className="mt-1 text-sm text-down">{error}</p>}
    </div>
  );
}
