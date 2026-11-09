# Comm Center

> **Status: DRAFT — not final.** Items marked `[OPEN]` are decisions still to be confirmed. Items marked `[DECIDED]` were settled in discussion.

## 1. Overview

Comm Center is a centralized platform for managing messages originating from multiple channels. In the initial phase, the only supported channel/source is a **GSM module** (SMS send/receive via a physical GSM modem).

`[DECIDED]` Multi-channel support is **light abstraction only**: Message has a `channel` column (value `gsm` for now) and the GSM code sits behind a small `ChannelProvider` interface (`send`, `poll_inbound`). No other channels are built in this phase.

## 2. Tech Stack

**Frontend:** ReactJS, Tailwind CSS, shadcn/ui
**Backend:** FastAPI, MySQL, SQLAlchemy (+ Alembic for migrations)
**Tooling:** Turborepo for monorepo management, pnpm for the JS workspace `[DECIDED]`

### 2.1 Monorepo Structure (draft)

```
comm_center/
  apps/
    web/        # React + Tailwind + shadcn frontend
    api/        # FastAPI + SQLAlchemy backend (Python), incl. GSM worker
  packages/
    config/     # shared eslint/tsconfig/tailwind config
  turbo.json
  package.json  # root workspace + Turborepo config
```

- `[DECIDED]` No `packages/ui` for now. shadcn components live in `apps/web` until a second frontend exists.
- Turborepo orchestrates task pipelines (`build`, `dev`, `lint`, `test`) and caching via `turbo.json`.
- The frontend (`apps/web`) is a native Turborepo/Node workspace member.
- `[DECIDED]` The backend (`apps/api`) is Python, wrapped in a thin `package.json` whose scripts shell out to Python tooling (e.g., `"dev": "uvicorn app.main:app --reload"`, `"test": "pytest"`), so Turborepo can run it alongside the frontend.

## 3. Frontend

### 3.1 Pages

| Page | CRUD? | Notes |
|---|---|---|
| Login | No | Auth only; no listing/CRUD |
| Messages | Yes (Create = Send) | Tabs: **All**, **Sent**, **Received**. "Create" composes and sends a new outbound message instead of a raw DB insert. Read/Delete apply to message records. Messages are an immutable log: no edit UI. |
| Users | Yes | System users that log in. System agents (see 4.2) are hidden by default. |
| Contacts | Yes | Contact book of persons/entities messages are sent to/received from |
GSM device management and group management have no UI page in this phase `[DECIDED]`. Devices are configured via backend settings/seed (the data model supports several); groups are seeded. Group assignment happens in the Users page (a picker fed by `GET /groups`) for callers with sufficient permissions.

### 3.2 Common Requirements
- All data-table pages must be **paginated** (server-driven; page + page size controls).
- Each table page supports **search/filter** and **sort**. Proposed columns: Messages: status, direction, contact, date range. Users: group, active. Contacts: name, phone, type. Default sort `created_at` desc. `[OPEN: confirm]`
- Shared design system: shadcn/ui on Tailwind; a shared `DataTable` component reused across pages.
- Auth-gated routing: unauthenticated users redirected to Login; session/token persisted (JWT + refresh flow).
- UI hides actions the user lacks permission for, using the effective permission list from `GET /auth/me`. This is cosmetic only; the API is the authority.

### 3.3 Suggested Structure
- Routing: React Router
- Server state/data fetching: TanStack Query
- Client/auth state: Context or lightweight store (e.g., Zustand)
- Forms: react-hook-form + zod validation
- Layout: shared shell (sidebar/topbar nav) wrapping the pages, with Login outside the shell

## 4. Backend

### 4.1 Core Responsibilities
- REST API serving all CRUD/listing needs of the frontend.
- A separate **GSM worker process** (see 4.4) for sending and receiving.

### 4.2 Data Model (draft)

**Soft deletes:** every entity has a nullable `deleted_at`; non-null means deleted. `[DECIDED]` `deleted_at` alone is sufficient, no `is_deleted` flag.

**Ownership:** `[DECIDED]` every resource row has a non-null `owner_id` (FK to `users`), set from the authenticated actor at creation. It is **not editable** through normal update endpoints. Reassignment (a `reassign` action) is deferred beyond this phase. "Own" in any permission means `owner_id = current_user.id`. Soft-deleting a user does not cascade to resources they own.

**System agents:** `[DECIDED]` rows in `users` with `is_system = true` and `login_enabled = false` (no password hash; auth rejects them). They own resources created by the system or non-human actors, so `owner_id` is never null. They are never soft-deleted and are hidden from the Users page by default. Each system agent has an `agent_direction` (`inbound` | `outbound`); humans have it null (check constraint: required iff `is_system`). Both `is_system` and `agent_direction` are **immutable** after creation. Seeded by the first migration (before any other row):
- `system`: migrations, seeds, admin scripts; owns the initial admin user. Owns no messages.
- `gsm-<device>`: one **inbound** agent per GSM device, linked from `GsmDevice`; owns the SMS received on that device.
- `notification`: **outbound** agent for system-generated messages (e.g., notifications, auto-replies).
Each agent has a linked Contact row (its display name). The seed migration inserts `system` and its contact with explicit ids (user 1, contact 1) and FK checks disabled for that step, then sets both `owner_id`s to the `system` user; every other seed row is created normally afterwards. A bidirectional channel needs separate agents per direction; e.g., a future email channel gets `email-inbound` plus an outbound agent (or reuses `notification`). Human sends are owned by the human.

**Message direction is derived from the owner** `[DECIDED]` (there is no stored `direction` column):
- owner is a human → **outbound**, `contact_id` is the recipient
- owner is a system agent with `agent_direction = inbound` → **inbound**, `contact_id` is the sender
- owner is a system agent with `agent_direction = outbound` → **outbound**, `contact_id` is the recipient
Consequences: (a) the API returns a computed `direction` on every message so clients never re-derive it; (b) ownership may never be reassigned across direction classes (a human can never own an inbound message, nor an inbound agent an outbound one) when reassignment is introduced; (c) humans cannot record inbound messages by hand (no manual import/log of received messages); (d) direction-based scoping joins `users` on the owner.

