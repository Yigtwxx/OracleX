import type { LucideIcon } from 'lucide-react';

export interface ToggleOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
}

interface ToggleGroupProps<T extends string> {
  /** Accessible name for the group — what the set of buttons is choosing between. */
  label: string;
  options: ToggleOption<T>[];
  value: T;
  onChange: (next: T) => void;
  className?: string;
}

/**
 * A segmented control: pick one of a handful of options.
 *
 * `aria-pressed` on real buttons rather than a radio group, because the
 * options act immediately rather than staging a choice for a submit.
 *
 * Lifted out of `components/overview/AdvancedHeatmap.tsx`, where it lived
 * privately while it had one consumer. The BIST boards need the same control in
 * four places, and a fifth copy of a nine-line component is how a design system
 * stops being one.
 */
export default function ToggleGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  className = '',
}: ToggleGroupProps<T>) {
  return (
    <div role="group" aria-label={label} className={`flex gap-0.5 ${className}`}>
      {options.map((option) => {
        const Icon = option.icon;
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors ${
              active ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            {Icon && <Icon className="h-3 w-3" aria-hidden="true" />}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
