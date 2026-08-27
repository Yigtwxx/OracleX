import {
  Calendar,
  Coins,
  Crown,
  Flame,
  Gauge,
  Link2,
  Newspaper,
  Percent,
  Pizza,
  Radar,
  Scale,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react';
import type { AlarmIconName } from '@/lib/alarms/registry';

/**
 * Icon names resolve here rather than in the registry, which stays free of
 * React so it can be imported by the node-environment vitest suite.
 */
export const ALARM_ICONS: Record<AlarmIconName, LucideIcon> = {
  trending: TrendingUp,
  percent: Percent,
  coins: Coins,
  flame: Flame,
  pizza: Pizza,
  radar: Radar,
  gauge: Gauge,
  crown: Crown,
  newspaper: Newspaper,
  calendar: Calendar,
  link: Link2,
  scale: Scale,
};