Entities:
- **User**: id, contact_id (**NOT NULL, unique FK to Contact**), username (technical/login name), password_hash (null for system agents), is_active, is_system, agent_direction (null for humans), login_enabled, owner_id, created_at, updated_at, deleted_at. `[DECIDED]` A user *is* a contact (not the other way around): name, email and phone numbers live only on the linked Contact. Roles are replaced by group assignments (see 4.6). System agents also have a contact row (their name), with `username` as the technical name. An existing contact can be promoted to a user by linking a new user to it.
- **Contact**: id, name, type (person/entity; a user's contact is a person), email (optional, single), notes, owner_id, created_at, updated_at, deleted_at. Phone numbers live in ContactPhone.
- **ContactPhone** `[DECIDED]` (a contact can have several numbers): id, contact_id, phone_e164, label, is_primary, deleted_at. Uniqueness among non-deleted rows via a generated column `active_phone = IF(deleted_at IS NULL, phone_e164, NULL)` with a unique index (MySQL allows many NULLs). At most one primary per contact, enforced the same way. Soft-deleting a contact soft-deletes its phones in the same transaction, which frees the numbers.
- **Ownership of users/contacts** `[DECIDED]`: the owner is whoever created the row. A user's `owner_id` and its linked contact's `owner_id` can differ (e.g., Admin One creates a contact; Admin Two later creates a user linked to it: the contact stays owned by Admin One, the user is owned by Admin Two).
- **Auto-created contacts** are identified by ownership: owner is a system agent **and** no user is linked to the contact (agents' own contacts are linked, so they are excluded).
- **Message**: id, channel (`gsm`), contact_id (**NOT NULL**), content, status (queued/sending/sent/failed/delivered/received), owner_id, created_at, sent_at, received_at, error_message, deleted_at, plus the open fields below. No stored `direction`; it is derived from the owner (see above). `contact_id` is the sender for inbound messages and the recipient for outbound. For human-sent messages `owner_id` is the sender; for received messages it is the receiving device's inbound agent. The worker only updates `status`, `sent_at`, `error_message` and never changes `owner_id`.
  - `[DECIDED]` Messages from an unknown sender cause a new Contact (plus a ContactPhone) to be auto-created, owned by the receiving device's agent and named after the phone number so it can be renamed later. No flag/type marks it; see "Auto-created contacts" above. If the number belongs only to a soft-deleted contact, a **new** contact is created (the old one is not restored). Users with only `contacts:read_own` don't see auto-created contacts; that is accepted, and someone with `read_all` reviews them.
  - `[DECIDED]` `reply_to_id` (migration 0004): a nullable FK to `messages`, set once at creation on a reply to the received message it answers; null for every other message. Only received (inbound) messages can be replied to.
  - `[DECIDED]` `gsm_device_id`: a nullable FK used **for outbound messages only**, set by the worker when it claims the message (outbound owners are humans or the `notification` agent, so the device can't be derived). For inbound messages it is derived from the owner: `SELECT g.id FROM gsm_device g WHERE g.agent_user_id = m.owner_id` (`GsmDevice.agent_user_id` must be unique).
  - `[DECIDED]` `phone_number`: kept as a snapshot of the number actually used (E.164), set once at creation and never updated, so later contact edits/merges don't rewrite message history. The worker sends to this number, not the contact's current one.
  - `[DECIDED]` Phone numbers are unique among non-deleted ContactPhone rows, normalized to E.164. Inbound handling does find-or-create by number and must handle the duplicate-key race by re-reading.
- **GsmDevice** `[DECIDED]` seed/config only (no API or UI yet), owned by `system`: id, name, serial_port, phone_number, status (online/offline/error), agent_user_id (unique; the device's inbound system agent), owner_id, created_at, updated_at, deleted_at
- **Group, Permission, and join tables**: see 4.6.

Index `(owner_id, deleted_at)` on each resource table, since own-scoped reads are the hot path.

### 4.3 API Endpoints (draft)

**Auth**
- `POST /auth/login`, `POST /auth/logout`
- `GET /auth/me` (returns the user plus effective permissions)

**Users / Contacts**
- `GET /users`, `POST /users`, `GET /users/{id}`, `PUT /users/{id}`, `DELETE /users/{id}` (soft)
- same shape for `/contacts`
- All lists paginated, filter/search, exclude soft-deleted by default, and scoped by the caller's permissions (4.6).
- `POST /{resource}/{id}/restore` `[OPEN: restore needed, or is soft-delete one-way from the UI?]`

**Messages**
- `GET /messages?direction=all|sent|received` (paginated, scoped by 4.6; `sent` = outbound, `received` = inbound, evaluated via the owner; responses include a computed `direction`)
- `POST /messages/send` (creates + enqueues; the "Create" action; sets `owner_id` to the caller)
- `GET /messages/{id}`
- `DELETE /messages/{id}` (soft)
- No update endpoint `[DECIDED]`.

**Groups / access** `[DECIDED]` access management is seed-only; there is no API to create, edit or delete groups.
- `GET /groups` (read-only, returns groups with their effective permissions; gated by `groups:read_all`) so the user-management UI can offer a group picker.
- Group assignment is part of user create/update (`users` endpoints, gated by `users:create` / `users:update`), with the escalation rule in 4.6.

### 4.4 Messaging Service (GSM integration)

- `[DECIDED]` The worker is a **separate Python process** (not a thread in the API), using **MySQL as the queue**. The modem is a single serial resource, so exactly one worker loop owns each serial port; `--reload` and multiple uvicorn workers must never touch it.
- **Outbound:** claims `queued` messages with `SELECT … FOR UPDATE SKIP LOCKED`, sends via the modem, sets `sent`/`failed`. Multi-device-ready: one loop per `GsmDevice` / serial port.
- **Inbound:** polls the modem (or reacts to new-message URC events), finds or creates the sender's Contact, and inserts a message with `owner_id` = that device's inbound agent (which makes it inbound).
- Wraps AT commands in `services/gsm_service.py` (e.g., `pyserial` or `python-gsmmodem-new`) behind the `ChannelProvider` interface.
- Resilience: modem disconnects, retries, rate limiting. Proposed: 3 attempts with exponential backoff, then `failed`. Delivery reports (`delivered`) depend on modem/carrier support. `[OPEN: confirm retry/backoff and whether delivered is required]`
- Logging/observability for modem errors.

### 4.5 Non-functional / Cross-cutting
- JWT auth. Authorization is permission-based (4.6).
- Pagination contract: `page`, `page_size`, `total` envelope on all list endpoints. `total` is computed with the same permission scope, so hidden rows don't leak into counts.
- **Soft deletes everywhere:** DELETE sets `deleted_at`; a shared base model/mixin applies `deleted_at IS NULL` by default. Phone numbers are handled by the ContactPhone generated-column unique index (see 4.2). `username` uniqueness should use the same pattern so a soft-deleted user's username is reusable `[OPEN: confirm]`.
- Migrations via Alembic; seed data (system agents, permissions, system groups) ships in migrations.

### 4.6 Authorization (permissions and groups)

`[DECIDED]` Fine-grained, resource-level permissions grouped into additive, nestable groups.

**Permission** = (resource, action).
- Resources `[DECIDED]`: `users`, `contacts`, `messages`, `groups` (read-only for now, see 4.3). `gsm_devices` has no API, so it has no permissions.
- Actions `[DECIDED]`: `create`, `read_all`, `read_own`, `update`, `delete`. Messages additionally have `read_received`. `groups` has only `read_all`.
- **Scope of `update` and `delete`** `[DECIDED]`: they apply to the rows the caller can read. With `read_all` they apply to all rows; with only `read_own` they apply to rows the caller owns. Consequence: "read everything but edit only mine" cannot be expressed.
- Messages have no `update` permission (immutable log). Restore is not a permission yet (restore is still undecided).
- "Own" means `owner_id = current_user.id` ("created by me"), not "myself"; self-service goes through `/auth/me`.

**Group** = a set of permissions plus a set of child groups (a DAG; cycle validation when seeding). Effective permissions of a group = union of its own and all descendants'. Nesting is resolved into a closure table (`group_closure`), built by the migration, so each request needs one indexed join.

**User assignment** is additive: a user holds a list of groups; effective permissions = union across them.

**Escalation rule** `[DECIDED]`: assigning groups through the users endpoints requires `users:create`/`users:update`, and a caller can only assign groups whose effective permissions are a subset of their own.

**Seed groups** `[DECIDED]` (proposed set accepted "for now"; revisit with real usage). Building blocks:
```
users_admin        users(create, read_all, update, delete) + groups(read_all)
users_viewer       users(read_all)
contacts_admin     contacts(create, read_all, update, delete)
contacts_editor    contacts(create, read_all, update)
contacts_viewer    contacts(read_all)
messages_admin     messages(create, read_all, delete)
messages_operator  messages(create, read_all)
messages_agent     messages(create, read_own, read_received)
messages_viewer    messages(read_all)
```
Roles (composed of the building blocks):
```
admin     = users_admin + contacts_admin + messages_admin
operator  = contacts_editor + messages_operator + users_viewer     # support team: sees and sends all, manages contacts, cannot delete
agent     = contacts_viewer + messages_agent                       # sends; sees own conversations plus inbound
auditor   = contacts_viewer + messages_viewer + users_viewer       # read-only
```
Notes: `agent` has `contacts_viewer` (not own-only contacts) because replying needs to see inbound senders' auto-created contacts, which are owned by system agents. As a result agents cannot create or edit contacts; operators/admins manage contacts `[DECIDED]`. A later option is letting the send action accept a raw phone number and find-or-create the contact.

**Message visibility** (replaces the earlier "received is visible to all" rule): decided purely by permissions.
- `read_all` → every message.
- else visible = (`read_own` and `owner_id = me`) OR (`read_received` and the owner is a system agent with `agent_direction = 'inbound'`, via a join on `users`).
- neither → 403.
The same scope applies to list, detail, and counts, and drives the "All / Sent / Received" tabs.

**Users and contacts:** each write is checked against the resource it touches. Changing name, email or phone numbers requires a `contacts` permission on that contact; changing username, active status or group assignments requires a `users` permission. Both can be done from either page if the caller holds the needed permissions. `[DECIDED]` A contact linked to an active user cannot be deleted; soft-deleting a user leaves its contact in place. `[DECIDED]` Self-service: `/auth/me` profile endpoints (name, email, phone numbers, password) let a caller edit their own user and contact only, bypassing resource scoping, since `read_own` means "created by me", not "myself".

**Enforcement**
- `require(resource, action)` FastAPI dependency for endpoint-level checks.
- `scope(query, user, resource)` helper for read scoping, used by every list/detail query; `update` and `delete` reuse the same scope.
- `[DECIDED]` Permissions are checked on every request (loaded from the DB, not baked into the token), so changes take effect immediately.

**Storage** `[DECIDED]` in the database; groups and permissions are seeded by migration
- `permission(id, resource, action)` seeded, fixed in code
- `group(id, name, is_system, owner_id, deleted_at, …)`
- `group_permission(group_id, permission_id)`
- `group_group(parent_id, child_id)` direct nesting; `group_closure(ancestor_id, descendant_id)` precomputed
- `user_group(user_id, group_id)`

### 4.7 Decoupled workers (refactor; supersedes 4.4 where they differ)

Goal: the API and the workers are separate programs with separate images and versions. A worker holds no database credentials and imports nothing from the API; it only calls the API over HTTP. Several kinds of SMS device sit behind it: `fake` (testing), `android` (SMS Gateway for Android, available now) and `gsm_modem` (future).

- `[DECIDED]` **Pull only.** A worker always calls out to the API; the API never calls a worker. So a worker can be on the same network as its devices, behind NAT, or remote from the API, with no change.
- `[DECIDED]` **Worker identity.** A worker is a `worker_account` (its own table, not a `users` row: the users table's agent and contact rules do not fit a program). It is created by a CLI command (`create-worker`) that prints the secret once; only a hash is stored and nothing ships in a migration. `POST /worker/token` exchanges name and secret for a short-lived token of its own kind (`typ = worker`), so a worker token never works on a user endpoint and the other way round; there are no refresh tokens, the worker signs in again. Sign-ins share the login rate limit (keyed `worker:<name>`) and are written to `login_log` as `worker_login`, `worker_login_failed` and `worker_login_blocked`. Worker endpoints check the token kind directly (their own regression tests), not the `(resource, action)` groups, which are for people.
- `[DECIDED]` **Devices belong to a worker.** `gsm_device` gains `provider` (`fake` / `android` / `gsm_modem`), `config` (JSON, no secrets) and `worker_id`, assigned explicitly by an administrator, and replaces the overloaded `serial_port` (kept until the in-process worker is removed in Phase 8 step 4, then moved into `config`). Assignment is by CLI (`register-device --provider --config --worker`) for now; an admin API for it is a later addition `[OPEN]`. The API thus knows which workers it expects. A worker serves only the devices assigned to it.
- `[DECIDED]` **Secrets stay with the worker.** `config` holds only a reference such as `password_ref: "PHONE1_PASSWORD"`; the worker resolves it from its own environment. The API database never stores or transmits a device credential.
- **Handshake.** On start (and then as its heartbeat) the worker calls `POST /worker/session` with its version, the protocol version and the provider types it supports. The API refuses an incompatible protocol version with a clear error, and answers with the devices assigned to the worker, each with its `provider` and `config`. `last_seen` on the worker feeds the existing device `offline`/`error` banner, so an expected worker that never appears is visible.
- **Outbound.** `POST /worker/claim` runs the `SELECT … FOR UPDATE SKIP LOCKED` claim on the API side, sets the message `sending` with a lease, and returns it (long-poll, so a queued message is not delayed by a poll interval). `POST /worker/messages/{id}/result` reports `sent` or `failed` (with the error), after the worker's own retries. The existing rule stays: a message left `sending` when its lease expires is failed, never re-sent. The message `id` is passed to the provider as an idempotency key where the device supports one.
- **Inbound.** Two shapes behind one rule (a message is stored, then acknowledged):
  - *Polled* devices (a modem): the worker reads the device and posts to `POST /worker/inbound`, then acknowledges on the device only after the API answers success.
  - *Pushing* devices (Android): the phone sends a signed webhook straight to the API (`POST /devices/{id}/webhook`, HMAC-SHA256 of the raw body plus timestamp, rejected outside a five-minute window or on a bad signature), which stores the message and returns 200 only after the commit; the phone retries until then. The worker is not involved.
  - Both go through the same API ingest code (find-or-create contact, E.164 snapshot, owner = the device's inbound agent), and are idempotent per `(device, provider message id)`.
- `[DECIDED]` **Delivery status.** `delivered` becomes a real status, set from provider delivery reports (Android `sms:delivered`; a modem when it supports reports). `sent` still means the device accepted the message; the UI shows `delivered` as a further state.
- **Provider interface** (in the worker): every provider has `send(message) -> result` and `close()`. A provider that can be polled also has `poll_inbound()` and `acknowledge()`. One contract test suite runs against every provider (fake, Android over a mocked HTTP transport, and the modem over a simulated serial port).
- **Contract and versioning.** The contract is the API's OpenAPI schema plus a protocol version checked in the handshake. The worker's client is generated from the schema (as the web client is), so the two share no Python package. The API image owns the schema and migrations; the worker image has no database driver.
- `[OPEN]` Whether the phone can reach the API over HTTPS for webhooks (SMS Gateway requires HTTPS except for localhost). If not, a relay is needed.
- `[OPEN]` Lease length, long-poll timeout, and whether one worker may serve devices of several kinds (assumed yes).
- Unchanged: ownership, message direction derived from the owner, immutable messages (the worker side updates only `status`, `sent_at`, `error_message`), soft deletes, and the agent users per device.

## 5. Open Questions Summary

Resolved: multi-channel scope, message update, `is_deleted` flag, Python-in-Turborepo, package manager, `packages/ui`, worker process model, device management scope, ownership model, message visibility via permissions, `owner_id` reassignment (deferred), message direction derived from owner, `contact_id` non-null with auto-created contacts for unknown senders.

Message entity: no open items besides contact uniqueness (below).

Resolved (Contacts): phone uniqueness among non-deleted numbers, new contact for a soft-deleted number, auto-created contacts identified by ownership, users linked to contacts, multiple phone numbers, single email, creator-as-owner, bootstrap.

Resolved (users/contacts): self-service `/auth/me` profile endpoints; delete rules in 4.6.

Resolved (authorization): single `update`/`delete` scoped by the caller's read permission; access management seed-only with a read-only `GET /groups` and group assignment in user management (subset escalation rule); groups stored in the DB with a closure table; permissions checked per request; seed group set (building blocks + admin/operator/agent/auditor); GsmDevice is seed/config only, owned by `system`.

Still open:
1. Which columns need filtering/sorting on each table page?
2. ~~Retry/backoff expectations and whether `delivered` status is required.~~ Settled in Phase 5: 3 attempts with doubling backoff; `delivered` is not produced (revisit when a real modem reports delivery).
3. Is restore needed in the UI?
4. Can `username` be reused after a soft delete?
5. Seed/dev data strategy beyond the required system rows.

## 6. Implementation Plan

**Decisions** `[DECIDED]`: backend foundation first, then frontend and remaining backend in parallel. Python environment managed with **uv** (single lockfile; Turborepo wrapper scripts call `uv run ...`). No modem hardware yet, so the worker is built against a **fake provider** first. The browser keeps the login token in **memory / localStorage** (not an httpOnly cookie). Because script-readable storage is exposed to XSS, use a short-lived access token with a refresh flow, avoid rendering untrusted HTML (message content is untrusted SMS text, so it must always be escaped), and set a strict Content-Security-Policy.

**Testing approach** `[DECIDED]`: development is **test-driven**. Each behavior gets a failing test first, then the code, then refactoring; unit tests are written as development progresses and a phase is only done when its tests pass.
- Backend tests (pytest) run against a **real MySQL** (docker-compose), not SQLite, because the design relies on MySQL behavior (generated-column unique indexes, `SKIP LOCKED`, check constraints, FK checks). Each test runs in a rolled-back transaction or a fresh schema.
- Layers: unit tests for pure logic (E.164 normalization, direction derivation, group closure, escalation subset check); database tests for constraints and the `scope` helper; API tests through FastAPI's test client; the permission matrix (every seed role × endpoint × scope) as parametrized tests.
- Worker tests use the fake provider to cover the claim loop, retries, concurrent claims and the duplicate-key race on inbound contact creation deterministically.
- Frontend tests use Vitest and React Testing Library with MSW mocking the API from the generated OpenAPI types, testing behavior (permission-aware UI, pagination, forms) rather than markup.
- `turbo test` runs both suites. Phase 0 ships a passing example test in each app so the harness is proven before feature work starts.

**Phase 0: Scaffold.** pnpm workspace + Turborepo (`dev`, `build`, `lint`, `test` pipelines); `apps/web` (Vite, React, TypeScript, Tailwind, shadcn/ui); `apps/api` (FastAPI, SQLAlchemy 2, Alembic, pytest, ruff) with a thin `package.json`; docker-compose MySQL for dev and tests. Done when `turbo dev` starts both apps and `turbo test` runs.

**Phase 1: Data model and migrations.** Shared mixins (timestamps, `deleted_at` default filter, `owner_id`); all tables from 4.2 and 4.6; generated-column unique indexes (active phone, primary phone, username); seed migration (the `system` bootstrap with FK checks off, agents and their contacts, permissions, groups, closure table, initial admin); tests that exercise constraints directly (uniqueness after soft delete, `agent_direction` check). `username` is assumed reusable after soft delete unless decided otherwise.

**Phase 2: Authentication and authorization.** Login/logout/`/auth/me` with JWT access + refresh; `require(resource, action)` and `scope(query, user, resource)` (message visibility rule, `update`/`delete` follow read scope, group-subset escalation check); `/auth/me` profile endpoints; a permission test matrix covering each seed role against each endpoint and scope.

**Phase 3: Users, contacts and groups API** (done, see outcomes below). CRUD with phone handling, pagination, filter and sort; `GET /groups`; group assignment in user create/update; delete rules (contact linked to an active user cannot be deleted).

**Phase 4: Messages API** (done, see outcomes below). `POST /messages/send` (enqueue with snapshot `phone_number`); `GET /messages` with computed `direction`, tabs and scoped counts; `DELETE /messages/{id}`.

**Phase 5: GSM worker** (done except the real modem provider, see outcomes below). `ChannelProvider` interface and a fake provider; outbound claim loop (`SKIP LOCKED`, retries); inbound polling with find-or-create contact and duplicate-key race handling; then the real modem provider once hardware is available.

**Phase 6: Frontend** (done, see outcomes below; can start after Phase 2 and run alongside 3 to 5). App shell, login, route guards, permission-aware UI; shared `DataTable`; Users, Contacts, Messages pages; typed API client generated from FastAPI's OpenAPI schema.

**Phase 7: Hardening** (done, see outcomes below). Logging and modem-error visibility, login rate limiting, deployment approach.

**Phase 8: Decoupled workers** (planned, see 4.7). (1) Worker accounts, the session handshake, and device `provider`/`config`/`worker_id` (migration); (2) claim, result and inbound endpoints, with the worker moved onto them; (3) the Android webhook, delivery status and the idempotency key; (4) split the worker into its own app and image with a contract-checked client, the protocol version check and the shared provider contract tests; (5) the Android provider (already written against the old interface) and docs. Tests first at each step; the old in-process worker keeps working until step 2 replaces it.

**Risks.** Phase 1 blocks almost everything and is intricate, so review it before moving on. Hardware is the main schedule risk, mitigated by the fake provider. Open items from section 5 are needed at: `username` reuse in Phase 1; filter/sort columns in Phases 3 and 6; retry policy and `delivered` in Phase 5; restore after Phase 3; dev seed data late.

### Phase 1 outcomes (implementation notes)

- The groups table is `access_group` (`groups` is a reserved word in MySQL 8). Group nesting uses `group_group` plus a precomputed `group_closure` that includes reflexive rows.
- Seed migration: `system` (user and contact id 1, owns itself) and `notification` agents, 16 permissions, 9 building-block groups and 4 roles. **No admin user is seeded**; the first admin is created by a Phase 2 bootstrap command so no default credential ships in a migration. This replaces the earlier idea that `system` owns "the initial admin user". GSM device agents are created when a device is registered (Phase 5), not seeded. Agent contacts have `type = entity`.
- DB-level enforcement: CHECK constraints (agent direction iff system, system agents cannot log in or be soft-deleted, E.164 numbers), generated-column unique indexes (active username, active phone, one active primary phone per contact, active group name), and a trigger that makes `users.is_system` and `users.agent_direction` immutable. The trigger requires `log_bin_trust_function_creators=1` on any MySQL server running the migrations as a non-SUPER user. `[OPEN]` If that server setting is a problem for a deployment target, replace the trigger with application-level enforcement.

### Phase 2 outcomes (implementation notes)

- **Tokens:** HS256 JWTs signed with `JWT_SECRET`; access 15 min, refresh 7 days (both configurable). Refresh tokens are tracked in a new `refresh_token` table (migration `0003`, keyed by `jti`) so they can be revoked: `/auth/refresh` rotates (the presented token is spent), presenting a spent token revokes all of that user's refresh tokens, `/auth/logout` revokes one (idempotent), and a password change revokes all. Access tokens are not stored; they simply expire.
- **Per-request checks:** the access token only identifies the user. Every request reloads the user (must be active, not deleted, `login_enabled`, not a system agent) and the effective permissions, so changes and deactivation apply immediately.
- **Endpoints:** `POST /auth/login|refresh|logout`, `GET /auth/me`, `PATCH /auth/me/profile` (name, email), `PUT /auth/me/phones` (replaces the list; removed numbers are soft-deleted; a number held by another contact is a 409), `PUT /auth/me/password`. Phones are normalized to E.164 (`DEFAULT_PHONE_REGION`, default `PH`). Passwords are hashed with argon2, minimum 10 characters. Unknown user and wrong password return the same 401.
- **Authorization code:** `app/authz.py` has `effective_permissions`, `require(resource, action)`, `scope(stmt, user, resource)` (message visibility rule; other resources `read_all` or `read_own`; 403 otherwise) and `check_assignable_groups` (escalation). Soft-deleted groups, assigned or nested, grant nothing.
- **Escalation rule refinement:** for the subset check, `read_all` on a resource counts as covering `read_own` and `read_received` on it. Taken literally, an `admin` (who holds only `messages:read_all`) could not assign `agent` or `messages_agent`. This does not affect `require` or `scope`, where the permissions stay distinct.
- **Bootstrap:** `pnpm --filter @comm-center/api create-admin --username NAME` (`python -m app.cli create-admin`) creates a human in the `admin` group, owned by `system`. It refuses once any human user exists.
- **Matrix:** `tests/api/test_permission_matrix.py` checks each seed role against every `(resource, action)` through `require` and against message and contact read scope, with expected values written by hand from section 4.6. Business endpoints arrive in Phases 3 and 4 and will reuse the same helpers; their per-endpoint rows join the matrix then.
- **Login rate limiting:** added in Phase 7 (see its outcomes).

### Phase 3 outcomes (implementation notes)

- **Endpoints:** `GET|POST /contacts`, `GET|PUT|DELETE /contacts/{id}`, the same for `/users`, and `GET /groups`. Every list returns the `items`/`total`/`page`/`page_size` envelope (`page_size` 1 to 100, default 20), with `total` computed from the same scoped query. Out-of-scope or soft-deleted rows return 404 (not 403) so existence does not leak; a caller with no read permission on the resource gets 403.
- **Filter and sort (answers open question 1 for now):** contacts: `q` (name, email or phone, literal substring), `type`, `sort` = `name|created_at|updated_at`; users: `q` (username or name), `is_active`, `sort` = `username|created_at`; both take `order=asc|desc` and break ties by id. Groups are sorted by name. Unknown sort columns are a 422.
- **Contacts:** `PUT` is a full update of name/type/email/notes; `phones` omitted leaves numbers alone, a list replaces them (shared with `/auth/me/phones` in `app/contact_ops.py`). `owner_id` is never read from the body. Responses carry `user_id` (the active user linked to the contact). A contact linked to an active user cannot be deleted (409) or switched to `entity`; deleting soft-deletes its phones in the same transaction, which frees the numbers.
- **Users:** `POST` takes `username`, `password`, optional `is_active`, `group_ids`, and exactly one of `contact_id` (link an existing contact, which needs read access to it) or `contact` (create one, which needs `contacts:create`; the new contact is owned by the caller). `PUT` fields are optional: `username`, `is_active`, `group_ids` need `users:update`; `name`, `email`, `phones` need `contacts:update` on the linked contact (`email: null` clears it). `group_ids` replaces the set after the escalation check. System agents are invisible here (404). A caller cannot delete or deactivate themselves (409). Deleting a user soft-deletes it, revokes its refresh tokens and leaves the contact in place. Duplicate username or already-linked contact is 409. A username is reusable after a soft delete (the unique index ignores deleted rows), which settles open question 4 as "yes".
- **Not in this phase:** admin password reset (an admin sets the initial password only; users change it via `/auth/me/password`), restore endpoints (open question 3), and removing groups from a user the caller could not have assigned them to (not restricted by the spec).
- **Tests:** `tests/api/test_contacts.py`, `test_users.py`, `test_groups.py`, plus `test_endpoint_matrix.py` (each seed role against each endpoint).

### Phase 4 outcomes (implementation notes)

- **Endpoints:** `POST /messages/send`, `POST /messages/send-bulk` (below), `GET /messages`, `GET /messages/counts`, `GET /messages/{id}`, `DELETE /messages/{id}`. There is no update route (405). `/messages/counts` returns `{all, sent, received}` under the caller's read scope, for the tab badges.
- **Send:** body `{contact_id, content, phone?}`, needs `messages:create` and read access to the contact (a caller without it gets 403, a missing or deleted contact 404). `phone` must be one of the contact's active numbers (422 otherwise); omitted, the primary number is used, else the first. The E.164 number is copied into `phone_number` as the snapshot. The message is created `queued`, channel `gsm`, owned by the caller; `owner_id`, `status` and `direction` in the body are ignored. `content` must not be blank and is limited to 1600 characters (ten SMS segments, a choice not in the spec).
- **List:** `direction=all|sent|received` (`received` = owned by an inbound system agent, `sent` = everything else), `status`, `contact_id`, `q` (content or number, literal substring), `order=desc|asc` on `created_at` (newest first by default), plus the shared `page`/`page_size`/`total` envelope. Visibility, `total` and `counts` all come from `scope()`.
- **Computed fields:** every message carries `direction` (`app/messaging.py:derive_direction`), `contact_name`, and `gsm_device_id` (stored for outbound, derived from the receiving agent's `GsmDevice` for inbound). Owners and contacts are read including soft-deleted rows, so history survives deleting a user or contact. The `sent`/`received` filter uses a subquery on inbound agents rather than a join on `users`, for the same reason.
- **Delete:** soft, needs `messages:delete`, and only for messages the caller can read (404 otherwise). A `queued` or `sending` message can be deleted too; the Phase 5 worker must skip rows with `deleted_at` set when it claims work and must not resurrect them.
- **Tests:** `tests/test_messaging_logic.py` (direction), `tests/api/test_messages.py`, and message rows in `tests/api/test_endpoint_matrix.py`.

### Phase 5 outcomes (implementation notes)

> Superseded in part by Phase 8 (section 4.7): the worker no longer reads the database or takes a `--provider` flag; it signs in to the API and runs the devices assigned to it. The queue, retry and inbound rules below still hold.

- **Layout:** `apps/api/app/worker/`: `provider.py` (the `ChannelProvider` protocol: `send`, `poll_inbound`, `acknowledge`, `close`; `ProviderError` is retried, `PermanentSendError` is not), `fake.py`, `outbound.py`, `inbound.py`, `runner.py` (`DeviceWorker`, one loop per device), `__main__.py` (`python -m app.worker --provider fake`, one thread per registered device, SIGTERM/SIGINT stop it cleanly). The worker is its own process and never part of the API.
- **Outbound:** `claim_next` takes the oldest `queued` live message with `SELECT … FOR UPDATE SKIP LOCKED`, marks it `sending` and stores `gsm_device_id`. It sends to the message's `phone_number` snapshot. Transient errors are retried up to `WORKER_MAX_ATTEMPTS` (3) with waits of base, 2×base, … (`WORKER_BACKOFF_BASE_SECONDS`, 2 s), then the message is `failed` with the error text; a permanent error fails it at once; an unexpected exception fails it too, so nothing is left stuck in `sending`. Final status is written with a core `UPDATE`, so it also lands on a message deleted mid-send. No attempts column was needed: retries happen inside one claim.
- **Crash handling `[DECIDED]`:** on start, a device's own `sending` messages are marked `failed` ("delivery unknown") rather than re-queued, since they may already have gone out and re-sending would duplicate an SMS.
- **Inbound:** the sender is normalized to E.164 and looked up among live phones; an unknown sender gets a contact named after the number (type `person`, primary phone), owned by the device's inbound agent, created inside a savepoint. If the unique index rejects it (another writer won), the savepoint is rolled back and the winner's contact is re-read. The message is owned by the agent, status `received`, `received_at` from the modem, `gsm_device_id` left null (derived). A soft-deleted contact's number gets a new contact. The modem copy is acknowledged (deleted) only after the commit, so a crash re-delivers instead of losing; a message that fails to store is left on the modem. **Limitation:** a sender that is not a phone number (alphanumeric sender IDs such as promotional names) cannot satisfy the E.164 constraint, so it is logged and dropped.
- **Device lifecycle:** `register-device` (`app/devices.py`, `pnpm --filter @comm-center/api register-device --name … --serial-port … --phone …`) creates the entity contact, the `gsm-<name>` inbound system agent and the `GsmDevice`, all owned by `system`. `gsm_device.status` is `online` after a good cycle, `error` when polling fails (queued messages stay queued), `offline` on shutdown. Each cycle sends at most 20 messages before polling inbound again. A loop stops if its device is removed.
- **Deployment:** compose service `worker` (profiles `app` and `worker`, so it starts with the stack; healthcheck on a heartbeat file touched every cycle; depends on `db` and, when enabled, `api`). It runs the **fake provider only**, which logs sends but marks them `sent`, so it must not be used where real messages matter. A `Supervisor` (`app/worker/supervisor.py`) starts a loop per registered device and re-checks every poll interval, so a device registered later is picked up and the process idles (healthy) with none; with the fake provider and no device at all, a `fake` device is registered at startup (`ensure_fake_device`) so a fresh stack sends out of the box. Settings `WORKER_*` are in `.env.example` and `docs/DEPLOYMENT.md`.
- **Not done:** the real modem provider (needs hardware: AT commands over pyserial or python-gsmmodem-new, delivery reports, signal checks). It only has to implement `ChannelProvider` and be added to the `--provider` choices; passing the serial device into the container is noted in the compose file.
- **Tests:** `tests/test_worker_unit.py` (backoff, fake provider, CLI), `tests/worker/` (registration, claim order and filters, retry and backoff, permanent and unexpected errors, delete during send, `SKIP LOCKED` with a held lock, two concurrent workers sending each message exactly once, crash recovery, inbound find-or-create, the duplicate-key race, ack-after-commit, the runner loop). These tests commit for real and clean up after themselves.

### Phase 6 outcomes (implementation notes)

- **Stack as built:** React 19, Vite, Tailwind 4, shadcn-style components written by hand in `apps/web/src/components/ui` (Radix dialog and slot; a native `<select>` and a simple tab list instead of Radix popovers, so they are testable and accessible without extra machinery), React Router 7, TanStack Query, react-hook-form with zod. No `packages/config` yet.
- **Typed client:** `pnpm --filter @comm-center/web gen:api` exports FastAPI's OpenAPI document (`python -m app.export_openapi`) to `src/api/openapi.json` and generates `src/api/schema.d.ts` with openapi-typescript; `openapi-fetch` uses those types. Both files are committed so the web image builds without Python, and `apps/api/tests/test_openapi_contract.py` fails when the API changed and they were not regenerated.
- **Same-origin API:** the browser calls `/api/...`; Vite (dev and `preview`) and the nginx in the web image strip the prefix and forward to the API (`API_PROXY_TARGET` and `API_UPSTREAM` respectively). No CORS is needed and the CSP can say `connect-src 'self'`.
- **Session `[DECIDED]` details:** the access token is in memory, the refresh token in `localStorage` (`cc.refresh`). Refreshing is **single-flight**, because the API treats a spent refresh token coming back as theft and ends every session: React StrictMode's double effect or two parallel 401s must not send the same token twice. The token is read from storage at call time, so a refresh rotated by another tab is used (two tabs refreshing in the same instant can still collide; accepted). A rejected refresh token ends the session; a network error or 5xx keeps it and offers Retry. A 401 on an API call refreshes once and replays the request. Sign-out revokes the refresh token and clears the query cache.
- **Permission-aware UI:** navigation, buttons and form sections follow `GET /auth/me`'s permission list; row actions follow the API's scope (`update`/`delete` apply to rows the caller can read, so with only `read_own` just owned rows, and for messages `read_received` covers inbound ones). The group picker disables groups the caller could not assign, using the same subset rule as the API (`read_all` covers the narrower reads). This is cosmetic; the API refuses regardless and its message is shown.
- **Pages:** Login; Messages (All/Sent/Received tabs with scoped counts, status and text filters, date sort, view dialog, send dialog with contact search, phone choice and a 1600-character counter, delete; the list and the tab counts refresh by themselves (every 1.5 s while a message is `queued` or `sending`, every 3 s otherwise, so received messages appear without a reload; background tabs pause and returning to the tab refreshes at once; a failed background refresh keeps the rows on screen)); Contacts (search, type filter, sort, create/edit with a phone list and primary choice, delete with the server's refusal shown); Users (search, status filter, create with a new or an existing contact and groups, edit that sends only changed fields, delete; you cannot delete or deactivate yourself). A shared `DataTable` provides server-driven paging, page size and sorting, and list state (page, size, sort, filters) lives in the URL.
- **Security:** SMS text and every other server string is rendered as React text, never as markup (tests assert this). nginx sends a strict CSP (`script-src 'self'`, `connect-src 'self'`, `default-src 'none'`; `style-src` also allows inline styles because the dialog library injects a `<style>` element), plus `nosniff` and `no-referrer`. Zod runs with `jitless` (`src/lib/zod.ts`), because its default compiles parsers with `new Function`, which the CSP blocks and reports. The built app was run in headless Chrome against the compose stack: no console errors or CSP violations through sign-in, creating a contact, sending a message (watched going `queued` to `sent` live), creating a user, reloading twice and signing out.
- **Gaps against the proposed filters (section 3.2):** Messages have no contact or date-range filter and Users have no group filter, because the API does not offer them yet (messages can be searched by number or text). There is no page for editing your own profile or password (the `/auth/me` endpoints exist). Both are small follow-ups.
- **Tests:** Vitest with happy-dom (jsdom's `AbortSignal` is not accepted by Node's `fetch` under MSW) and MSW 3 (`onUnhandledFrame: "error"` fails a test that makes an unmocked request): tokens, client, permissions, auth and guards, `DataTable`, URL list state, and the three pages including per-role action matrices.

### Phase 7 outcomes (implementation notes)

- **Login rate limiting `[DECIDED]`:** failed sign-ins are rows in `login_attempt` (migration `0005`), so every API process shares the count. `POST /auth/login` answers `429` with `Retry-After` once a normalized username (trimmed, case-folded; unknown usernames count the same, so nothing reveals which exist) has `LOGIN_MAX_FAILURES` (5) failures, or one client address has `LOGIN_MAX_FAILURES_PER_IP` (20), within `LOGIN_LOCKOUT_SECONDS` (900). The check runs before the password is verified, so a correct password does not get through while locked; blocked attempts are not recorded (hammering does not extend the lock); a successful sign-in clears the username's failures; rows older than the window are deleted as new failures arrive. Code in `app/login_limits.py`. The usual trade-off applies: anyone who knows a username can lock it for up to the window. The per-address limit needs the real client address, which behind nginx means `FORWARDED_ALLOW_IPS` (compose sets `*`); see `docs/DEPLOYMENT.md`. See the follow-up below for the other endpoints.
- **Logging:** `app/logging_config.py` gives the API and the worker one stderr format, at `LOG_LEVEL`. Failed and blocked sign-ins are logged with the username and address (never the password). The worker already logged modem failures, retries and crash recovery; they now share the format.
- **Modem-error visibility `[DECIDED]`:** `gsm_device` gains `last_error` and `last_error_at` (migration `0006`). The worker records them when the modem cannot be polled and when a send fails after its last retry (a message the modem rejects as invalid is the message's problem, not the modem's, and is not recorded). The status still flips back to `online` on recovery; the last error stays as history. `GET /devices` (needs `messages:read_all`: admin, operator, auditor) returns each device's `status` and last error, and the Messages page shows a banner for those people when a modem is `error` or `offline`. There is still no device management through the API or UI (devices are registered from the command line).
- **Deployment approach:** unchanged (three modes in `docs/DEPLOYMENT.md`); it gained the logging, rate-limit and forwarded-address notes and the new settings. Containers log to stderr for the runtime to collect; no log files or rotation are managed by the app.
- **Not done:** alerting beyond the in-app banner and the logs, and a limit on sending volume (messages per user per hour).
- **Follow-up (admin unlock and other endpoints) `[DECIDED]`:** `login_attempt.kind` (migration `0007`) separates three counters sharing the table and the window: `login` (per username and per address, as above), `password` (wrong current password in `PUT /auth/me/password`, per user id, `PASSWORD_MAX_FAILURES` = 5, a 429 before the password is checked, success clears it) and `refresh` (invalid or replayed tokens in `POST /auth/refresh`, per address only, `REFRESH_MAX_FAILURES_PER_IP` = 30; valid refreshes are never counted, and the browser's single-flight refresh makes bad tokens rare). Other endpoints need a valid access token, which is checked against the database on every request, and are not limited. `POST /users/{id}/unlock` (needs `users:update`, same visibility rules as other user endpoints: 404 if out of scope; 204, also when nothing was locked) deletes that user's `login` and `password` failures; `UserOut` carries `locked` (the username has reached `LOGIN_MAX_FAILURES` inside the window), and the Users page shows a Locked badge and an Unlock button. A block by address cannot be lifted by an admin. The 429 message is now the generic "too many failed attempts; try again later".
- **Tests:** `tests/api/test_login_rate_limit.py`, `tests/api/test_devices.py` (plus a matrix row), `tests/test_logging_config.py`, modem-error cases in `tests/worker/`, and the banner and the 429 message in the web tests.

### Phase 8 outcomes (implementation notes)

- **Step 1 (done):** migration `0010` adds `worker_account` and, on `gsm_device`, `provider` (`fake`/`android`/`gsm_modem`, default `fake`), `config` (JSON, default `{}`) and `worker_id` (nullable FK). `app/worker_accounts.py` creates workers and checks secrets; `app/routers/worker.py` serves `POST /worker/token` and `POST /worker/session` (protocol version 1; a different version is a 409; the session lists only the caller's non-deleted devices and records `version`, `protocol_version` and `last_seen_at`). CLI: `create-worker --name`, and `register-device` gains `--provider`, `--config` (JSON object) and `--worker`. Tests: `tests/db/test_worker_tables.py`, `test_worker_accounts.py`, `test_cli_workers.py`, `tests/api/test_worker_auth.py`, `test_worker_session.py`. The in-process worker is untouched and still reads `serial_port`. Worker names are unique across deleted rows too (a plain unique index).

- **Step 2a (done, server side):** migration `0011` adds `message_lease(message_id, worker_id, device_id, expires_at)` (kept apart from `messages`, which stays immutable) and `inbound_ref(device_id, ref, message_id)` (unique per device and ref). New worker endpoints, all with a worker token and all answering 404 for a device that is not the caller's: `POST /worker/claim` (`{device_id, wait_seconds}`; oldest queued message by `SKIP LOCKED`, status `sending`, a lease of `WORKER_LEASE_SECONDS` = 120; waits up to `WORKER_LONG_POLL_SECONDS` = 20, polling the database once a second; answers `{message: {id, phone_number, content} | null, lease_seconds}`); `POST /worker/messages/{id}/extend`; `POST /worker/messages/{id}/result` (`sent` or `failed` plus error; 409 unless this worker holds the lease; a late result is accepted until the lease has been reaped; also reaches a message deleted meanwhile); `POST /worker/inbound` (`{device_id, ref, sender, content, received_at}`; stores through the shared `app/inbound.py`, answers 200 only after the commit with `{stored, duplicate, message_id}`; a repeated `ref` is a no-op, and a sender that is not a phone number is dropped but its `ref` is remembered; a zone-less time is read as UTC); `POST /worker/devices/{id}/status` (`online`/`offline`/`error` plus optional error, which is kept as history). Leases are reaped on every claim (message `failed`, "delivery unknown", never re-sent), and a worker opening a new session has its own leases failed at once. `ref` must identify one message for good: a modem must not use a reusable SIM index alone. The in-process worker still runs on the database directly until step 2b moves it; its ingest now calls the shared code. `[OPEN]` any device still claims any queued message (messages are not routed to a particular device).

- **Step 2b (done, the worker moved onto the API):** the worker (`apps/api/app/worker/`) no longer imports `sqlalchemy`, `app.db` or `app.models` (a test imports it in a fresh process and fails if they load). `client.py` (`ApiClient`) signs in with `POST /worker/token`, reuses the token until 30 seconds before it expires, signs in again once on a 401, and tells failures apart: `ApiUnavailable` (network, 5xx, 429: try later), `ApiConflict` (409: the API will not take this report) and `ApiError` (refused). `outbound.py` claims, sends with the retry policy, extends the lease between retries, and reports `sent` or `failed` (three tries to deliver the report; if it cannot be told, the lease fails the message later: delivery unknown, never re-sent). `inbound.py` posts each message to `/worker/inbound` and acknowledges it on the device only after the API answered (a duplicate is acknowledged too). `runner.py` (`DeviceWorker`) reports device status to the API. `supervisor.py` calls `POST /worker/session` every poll interval (the session is the heartbeat: the heartbeat file is touched only when the API answered, so a worker that cannot reach it reads as unhealthy), starts a loop per assigned device, stops the loop of a device taken away or deleted, and skips (logging once) a device whose provider it cannot run. Configuration: `WORKER_API_URL`, `WORKER_NAME`, `WORKER_SECRET`; there is no `--provider` flag any more, the device's own `provider` decides. **Restart versus heartbeat:** every session carries an `instance_id` (random per worker process, kept in `worker_account.instance_id`, migration `0012`); the same id again is a heartbeat and changes nothing, a new one means the worker restarted and its previous leases are failed ("delivery unknown"). CLI additions: `ensure-worker --name N [--fake-device]` (secret from `WORKER_SECRET`; used by the compose `worker-setup` one-shot, which also registers a fake device for a fresh stack) and `assign-device --name D --worker W [--provider P] [--config JSON]` (for devices registered before workers existed; the migration cannot guess their worker). `httpx` is now a runtime dependency. Tests: `tests/worker/` is rewritten to drive the real app through FastAPI's test client with real commits (`conftest.py`), plus `tests/test_worker_client.py` (client, no database), `tests/test_worker_isolation.py` and `tests/worker/test_claim_locking.py`. **Bugs found while verifying against the running stack and fixed:** (1) the lease reaper took range locks that blocked and deadlocked other workers' lease inserts; it now finds expired leases with a plain read and locks them by primary key (regression test holds the reaper's locks open while another session claims); (2) treating every session as a restart failed messages mid-send (see `instance_id`); (3) the fake provider reused the ref `file-1` after a restart, which the API rightly treated as a duplicate (refs now carry a per-run id). `[OPEN]` the worker's claim does not yet use the long poll (it polls on its interval), because one loop also polls inbound; it will matter for push-only providers such as Android.

- **Step 3 (done, server side):** `POST /devices/{id}/webhook` (`app/routers/webhooks.py`) receives the Android gateway's events. **Authentication `[DECIDED]`:** each device has its own signing key derived as HMAC-SHA256 of the device id under the server's `WEBHOOK_SECRET` (`app/webhooks.py`), so no key is stored; `app.cli webhook-info --name D --base-url URL` prints the URL and key to enter in the app. The app signs HMAC-SHA256(key, raw body + `X-Timestamp`) into `X-Signature`; the API refuses a timestamp more than five minutes away, compares in constant time, and answers one 401 for a bad signature, an unknown device and a device that is not `android` (nothing reveals which ids exist). A signed body that is not a JSON event is a 400; unhandled events (pings, MMS, batches) are a 200 `{ignored: true}` so the app stops retrying. **`sms:received`:** stored through the shared `store_inbound` (also used by `/worker/inbound`), once per event id (`wh:<event id>`; falls back to the app's message id), `sender` or the older `phoneNumber`, `receivedAt` converted to UTC; answers 200 only after the commit. **Delivery:** the id we give the gateway for a message is `cc-<message id>` (`dispatch.gateway_message_id`; the Android provider must send it as the gateway's `id`, step 5). `sms:delivered` and `sms:failed` (with the reason) apply only to that message when it belongs to this device and is `sending` or `sent`; `delivered` and `failed` are final; `sms:sent` is acknowledged and changes nothing (the worker marked it sent when the phone accepted it); an id that is not ours is ignored. A worker's own report never overwrites a status the phone already set (`finish` only updates a message still `sending`). `delivered` is now a real status (the web app already displays it). **Network `[DECIDED]`:** the webhook must be reachable over https from the phone; the documented setup is a Cloudflare tunnel or an https proxy restricted to the path `^/api/devices/[0-9]+/webhook$` so that only this endpoint is public (see `docs/DEPLOYMENT.md`). Tests: `tests/test_webhook_signature.py`, `tests/api/test_device_webhook.py`, additions to `test_worker_result.py` and `tests/db/test_cli_workers.py`. `[OPEN]` the gateway's event id being stable across its own retries is taken from its documentation, not yet observed on a real phone; verify when the phone is connected.

- **Step 4 (done, the split):** the worker moved to `apps/worker` (package `comm_center_worker`: `client.py`, `outbound.py`, `inbound.py`, `runner.py`, `supervisor.py`, `fake.py`, `provider.py`, `protocol.py`, `config.py`, `logging_config.py`, `__main__.py`) with its own `pyproject.toml`, `uv.lock`, `Dockerfile` and `package.json` (`@comm-center/worker`: `start`, `lint`, `test`); its dependencies are `httpx` and `pydantic-settings` only. The API image no longer contains the worker and the worker image contains no API code or database driver. **Contract `[DECIDED]`, differing from the earlier plan:** the client is handwritten, not generated, and checked against a committed contract instead: `apps/worker/contract/worker-api.json` is the `/worker/*` slice of the API's OpenAPI document (`app/export_worker_contract.py`, regenerated with `pnpm --filter @comm-center/api gen:worker-contract`). The API's `tests/test_worker_contract.py` fails when the file is stale or the protocol versions differ; the worker's `tests/test_contract.py` builds every response from the contract and validates every request body against it (also rejecting fields the contract does not know), and was checked to fail when the API drops a request field or a response field the client reads. The worker's `tests/test_loops.py` drive the loops against an in-memory fake API (`tests/fake_server.py`); the API's `tests/worker/` still run the real worker code against the real API with real commits (the API's pytest path includes `../worker`), which is where concurrency and the lease rules are tested. Worker count of tests: 51, no database. The compose `worker` service builds `./apps/worker`; `worker-setup` stays on the API image because it needs the database.

### Unread messages (addition after Phase 7)

- **Per user `[DECIDED]`:** whether a received message has been read is kept per person in `message_read(user_id, message_id, read_at)` (migration `0008`; primary key on the pair), so the immutable message is untouched and one person reading it does not change what others see. `MessageOut.unread` is computed for the caller: true for a received message with no row for them, always false for sent messages.
- **Marking read:** `POST /messages/{id}/read` (204, idempotent; any caller who can see the message, 404 otherwise; a no-op for sent messages) is called by the web app when a person opens a message's details. Replying to a message also marks it read for the replier. There is no "mark unread".
- **Tab numbers:** `GET /messages/counts` also returns `unread` (received messages in the caller's scope with no read row for them). The **All** and **Received** tabs show `<unread>/<total>`; **Sent** shows its total.
- **Existing messages:** the migration marks everything already received as read for the users that exist at that time, so upgrading does not turn the whole history bold. A user created later sees older received messages as unread; a created-after rule is a possible refinement.
- **UI:** an unread row has a blue dot beside the contact name and a bold message; opening it marks it read and the list refreshes. Not done: an unread count on the Received tab.

### Activity and login logs (addition after Phase 7)

- **Two logs `[DECIDED]`:** `activity_log(user_id, action, resource, resource_id, summary, ip, created_at)` records what a signed-in person changed; `login_log(event, username, user_id?, ip, created_at)` records sign-in history, apart from the rate-limit table `login_attempt`. Migration `0009`.
- **What is logged:** creates, updates and deletes of contacts, users and messages; send, bulk send and reply; unlock; a person's own profile, phone and password changes. Not logged: reads, marking a message read, requests that fail or are refused, and anything done by the worker. Summaries never contain message text or passwords.
- **Login events:** `login`, `login_failed` (also for unknown usernames, with no user id), `login_blocked`, `logout`, `sessions_revoked` (replayed refresh token). Successful refreshes are not logged.
- **Written with the change:** the row is added to the same transaction, so a rolled-back change leaves no entry.
- **Access:** new permission `logs:read_all` in a `logs_viewer` block included by `admin` and `auditor` (so an operator can no longer assign `auditor`, by the escalation rule). `GET /logs/activity` (filters `user_id`, `action`, `resource`, `q`) and `GET /logs/logins` (`user_id`, `event`, `q`), newest first; shown on the **Logs** page. Entries of deleted users still show their name.
- **Follow-up `[OPEN]`:** no retention or pruning yet; no date-range filter; the worker's sends are visible only as messages.

### Sending to many contacts (addition after Phase 6)

- **`POST /messages/send-bulk`** takes `{contact_ids, content}` (1 to 500 ids, same 1600-character text rules as `send`) and needs `messages:create` plus read access to the contacts. It creates **one message per contact**, each owned by the caller, queued to that contact's primary number (else its first), in the order given, all in one transaction. Repeated ids are collapsed. A contact that cannot be messaged is **skipped, not an error**: the response is `201 {queued: [MessageOut], skipped: [{contact_id, reason}]}` with the reason `no phone number` or `contact not found` (which is also what a contact the caller may not read looks like). If every contact is skipped nothing is queued and the response is still 201. The single-contact `send` is unchanged and still lets the caller choose which number to use.
- **UI:** the New message dialog has a multi-select picker (search, up to 100 contacts per search, "Select all shown", "Clear selection", removable chips, and the selection survives later searches; contacts without a phone are not offered). With exactly one contact you still choose the number; with several, each uses its primary number and the button reads "Send to N contacts". If some were skipped, the dialog stays open and lists who and why.

### Fake modem timing (addition after Phase 6)

The fake provider now imitates a modem's pace instead of sending instantly (which made a whole batch turn `sent` at once): each send takes `WORKER_FAKE_SEND_DELAY_SECONDS` (default 2) plus a random 0 to `WORKER_FAKE_SEND_JITTER_SECONDS` (default 1), the message stays `sending` meanwhile, and the next one is not claimed until it finishes (one loop per device, as with a real serial port). The wait is interruptible, so a shutdown does not hang. A cycle now sends at most 5 messages before polling inbound again (was 20), so received SMS are not held up behind a long queue. `FakeProvider` itself defaults to no delay, so tests stay instant; the delay is applied only by the worker process.

### Placeholders and replies (additions after Phase 6)

- **Placeholders `[DECIDED]`:** message text may contain `{{name}}` (Handlebars-style; spaces inside the braces are fine), which becomes the recipient's contact name. It is filled in **by the server when each message is created** (`app/templating.py`), so the stored text is exactly what is sent and the log stays immutable; it works in `POST /messages/send`, `send-bulk` and replies. `name` is the only placeholder so far (add more to `SUPPORTED` and pass their values to `render`). An unknown placeholder (`{{nam}}`, `{{Name}}`, `{{}}`) is a 422 that lists the supported ones, rather than texting literal braces. The 1600-character limit applies to the text **after** the name is inserted: a single send or reply is a 422, and in a bulk send that recipient is skipped (`message too long once the name is inserted`) while the others go. Names are inserted literally (a name such as `A\1 $0` is not read as a regex reference, and a name that looks like a placeholder is not expanded again). The browser mirrors the rules in `apps/web/src/lib/placeholders.ts` to validate and preview; keep the two in step. Contacts auto-created from received SMS are named after their number, so `{{name}}` gives the number for them.
- **Dialog:** an "Insert name" button puts `{{name}}` at the cursor, and a live preview shows the text as the first selected recipient will get it (with a warning when their name pushes it over the limit).
- **Replies `[DECIDED]`:** `POST /messages/{id}/reply` with `{content}` queues a message to the sender of a **received** message (outbound messages: 422 `only received messages can be replied to`). It needs `messages:create` and the ability to **see that message** (404 otherwise); it needs **no contacts access**, so an agent who sees inbound messages can reply. It sends to the number stored on the original (the snapshot), not whatever the contact's numbers are now, and still works if the contact was since deleted. The new message is an ordinary queued outbound message owned by the caller, plus `reply_to_id` pointing at the original (new nullable self-referencing column, migration `0004`, set once at creation). A message can be replied to more than once. `MessageOut` now carries `reply_to_id`.
- **UI:** received rows get a Reply action (for callers who may create messages), and the details dialog of a received message has a Reply button. The reply dialog shows who is being answered, at which number, and the original text (as text). A reply is marked `Reply to #N` in the list, and its details dialog shows the original it answers (or says it is no longer available).
