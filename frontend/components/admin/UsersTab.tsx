'use client';

import { useState } from 'react';
import { Ban, Search, ShieldCheck, Undo2 } from 'lucide-react';

import BanDialog from '@/components/admin/BanDialog';
import {
  USERS_PAGE_SIZE,
  useAdminUsers,
  useBanUser,
  useSetUserPlan,
  useUnbanUser,
} from '@/hooks/useAdmin';
import type { AdminUser, AdminUserListParams } from '@/lib/api';

// One grid template, shared by the header row and every body row, so a column
// cannot drift between them. Same approach as components/overview/AssetTable.
const GRID = 'grid grid-cols-[1fr_110px_70px_110px_150px_96px] gap-2 px-4';

const PLANS = ['free', 'pro', 'whale'];
const STATUSES: { key: NonNullable<AdminUserListParams['status']>; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'banned', label: 'Suspended' },
];

export default function UsersTab({ currentUserId }: { currentUserId: string }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<NonNullable<AdminUserListParams['status']>>('all');
  const [offset, setOffset] = useState(0);
  const [banTarget, setBanTarget] = useState<AdminUser | undefined>();

  const params: AdminUserListParams = {
    search: search.trim() || undefined,
    status,
    limit: USERS_PAGE_SIZE,
    offset,
  };
  const { data, isLoading, isError } = useAdminUsers(params);

  const setPlan = useSetUserPlan();
  const ban = useBanUser();
  const unban = useUnbanUser();

  const users = data?.users ?? [];
  const total = data?.total ?? 0;
  const rangeLabel = total
    ? `${offset + 1}–${Math.min(offset + USERS_PAGE_SIZE, total)} of ${total}`
    : '0';

  return (
    <div className="surface overflow-hidden">
      <div className="flex flex-col justify-between gap-3 border-b border-line px-4 py-2.5 sm:flex-row sm:items-center">
        <h2 className="text-md font-semibold text-fg">Users</h2>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1 transition-colors focus-within:border-accent">
            <Search className="h-3 w-3 text-fg-subtle" />
            <input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                // A narrower result set has fewer pages; staying on page 3 of a
                // one-page result shows an empty table.
                setOffset(0);
              }}
              placeholder="Email or name"
              aria-label="Search users"
              className="w-40 bg-transparent text-base text-fg outline-none placeholder:text-fg-subtle"
            />
          </div>

          <div role="group" aria-label="Account status" className="flex items-center gap-1">
            {STATUSES.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-pressed={status === option.key}
                onClick={() => {
                  setStatus(option.key);
                  setOffset(0);
                }}
                className={`rounded-md px-2 py-1 text-sm transition-colors ${
                  status === option.key ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={`${GRID} border-b border-line bg-surface-2 py-1.5`}>
        <div className="label">User</div>
        <div className="label">Plan</div>
        <div className="label text-right">Posts</div>
        <div className="label">Joined</div>
        <div className="label">Status</div>
        <div className="label text-right">Actions</div>
      </div>

      {isLoading ? (
        <div className="divide-y divide-line" aria-hidden="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className={`${GRID} py-2.5`}>
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">
          The user list would not load.
        </div>
      ) : users.length === 0 ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">
          No account matches that.
        </div>
      ) : (
        <div className="divide-y divide-line">
          {users.map((user) => (
            <UserRow
              key={user.id}
              user={user}
              isSelf={user.id === currentUserId}
              isBusy={setPlan.isPending || ban.isPending || unban.isPending}
              onPlanChange={(plan) => setPlan.mutate({ userId: user.id, plan })}
              onBan={() => setBanTarget(user)}
              onUnban={() => unban.mutate(user.id)}
            />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-4 border-t border-line px-4 py-2.5">
        <span className="text-xs text-fg-subtle tabnum">{rangeLabel}</span>
        <div className="flex items-center gap-1.5">
          <PagerButton
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(offset - USERS_PAGE_SIZE, 0))}
          >
            Previous
          </PagerButton>
          <PagerButton
            disabled={offset + USERS_PAGE_SIZE >= total}
            onClick={() => setOffset(offset + USERS_PAGE_SIZE)}
          >
            Next
          </PagerButton>
        </div>
      </div>

      <BanDialog
        user={banTarget}
        isSubmitting={ban.isPending}
        onClose={() => setBanTarget(undefined)}
        onConfirm={(input) => {
          if (!banTarget) return;
          ban.mutate({ userId: banTarget.id, ...input });
          setBanTarget(undefined);
        }}
      />
    </div>
  );
}

interface UserRowProps {
  user: AdminUser;
  isSelf: boolean;
  isBusy: boolean;
  onPlanChange: (plan: string) => void;
  onBan: () => void;
  onUnban: () => void;
}

function UserRow({ user, isSelf, isBusy, onPlanChange, onBan, onUnban }: UserRowProps) {
  // The server refuses both of these for an admin account and for the caller
  // themselves; disabling here only saves the round-trip.
  const isProtected = user.is_admin || isSelf;

  return (
    <div className={`${GRID} items-center py-2.5`}>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-base text-fg">{user.full_name || 'No name'}</span>
          {user.is_admin && (
            <ShieldCheck className="h-3 w-3 shrink-0 text-accent" aria-label="Admin" />
          )}
        </div>
        <div className="truncate font-mono text-xs text-fg-subtle">{user.email ?? user.id}</div>
      </div>

      <select
        value={user.subscription_plan}
        disabled={isBusy}
        onChange={(event) => onPlanChange(event.target.value)}
        aria-label={`Plan for ${user.email ?? user.id}`}
        className="rounded-md border border-line bg-surface-2 px-1.5 py-1 text-sm text-fg transition-colors hover:border-line-strong focus:border-accent focus:outline-none disabled:opacity-50"
      >
        {PLANS.map((plan) => (
          <option key={plan} value={plan}>
            {plan}
          </option>
        ))}
      </select>

      <div className="text-right font-mono text-sm text-fg-muted tabnum">{user.posts_count}</div>

      <div className="font-mono text-xs text-fg-subtle tabnum">{formatDate(user.created_at)}</div>

      <div className="min-w-0">
        {user.is_banned ? (
          <div className="truncate">
            <span className="text-sm text-down">Suspended</span>
            {user.ban_reason && (
              <span className="ml-1 text-xs text-fg-subtle">— {user.ban_reason}</span>
            )}
          </div>
        ) : (
          <span className="text-sm text-fg-subtle">Active</span>
        )}
      </div>

      <div className="flex justify-end">
        {user.is_banned ? (
          <RowAction onClick={onUnban} disabled={isBusy} label="Reinstate">
            <Undo2 className="h-3 w-3" />
          </RowAction>
        ) : (
          <RowAction
            onClick={onBan}
            disabled={isBusy || isProtected}
            label={isProtected ? 'Admin accounts cannot be suspended' : 'Suspend'}
            destructive
          >
            <Ban className="h-3 w-3" />
          </RowAction>
        )}
      </div>
    </div>
  );
}

function RowAction({
  children,
  label,
  onClick,
  disabled,
  destructive,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={`flex items-center gap-1 rounded-md border border-line px-2 py-1 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        destructive
          ? 'text-fg-muted hover:border-down hover:text-down'
          : 'text-fg-muted hover:border-line-strong hover:text-fg'
      }`}
    >
      {children}
    </button>
  );
}

function PagerButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(0, 10);
}
