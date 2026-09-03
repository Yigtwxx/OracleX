'use client';

import AdminPage from '@/components/AdminPage';

/**
 * The same panel as `/admin`, mounted inside the BIST realm.
 *
 * Not a redirect and not a copy: the header reads the realm off the path, so an
 * admin who opened the panel from a BIST board on the global route watched the
 * whole bar switch to Kripto / Nasdaq under them. Two addresses for one
 * component is what keeps the tab set the reader was in.
 */
export default function BistAdminRoute() {
  return <AdminPage />;
}
