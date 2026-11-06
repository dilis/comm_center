# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Phase 0 (scaffold) is done: a walking skeleton with `GET /health`, a placeholder `App`, and a passing test in each app. Everything else is still specified only in `SPECS.md` (a draft; `[DECIDED]` marks settled decisions, `[OPEN]` marks unresolved ones, section 5 lists what is still open). Section 6 is the phased implementation plan; next is Phase 1 (data model and migrations). Treat `SPECS.md` as the source of truth.

## Commands

Run from the repo root unless noted. Requires Node, pnpm (via Corepack), uv and Docker.

- `docker compose up -d --wait`: start MySQL 8.4 (host port **3307**, db/user/password `comm_center`). Backend tests need it running; `apps/api/app/config.py` defaults to this URL, or override with `DATABASE_URL` in `.env` (see `.env.example`).
- `pnpm install`: install JS deps (`esbuild` is the only build script approved, via `allowBuilds` in `pnpm-workspace.yaml`). Python deps: `cd apps/api && uv sync`.
- `pnpm dev` / `pnpm build` / `pnpm lint` / `pnpm test`: Turborepo runs the task in both apps. API lint is `ruff check`; web lint is `tsc --noEmit`.
- `pnpm test:unit` needs nothing running (no MySQL, no containers); `pnpm test:integration` needs MySQL (`pnpm db:up`). API tests that touch the database must carry `pytestmark = pytest.mark.db` (marker declared in `apps/api/pyproject.toml`); unit tests must not import anything that connects at import time.
- `pnpm clean` removes everything the project installed inside the repo.
- Local development runs apps natively; only MySQL is a container (`pnpm db:up`).
- Full containerized stack: `pnpm docker:up` (builds and waits until every service is healthy; `pnpm docker:down` stops it). API on :8000, web (nginx) on :8080. The `api` and `web` services sit behind the compose profile `app`, so a plain `docker compose up` starts only MySQL. Every service must define a healthcheck (add one, with `depends_on: condition: service_healthy`, for the GSM worker when it exists). The API image uses `/opt/venv` (call `/opt/venv/bin/python`, not bare `python`); the web image builds from the repo root context (`apps/web/Dockerfile`).
- Single API test: `cd apps/api && uv run pytest tests/test_db.py::test_database_is_mysql_8`
- Single web test: `pnpm --filter @comm-center/web exec vitest run src/App.test.tsx -t "renders the app title"`
- API only: `uv run uvicorn app.main:app --reload` (from `apps/api`); web only: `pnpm --filter @comm-center/web dev`.

Not set up yet: shadcn/ui, React Router/TanStack Query, Alembic migrations, `packages/config`. Add them in the phase that needs them.

## Conventions

- **No attribution by-lines.** Do not add `Co-Authored-By` trailers, "Generated with Claude Code" lines or any similar by-line to commit messages or pull request descriptions.
- **Keep the developer machine clean.** Install nothing globally. Use project-local environments (`node_modules`, `apps/api/.venv`) and run tools through them (`pnpm`, `uv run`); put any new service in a container. Document new prerequisites in `README.md`.

## Planned stack

Turborepo + pnpm monorepo: `apps/web` (React, Vite, Tailwind, shadcn/ui, React Router, TanStack Query, react-hook-form + zod) and `apps/api` (FastAPI, SQLAlchemy 2, Alembic, MySQL, Python managed with uv). The Python app joins Turborepo through a thin `package.json` whose scripts shell out to `uv run ...`. No `packages/ui`; shadcn components live in `apps/web`.

## Working style: test-driven

Write the failing test first, then the code, then refactor; a phase is done only when its tests pass. Backend tests run against a real MySQL (docker-compose), never SQLite, because the design depends on MySQL behavior (generated-column unique indexes, `SKIP LOCKED`, check constraints, FK checks). The permission matrix (each seed role × endpoint × scope) is the regression suite; keep it green. Worker tests use the fake `ChannelProvider`.

## Architecture invariants (they span many files)

- **Ownership:** every resource row has a non-null, non-editable `owner_id` (the creator). "Own" means `owner_id = me`, not "myself". Reassignment is deferred. Self-service editing goes through `/auth/me` endpoints.
- **System agents:** users with `is_system = true`, `login_enabled = false`, and an immutable `agent_direction` (`inbound`/`outbound`), required iff `is_system`. They own system-created rows (`system`, one inbound `gsm-<device>` agent per device, outbound `notification`). Agents have contact rows too. The seed migration bootstraps `system` and its contact with explicit ids and FK checks off.
- **Message direction is derived, not stored:** a human owner means outbound; a system agent owner follows its `agent_direction`. `contact_id` (NOT NULL) is the sender for inbound and the recipient for outbound. Ownership must never cross direction classes. The API returns a computed `direction`. Messages are immutable (no update); the worker changes only `status`, `sent_at`, `error_message`. `gsm_device_id` is stored for outbound messages only and derived from the owner's `GsmDevice.agent_user_id` for inbound. `phone_number` is an E.164 snapshot set once.
- **A user is a contact:** `users.contact_id` is a required unique FK (name, email and phones live on the contact). Phones are in `ContactPhone`, unique among non-deleted rows via a generated column; auto-created contacts for unknown senders are owned by the receiving device's agent and are identified by "system-agent owner and no linked user". A soft-deleted number gets a new contact, not a restore.
- **Soft deletes everywhere:** `deleted_at` only (no `is_deleted`); a shared mixin applies `deleted_at IS NULL` by default. A contact linked to an active user cannot be deleted.
- **Authorization:** permissions are `(resource, action)` with actions `create`, `read_all`, `read_own`, `update`, `delete` (plus `read_received` on messages). `update` and `delete` apply to the rows the caller can read. Groups are DB-stored, nestable and additive, resolved through a `group_closure` table and checked on every request. Group management is seed-only (read-only `GET /groups`); assigning groups requires `users:update` and only groups whose permissions the caller already holds. Message visibility is purely permission-based (`read_all`, or `read_own` and/or `read_received`).
- **GSM worker is a separate process** (never a thread in the API) using MySQL as the queue (`SELECT … FOR UPDATE SKIP LOCKED`), one loop per serial port, behind a `ChannelProvider` interface. A `channel` column exists on Message; no other channel is built.
- **List endpoints** share one `page`/`page_size`/`total` envelope, and `total` is computed under the same permission scope.
- **Frontend security:** the token lives in memory/localStorage, so always escape SMS content (untrusted text) and keep a strict CSP.
