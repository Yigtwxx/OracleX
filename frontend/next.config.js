/** @type {import('next').NextConfig} */
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const nextConfig = {
  reactStrictMode: true,
  // Hide the dev-only overlay badges (the Next.js logo / static-route
  // indicator in the bottom-left corner). Dev-time only; no effect on prod.
  devIndicators: {
    appIsrStatus: false,
    buildActivity: false,
  },
  // Emit a self-contained server bundle so the Docker runtime stage ships
  // only the node_modules actually used instead of the full install.
  output: 'standalone',
  experimental: {
    // `output: 'standalone'` traces the imports a route reaches, and the OG
    // card's fonts are read at runtime with `fs` — a path string webpack
    // cannot follow. Without this the route builds fine and then throws
    // ENOENT in the container, which is the worst place to find out.
    outputFileTracingIncludes: {
      '/opengraph-image': ['./assets/og/**'],
    },
  },
  eslint: {
    // Linting is a dedicated CI step (`npm run lint`); don't fail production
    // builds on lint issues.
    ignoreDuringBuilds: true,
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
};

module.exports = nextConfig;
