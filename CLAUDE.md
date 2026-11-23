# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Source of truth

`SPECS.md` is the design record and the source of truth: `[DECIDED]` marks settled decisions, `[OPEN]` unresolved ones (section 5), section 6 is the phased plan with per-phase implementation notes (phase status lives there and in `git log`, not here). Read the section you need, not the whole file. Authorization is 4.6, decoupled workers 4.7. Worker and notifier rules are in `apps/worker/CLAUDE.md` and `apps/notifier/CLAUDE.md` (loaded when working there).

## Commands

Run from the repo root unless noted. Requires Node, pnpm (via Corepack), uv and Docker.

- `docker compose up -d --wait` (or `pnpm db:up`): start MySQL 8.4 (host port **3307**, db/user/password `comm_center`). Backend tests need it; `apps/api/app/config.py` defaults to this URL, or override `DATABASE_URL` in `.env`.
- `pnpm test:unit` needs nothing running; `pnpm test:integration` needs MySQL. API tests that touch the database must carry `pytestmark = pytest.mark.db`; unit tests must not import anything that connects at import time. Lint: API `ruff check`, web `tsc --noEmit`.
- Single API test: `cd apps/api && uv run pytest tests/test_db.py::test_database_is_mysql_8`. Single web test: `pnpm --filter @comm-center/web exec vitest run src/auth/auth.test.tsx -t "wrong password"`.
- Compose reads credentials and ports from `.env`; `deploy/*.example` hold env files for running images without compose. Deployment modes are in `docs/DEPLOYMENT.md`; keep it and `.env.example` in step when you add a setting.
- Contact import from a spreadsheet: `docs/IMPORT_CONTACTS.md` (`openpyxl` is a dev dependency, not in the API image).
- `pnpm db:migrate` applies migrations (the API container also runs `alembic upgrade head` on start). New migration: `cd apps/api && uv run alembic revision --autogenerate -m "..." --rev-id 000N`, then review it by hand (autogenerate cannot express triggers or the `contacts`/`users` circular foreign key; `tests/db/test_models.py` fails if models and migrations drift).
- Local development runs apps natively (`pnpm dev`: web on :5173 forwarding `/api` to :8000, `API_PROXY_TARGET` overrides); only MySQL is a container.
- Full containerized stack: `pnpm docker:up` / `pnpm docker:down`. The `api`, `web`, `worker` and `notifier` services sit behind compose profile `app` (the worker also has its own `worker` profile), so a plain `docker compose up` starts only MySQL. Every service must have a healthcheck (Dockerfile `HEALTHCHECK` for `api`/`web`, compose for `db`; give the GSM worker one too, with `depends_on: condition: service_healthy`). The API image uses `/opt/venv` (call `/opt/venv/bin/python`, not bare `python`); the web image builds from the repo root context.
- Create the first admin: `pnpm --filter @comm-center/api create-admin --username NAME`. Register a device: `register-device --name NAME --phone +63…` (prints the secret its worker signs in with). Run a worker with `WORKER_NAME=gsm-NAME`, `WORKER_SECRET`, `WORKER_PROVIDER` set: `pnpm --filter @comm-center/worker start`.
- After changing any API route or schema, regenerate the web client: `pnpm --filter @comm-center/web gen:api` (needs uv) and commit `apps/web/src/api/openapi.json` and `schema.d.ts` (`tests/test_openapi_contract.py` fails if stale). After changing a `/worker/*` route also run `pnpm --filter @comm-center/api gen:worker-contract`.
- `pnpm clean` removes everything the project installed inside the repo.

## Conventions

- **No attribution by-lines.** Do not add `Co-Authored-By` trailers, "Generated with Claude Code" lines or any similar by-line to commit messages or pull request descriptions.
- **Keep the developer machine clean.** Install nothing globally. Use project-local environments (`node_modules`, `apps/api/.venv`) and run tools through them (`pnpm`, `uv run`); put any new service in a container. Document new prerequisites in `README.md`.

## Working style: test-driven

Write the failing test first, then the code, then refactor; a phase is done only when its tests pass. Backend tests run against a real MySQL, never SQLite, because the design depends on MySQL behavior (generated-column unique indexes, `SKIP LOCKED`, check constraints, FK checks). The permission matrix (each seed role × endpoint × scope) is the regression suite; keep it green. Worker tests use the fake `ChannelProvider`.

