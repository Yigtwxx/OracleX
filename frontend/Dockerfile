# syntax=docker/dockerfile:1
#
# Oracle-X frontend image (Next.js 14, App Router).
#
# Build from the frontend directory:
#   docker build -t oracle-x-frontend ./frontend
#
# Node 20 matches the CI job (.github/workflows/ci.yml).

# ── Stage 1: dependencies ───────────────────────────────────────────────────
# Also used directly as the dev-mode target in docker-compose.override.yml.
FROM node:20-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── Stage 2: build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# These must be build args, not runtime env: next.config.js reads
# NEXT_PUBLIC_API_URL at module load to build the rewrite destination, and every
# NEXT_PUBLIC_* value is inlined into the client bundle at build time.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/prices
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── Stage 3: runtime ────────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3100 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# `output: 'standalone'` in next.config.js emits a self-contained server bundle
# with only the node_modules it actually uses.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# `output: 'standalone'` copies neither .next/static nor public/ into the bundle;
# both are the server's job to serve. Without this line the community seed post's
# image 404s in the production image while working fine in dev.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3100

CMD ["node", "server.js"]
