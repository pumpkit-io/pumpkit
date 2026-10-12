# The web image: the built frontend served by Caddy, which also proxies /api to the backend.
# Build it from the repo root: docker build -f infra/web/Dockerfile .
FROM node:22-slim AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM caddy:2.10-alpine

COPY infra/web/Caddyfile /etc/caddy/Caddyfile
COPY infra/web/start.sh /usr/local/bin/pumpkit-web-start
COPY infra/web/start.d/ /etc/pumpkit/start.d/
COPY --from=build /app/dist /srv

ENTRYPOINT ["pumpkit-web-start"]
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
