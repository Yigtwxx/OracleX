/** @type {import('next').NextConfig} */
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const nextConfig = {
  reactStrictMode: true,
  // Hide the dev-only overlay badges (the Next.js logo / static-route
  // indicator in the bottom-left corner). Dev-time only; no effect on prod.
  // Next 15 replaced the two per-badge switches (`appIsrStatus`,
  // `buildActivity`) with one: they are still read, but only to warn.
  devIndicators: false,
  // Emit a self-contained server bundle so the Docker runtime stage ships
  // only the node_modules actually used instead of the full install.
  output: 'standalone',
  // `output: 'standalone'` traces the imports a route reaches, and the OG
  // card's fonts are read at runtime with `fs` — a path string webpack cannot
  // follow. Without this the route builds fine and then throws ENOENT in the
  // container, which is the worst place to find out.
  //
  // Top-level since Next 15; under `experimental` it is now ignored silently,
  // which would have put the ENOENT back without a warning.
  outputFileTracingIncludes: {
    '/opengraph-image': ['./assets/og/**'],
  },
  eslint: {
    // Linting is a dedicated CI step (`npm run lint`); don't fail production
    // builds on lint issues.
    ignoreDuringBuilds: true,
  },
  images: {
    // Turns off `/_next/image`, which this app has no use for and which was
    // reachable anyway.
    //
    // Nothing here imports `next/image` — the image surfaces are plain `<img>`,
    // which is what the standing `@next/next/no-img-element` warnings are, and
    // `app/opengraph-image.tsx` renders through Satori. That is already the
    // reasoning behind the `sharp` override in `package.json`. But not
    // importing the component does not retire the route: the optimizer is part
    // of the server whether or not a page links to it, so GHSA-2xp9-vwfh-vxw4
    // — unauthenticated RCE via a crafted AVIF — was live on an endpoint no
    // page of ours would ever have called. Neither the Caddyfile nor the
    // rewrites filtered it.
    //
    // The `next` bump to 15.5.25 closes that advisory; this closes the route,
    // so the next one in the same component is not ours to be exposed to.
    // Adopting `next/image` means removing this and revisiting the `sharp`
    // override at the same time — they rest on the same fact.
    unoptimized: true,
  },
  webpack: (config) => {
    // The dev server compiles chunks on demand, and a cold backend start
    // saturates the machine loading embedding models — enough that a chunk
    // request outran the 120s default and the app died on a ChunkLoadError
    // before it had finished booting. The inline recovery script in
    // app/layout.tsx handles the failures this does not prevent.
    config.output.chunkLoadTimeout = 300_000;
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
  async redirects() {
    return [
      // The page was called Heatmap while three of its eight views were
      // heatmaps. Permanent, because the old path is in browser histories and
      // bookmarks and there is nothing left at it.
      { source: '/heatmap', destination: '/derivatives', permanent: true },
    ];
  },
};

module.exports = nextConfig;
