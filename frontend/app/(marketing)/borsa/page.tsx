import type { Metadata, Viewport } from 'next';

import BorsaPage from '@/components/borsa/BorsaPage';

export const metadata: Metadata = {
  title: 'Oracle-X | BIST 100 terminali',
  description:
    'Borsa İstanbul, TEFAS fonları ve KAP tek terminalde. Her getiri, enflasyona göre reel karşılığıyla birlikte.',
};

/**
 * Overrides the root layout's dark declaration for this route only. Without it
 * the browser paints form controls, the native scrollbar and the mobile address
 * bar dark over a light document.
 */
export const viewport: Viewport = {
  colorScheme: 'light',
  themeColor: '#eaeef2',
};

export default function BorsaRoute() {
  return <BorsaPage />;
}
