# Placeholder frontend container.
# The Angular application (public subscription pages, customer portal, admin
# portal) has not been scaffolded yet in this pass - see docs/implementation-status.md.
# This placeholder keeps `docker compose build` working end-to-end for the
# backend-focused Phase 1 slice delivered so far.
FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev || true
COPY . .
EXPOSE 4200
CMD ["npx", "http-server", "src", "-p", "4200"]
