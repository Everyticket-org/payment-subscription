# Placeholder frontend container.
# The React application (public subscription pages, customer portal, admin
# portal) has not been scaffolded yet in this pass - see docs/implementation-status.md.
# This placeholder keeps `docker compose build` working end-to-end for the
# backend-focused Phase 1 slice delivered so far.
#
# NOTE: the frontend framework was changed from Angular (as originally
# specced in the master prompt) to React per Vishal's 2026-08-27 correction.
# See docs/implementation-status.md for details.
FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev || true
COPY . .
EXPOSE 3000
CMD ["npx", "http-server", "src", "-p", "3000"]
