# Dev-mode container: runs the real Vite dev server (with HMR) against a
# bind-mounted ./frontend, matching docker-compose.yml's volume setup
# (source is mounted live; node_modules gets its own anonymous volume so
# the host's node_modules - or lack thereof - never shadows what's
# installed here). This replaces the earlier placeholder that predated
# the actual React app (see docs/implementation-status.md).
#
# NOT set up for a production build/serve yet - that would be a separate
# multi-stage Dockerfile (npm run build -> serve dist/ with a static
# server), left for when this is actually deployed somewhere.
FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
