# Comm Center

A centralized platform for managing messages from multiple channels. The first channel is SMS through a physical GSM modem.

- **Web:** React, Vite, Tailwind CSS (shadcn/ui to be added)
- **API:** FastAPI, SQLAlchemy, Alembic, MySQL
- **Monorepo:** pnpm and Turborepo; the Python API is wrapped in a thin `package.json` so Turborepo can run it

> **Status:** early. Phase 0 (scaffold) is done: a health endpoint, a placeholder page, tests and containers. The design is in [`SPECS.md`](SPECS.md) (a draft with the build plan in section 6). [`CLAUDE.md`](CLAUDE.md) holds the working conventions for Claude Code.

## Prerequisites

Only these are needed on your machine; everything else installs inside the repo.

- Node.js (developed on 24) with Corepack (provides pnpm; run `corepack enable` once if `pnpm` isn't found)
- [uv](https://docs.astral.sh/uv/) and a Python 3.13 interpreter (`apps/api/.python-version`)
- Docker (for MySQL, and optionally the whole stack)

## Quick start (apps run natively, MySQL in a container)

```sh
pnpm install                      # JS dependencies, including Turborepo, into ./node_modules
(cd apps/api && uv sync)          # Python dependencies into apps/api/.venv
pnpm db:up                        # MySQL 8.4 on localhost:3307, waits until healthy
pnpm dev                          # API on :8000 and web on :5173
```

Configuration defaults match `docker-compose.yml`. To override, copy `.env.example` to `.env`.

## Commands

Run from the repo root.

| Command | What it does |
|---|---|
| `pnpm test:unit` | Unit tests for both apps; needs no database or containers |
| `pnpm test:integration` | Tests marked `db`; needs MySQL (`pnpm db:up`) |
| `pnpm test` | Everything |
| `pnpm lint` | `ruff check` (API) and `tsc --noEmit` (web) |
| `pnpm build` | Type-check and build the web app |
| `pnpm db:up` | Start only MySQL |
| `pnpm docker:up` / `pnpm docker:down` | Build and run the full stack, or stop it |
| `pnpm clean` | Remove everything installed in the repo (`node_modules`, `.venv`, build output, caches) |

Run a single test:

```sh
cd apps/api && uv run pytest tests/test_db.py::test_database_is_mysql_8
pnpm --filter @comm-center/web exec vitest run src/App.test.tsx -t "renders the app title"
```

## Containers

`pnpm docker:up` builds the images and returns once every service reports healthy.

| Service | Port | Healthcheck |
|---|---|---|
| `db` (MySQL 8.4) | 3307 | `mysqladmin ping` |
| `api` | 8000 | `GET /health` |
| `web` (nginx) | 8080 | `GET /` |

`api` and `web` are behind the compose profile `app`, so plain `docker compose up` starts only MySQL and won't collide with the native dev servers.

## Keeping your machine clean

- Nothing is installed globally by this project. Turborepo, `pytest` and `ruff` run from `node_modules` and `apps/api/.venv`.
- Outside the repo you will only find caches: the pnpm store, the uv cache and the Corepack download of pnpm.
- `pnpm clean` removes everything the project put inside the repo, and `pnpm docker:down` stops the containers.

## Layout

```
apps/api   FastAPI app, tests, Dockerfile
apps/web   React app, tests, Dockerfile, nginx.conf
SPECS.md   Product and architecture spec (draft)
CLAUDE.md  Guidance for Claude Code
```
