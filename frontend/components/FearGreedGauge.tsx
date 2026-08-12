'use client';

import { useEffect, useState } from 'react';

interface FearGreedData {
  value: number;
  classification: string;
  timestamp: string;
}

interface FearGreedGaugeProps {
  data?: FearGreedData | null;
  isLoading?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export default function FearGreedGauge({ data, isLoading, size = 'md' }: FearGreedGaugeProps) {
  const [animatedValue, setAnimatedValue] = useState(0);

  // Animate needle on value change
  useEffect(() => {
    if (data?.value !== undefined) {
      const timer = setTimeout(() => {
        setAnimatedValue(data.value);
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [data?.value]);

  // Size configurations
  const sizeConfig = {
    sm: { width: 120, height: 70, fontSize: 'text-lg', labelSize: 'text-2xs' },
    md: { width: 200, height: 110, fontSize: 'text-2xl', labelSize: 'text-xs' },
    lg: { width: 280, height: 150, fontSize: 'text-2xl', labelSize: 'text-base' },
  };

  const config = sizeConfig[size];

  // Calculate needle rotation (-90 to 90 degrees for half circle)
  const needleRotation = -90 + (animatedValue * 180) / 100;

  // Get color based on value
  const getColor = (value: number) => {
    if (value <= 25) return '#ef4444'; // Red - Extreme Fear
    if (value <= 45) return '#f97316'; // Orange - Fear
    if (value <= 55) return '#eab308'; // Yellow - Neutral
    if (value <= 75) return '#84cc16'; // Light Green - Greed
    return '#22c55e'; // Green - Extreme Greed
  };

  const getGradientId = 'fearGreedGradient';

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center p-4">
        <div className="w-8 h-8 rounded-full border-2 border-line border-t-accent animate-spin" />
        <span className="text-xs text-fg-subtle mt-2">Loading…</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center p-4">
        <span className="text-base text-fg-subtle">No data</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center">
      {/* Gauge SVG */}
      <svg width={config.width} height={config.height} viewBox="0 0 200 110">
        {/* Gradient definition */}
        <defs>
          <linearGradient id={getGradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="25%" stopColor="#f97316" />
            <stop offset="50%" stopColor="#eab308" />
            <stop offset="75%" stopColor="#84cc16" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
        </defs>

        {/* Background arc */}
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          fill="none"
          stroke="var(--border)"
          strokeWidth="16"
          strokeLinecap="round"
        />

        {/* Colored arc */}
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          fill="none"
          stroke={`url(#${getGradientId})`}
          strokeWidth="16"
          strokeLinecap="round"
        />

        {/* Tick marks */}
        {[0, 25, 50, 75, 100].map((tick) => {
          const angle = (-90 + (tick * 180) / 100) * (Math.PI / 180);
          const x1 = 100 + 70 * Math.cos(angle);
          const y1 = 100 + 70 * Math.sin(angle);
          const x2 = 100 + 60 * Math.cos(angle);
          const y2 = 100 + 60 * Math.sin(angle);
          return (
            <line
              key={tick}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="var(--fg-subtle)"
              strokeWidth="2"
            />
          );
        })}

        {/* Needle */}
        <g
          transform={`rotate(${needleRotation}, 100, 100)`}
          style={{ transition: 'transform 1s cubic-bezier(0.34, 1.56, 0.64, 1)' }}
        >
          <line
            x1="100"
            y1="100"
            x2="100"
            y2="35"
            stroke={getColor(data.value)}
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx="100" cy="100" r="7" fill={getColor(data.value)} />
          <circle cx="100" cy="100" r="3.5" fill="var(--surface)" />
        </g>

        {/* Labels */}
        <text x="20" y="115" fill="var(--fg-subtle)" fontSize="9" textAnchor="start">
          Fear
        </text>
        <text x="180" y="115" fill="var(--fg-subtle)" fontSize="9" textAnchor="end">
          Greed
        </text>
      </svg>

      {/* Value display */}
      <div className="text-center -mt-2">
        <div
          className={`${config.fontSize} font-mono tabnum`}
          style={{ color: getColor(data.value) }}
        >
          {data.value}
        </div>
        <p className={`${config.labelSize} text-fg-muted mt-0.5`}>{data.classification}</p>
      </div>
    </div>
  );
}
