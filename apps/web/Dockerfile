# Build context is the repo root (the lockfile lives there): docker build -f apps/web/Dockerfile .
FROM node:24-alpine AS build
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter @comm-center/web...
COPY apps/web apps/web
RUN pnpm --filter @comm-center/web build

FROM nginx:alpine
# host:port of the API as seen from this container; override with -e API_UPSTREAM=...
ENV API_UPSTREAM=api:8000
COPY apps/web/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD ["wget", "-qO-", "http://127.0.0.1/"]