## Database notes

- DB tests (`apps/api/tests/db/`, auto-marked `db`) build a throwaway `comm_center_test` database by running the real migrations as `root` (override with `TEST_DATABASE_ADMIN_URL`) and roll back each test. Negative tests must assert the specific constraint name (`pytest.raises(DBAPIError, match="uq_...")`); a bare "something failed" check can pass for the wrong reason, because most inserts need valid foreign keys first.
- `test_migration_roundtrip.py` runs migrations as the unprivileged app user. The immutability trigger on `users` needs `log_bin_trust_function_creators=1` on the MySQL server (set in `docker-compose.yml`).
- MySQL DDL is not transactional: a migration that fails midway leaves partial tables and no `alembic_version` row. Drop and recreate the dev database before retrying.
- The `groups` table is named `access_group` (`groups` is reserved in MySQL 8). Soft-deletable models are filtered by a session event in `app/models/base.py`; pass `execution_options(include_deleted=True)` to see deleted rows.
- No human user is seeded (the first admin comes from `create-admin`); GSM device agents are created by `register-device`.

## Architecture invariants (they span many files; rationale in `SPECS.md`)

- **Logs:** `activity_log` and `login_log` are written with `record_activity` / `record_login` (`app/audit.py`), which only add a row to the request's session. Add a `record_activity` call to every new mutating endpoint, and never put message text or secrets in a summary.
- **Ownership:** every resource row has a non-null, non-editable `owner_id` (the creator). "Own" means `owner_id = me`, not "myself". Self-service editing goes through `/auth/me`.
- **System agents:** `is_system = true`, `login_enabled = false`, immutable `agent_direction` (`inbound`/`outbound`). They own system-created rows (`system`, one inbound `gsm-<device>` per device, outbound `notification`) and have contact rows too.
- **Message direction is derived, not stored:** a human owner means outbound; a system agent owner follows its `agent_direction`. `contact_id` is the sender for inbound and the recipient for outbound. Ownership must never cross direction classes. Messages are immutable: only `status`, `sent_at`, `error_message` change (by the worker), plus a person's retry of a failed one; read state is per user in `message_read`. `reply_to_id` and `phone_number` (E.164 snapshot) are set once. `{{name}}` placeholders are filled by the server (`app/templating.py`, mirrored in `apps/web/src/lib/placeholders.ts`: keep them in step).
- **A user is a contact:** `users.contact_id` is a required unique FK. A contact's name is `first_name`, optional `middle_name`, `last_name`; `contacts.name` is a generated column, never written (`app/names.py:split_name` splits a single text). Phones live in `ContactPhone`, unique among non-deleted rows; a soft-deleted number gets a new contact, not a restore.
- **Soft deletes everywhere:** `deleted_at` only (no `is_deleted`). A contact linked to an active user cannot be deleted.
- **Authorization:** permissions are `(resource, action)` (`create`, `read_all`, `read_own`, `update`, `delete`, plus `read_received` on messages); `update`/`delete` apply to rows the caller can read. Groups are seed-only, nestable and additive, resolved through `group_closure` on every request; assigning groups requires `users:update` and only groups the caller already holds.
- **The worker has no database access and the API never sends pushes:** see `apps/worker/CLAUDE.md` and `apps/notifier/CLAUDE.md`. Never lock a range of `message_lease` or `push_outbox` with `FOR UPDATE` (gap locks deadlock): plain read, then lock by primary key.
- **List endpoints** share one `page`/`page_size`/`total` envelope; `total` is computed under the same permission scope.
- **Frontend security:** access token in memory, refresh token in localStorage, so always render SMS content (untrusted text) as React text and keep the strict CSP in `apps/web/nginx.conf` (no `unsafe-eval`: zod runs `jitless`, see `src/lib/zod.ts`). The browser only talks to its own origin under `/api`.
- **Token refresh is single-flight** (`apps/web/src/auth/tokens.ts`): the API ends all sessions if a spent refresh token is replayed, so never add a second code path that calls `/auth/refresh`.
- **Web tests:** Vitest in happy-dom with MSW 3 (`onUnhandledFrame: "error"`); use `renderApp`/`signIn` from `src/test/utils.tsx`. UI permission gating is cosmetic; the API stays the authority.
