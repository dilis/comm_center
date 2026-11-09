FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN useradd --system --uid 10001 worker
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY comm_center_worker ./comm_center_worker
USER worker
# No database, no migrations: the worker reaches the API over HTTP (WORKER_API_URL).
CMD ["/opt/venv/bin/python", "-m", "comm_center_worker"]
