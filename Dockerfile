# Multi-stage Dockerfile for ariaflow-server (@ariaflow/cli).

ARG NODE_VERSION=20-alpine

# ── builder: install deps and produce dist/ for every workspace ──
FROM node:${NODE_VERSION} AS builder
WORKDIR /build

RUN corepack enable && corepack prepare pnpm@9 --activate

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json tsconfig.base.json tsconfig.json ./
COPY packages/core/package.json packages/core/tsconfig.json ./packages/core/
COPY packages/api/package.json packages/api/tsconfig.json ./packages/api/
COPY packages/cli/package.json packages/cli/tsconfig.json ./packages/cli/

RUN pnpm install --frozen-lockfile=false

COPY packages/core/src ./packages/core/src
COPY packages/api/src ./packages/api/src
COPY packages/cli/src ./packages/cli/src

RUN pnpm build && pnpm --filter '@ariaflow/cli...' deploy --prod --legacy /out

# ── runtime: minimal Alpine + aria2c ──
FROM node:${NODE_VERSION} AS runtime
RUN apk add --no-cache aria2 tini

WORKDIR /app
COPY --from=builder /out ./
COPY openapi.yaml ./openapi.yaml

ENV ARIAFLOW_DIR=/data/config
VOLUME ["/data/config", "/data/downloads"]
EXPOSE 8000

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/index.js", "serve", "--host", "0.0.0.0", "--port", "8000", "--openapi-yaml", "/app/openapi.yaml"]
