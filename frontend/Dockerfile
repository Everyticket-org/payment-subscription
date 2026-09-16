# Production build: compile the React app once (npm run build -> static
# files in dist/), then serve those with a minimal nginx - not the Vite
# dev server. This replaces the earlier dev-mode-only version (Vite dev
# server with HMR), which was fine for local development but was never
# meant to sit behind a real reverse proxy in production (see
# docs/implementation-status.md history / this file's own past comment).
#
# VITE_API_BASE_URL is baked into the compiled JS at BUILD time (Vite
# inlines import.meta.env.* during `vite build` - unlike the backend, a
# runtime `environment:` on the container has NO effect here, since by
# the time the container runs, the bundle is already static). It must be
# passed as a build ARG (see docker-compose.yml's `build.args`), and it
# must be a URL the BROWSER can reach - not a Docker-internal service
# name like "backend:8002".

FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
