import { Construction } from 'lucide-react';

interface ComingSoonProps {
  /** Which implementation phase lands this board. */
  phase: string;
  /** What will actually be here, one bullet each. */
  items: string[];
}

/**
 * The body of a `/bist` page whose data layer is not built yet.
 *
 * Deliberately empty of numbers. The rule the rest of this codebase follows —
 * decline rather than guess, because a plausible wrong number in a trading
 * terminal is worse than an error — applies just as much to a placeholder:
 * mock rows here would be indistinguishable from real ones at a glance.
 */
export default function ComingSoon({ phase, items }: ComingSoonProps) {
  return (
    <div className="surface flex flex-col items-center gap-4 px-6 py-16 text-center">
      <Construction className="h-6 w-6 text-fg-subtle" />
      <div className="space-y-1">
        <p className="text-base font-medium text-fg">Bu ekran henüz hazır değil</p>
        <p className="text-sm text-fg-muted">{phase} kapsamında geliyor.</p>
      </div>
      <ul className="space-y-1 text-sm text-fg-subtle">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
