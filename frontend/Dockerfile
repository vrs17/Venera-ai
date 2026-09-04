# syntax=docker/dockerfile:1
# Multi-stage, non-root production image for the Venera frontend.
#   Stage 1 (build): Node 22 builds the Vite SPA -> /app/dist.
#   Stage 2 (serve): nginx-unprivileged (uid 101, :8080) serves dist/ + SPA
#                    fallback + /api proxy + security headers + /healthz.
#
# PRODUCTION: pin BOTH base images by @sha256 digest resolved from your internal
# registry mirror, and build against the internal npm registry (see
# deploy/ENTERPRISE.md). The floating tags below are for buildability today.
ARG NODE_IMAGE=docker.io/library/node:22-bookworm-slim
ARG NGINX_IMAGE=docker.io/nginxinc/nginx-unprivileged:1.27

# ---------------------------- build ----------------------------
FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV npm_config_fund=false npm_config_audit=false CI=true

# Install deps from the lockfile FIRST so the layer cache survives source changes.
COPY package.json package-lock.json ./
RUN npm ci

# Source, then build. .env.production (committed) sets VITE_API_BASE="" => the
# bundle calls relative /api; the backend URL is NOT baked into the JS.
COPY . .
RUN npm run build && test -f dist/index.html

# ---------------------------- serve ----------------------------
FROM ${NGINX_IMAGE} AS serve
# Hardened server block as an envsubst template; API_UPSTREAM injected at runtime.
COPY deploy/nginx.container.conf /etc/nginx/templates/default.conf.template
# Static bundle, owned by the runtime user.
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html

# Backend target is injected per-environment at RUNTIME, so ONE image promotes
# staging -> prod unchanged. Empty default => the deploy fails closed if unset.
ENV API_UPSTREAM="" \
    API_READ_TIMEOUT="120s"

EXPOSE 8080

# No in-image HEALTHCHECK: this minimal nginx image ships no wget/curl, and our
# deployment health-gates /healthz EXTERNALLY (CI smoke test, cutover.sh, and an
# orchestrator readiness probe) — the standard place for an HTTP probe. Adding a
# tool just to self-probe would only bloat the image.

USER 101
STOPSIGNAL SIGQUIT
