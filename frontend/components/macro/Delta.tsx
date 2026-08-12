'use client';

/**
 * Change indicator for the macro board.
 *
 * Mirrors the rule the on-chain cards follow: a delta that rounds to zero is not
 * a direction, so it stays neutral instead of rendering as a green rise, and an
 * unmeasured delta shows nothing at all rather than a confident 0.00%.
 */
export default function Delta({
  value,
  className = '',
}: {
  value: number | null;
  className?: string;
}) {
  if (value === null) return null;

  const rounded = Math.abs(value) < 0.005 ? 0 : value;
  if (rounded === 0) {
    return <span className={`font-mono tabnum text-fg-subtle ${className}`}>0.00%</span>;
  }

  return (
    <span className={`font-mono tabnum ${rounded > 0 ? 'text-up' : 'text-down'} ${className}`}>
      {rounded > 0 ? '▲' : '▼'} {Math.abs(rounded).toFixed(2)}%
    </span>
  );
}
