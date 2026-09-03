import { Bricolage_Grotesque, Source_Serif_4 } from 'next/font/google';

/**
 * The BIST product page's own faces, loaded only where they are used.
 *
 * Declared here rather than in the root layout so the terminal — every other
 * route in the app — does not carry two extra `@font-face` blocks it will never
 * paint with. The variables are attached to this page's own root element.
 *
 * `latin-ext` is not optional: ı, İ, ğ, Ğ, ş and Ş live in that subset, and a
 * Turkish page set in a latin-only cut falls back mid-word on the commonest
 * letters in the language.
 */

/** The claim. An engineered grotesque with a wide axis — a poster face, not a UI one. */
export const displayFont = Bricolage_Grotesque({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-borsa-display',
  display: 'swap',
});

/** The argument. A serif, because the body copy here is prose making a case. */
export const bodyFont = Source_Serif_4({
  subsets: ['latin', 'latin-ext'],
  variable: '--font-borsa-body',
  display: 'swap',
});
