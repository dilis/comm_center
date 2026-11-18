# Build context is this folder: docker build -t comm-center-notifier apps/notifier
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN useradd --system --uid 10001 notifier
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY comm_center_notifier ./comm_center_notifier
USER notifier
# No API, no migrations: it reads and updates the outbox tables (DATABASE_URL) and calls the push
# services. Run exactly one. Healthy while its heartbeat file keeps being touched.
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
  CMD ["/opt/venv/bin/python", "-c", "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime('/tmp/comm-center-notifier.heartbeat')<60 else 1)"]
CMD ["/opt/venv/bin/python", "-m", "comm_center_notifier"]
