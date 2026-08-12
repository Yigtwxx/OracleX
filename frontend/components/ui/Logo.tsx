'use client';

/**
 * The Oracle-X mark: four reticle ticks read as an aperture, pierced by an X.
 *
 * The arms deliberately overshoot the ring — an X contained inside a circle is
 * already spoken for as "close"/"error", and the overshoot is what separates
 * the two readings.
 *
 * Geometry is duplicated in `frontend/app/icon.svg`, `docs/brand/oracle-x-mark.svg`
 * and `scripts/generate_brand_assets.py` (which renders the .ico and .png the
 * browsers ask for). Change one, change all four.
 */
interface LogoProps {
  /** Rendered edge length in px. */
  size?: number;
  /**
   * Draw the dark rounded-square backing. Off in-app: the chrome is already
   * `--surface`, so the capsule would be invisible, and the bare stroke suits
   * the terminal styling. On for standalone assets.
   */
  withCapsule?: boolean;
  className?: string;
}

export default function Logo({ size = 20, withCapsule = false, className }: LogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      aria-hidden
    >
      {withCapsule && <rect width="32" height="32" rx="7" fill="var(--surface)" />}
      <g stroke="currentColor" fill="none">
        <g strokeWidth="2.4">
          <path d="M12.63 7.66A9 9 0 0 1 19.37 7.66" />
          <path d="M24.34 12.63A9 9 0 0 1 24.34 19.37" />
          <path d="M19.37 24.34A9 9 0 0 1 12.63 24.34" />
          <path d="M7.66 19.37A9 9 0 0 1 7.66 12.63" />
        </g>
        <g strokeWidth="2.1">
          <path d="M7.09 7.09L24.91 24.91" />
          <path d="M24.91 7.09L7.09 24.91" />
        </g>
      </g>
    </svg>
  );
}
