import type { Metadata } from 'next';
import LandingPage from '@/components/landing/LandingPage';

// The only route in the app that is a server component. Everything else is a
// thin 'use client' wrapper because it needs hooks immediately; the landing page
// has no hooks at this level, and `metadata` only works from a server component.
export const metadata: Metadata = {
  title: 'Oracle-X | Analysis you can check line by line',
  description:
    'A local-first financial intelligence terminal. Three-stage AI analysis, RAG-backed chat, live on-chain and derivatives data across crypto and US equities.',
};

export default function LandingRoute() {
  return <LandingPage />;
}
