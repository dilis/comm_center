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

## 5. Open Questions Summary

Resolved: multi-channel scope, message update, `is_deleted` flag, Python-in-Turborepo, package manager, `packages/ui`, worker process model, device management scope, ownership model, message visibility via permissions, `owner_id` reassignment (deferred), message direction derived from owner, `contact_id` non-null with auto-created contacts for unknown senders.

Message entity: no open items besides contact uniqueness (below).

Resolved (Contacts): phone uniqueness among non-deleted numbers, new contact for a soft-deleted number, auto-created contacts identified by ownership, users linked to contacts, multiple phone numbers, single email, creator-as-owner, bootstrap.

Resolved (users/contacts): self-service `/auth/me` profile endpoints; delete rules in 4.6.

Resolved (authorization): single `update`/`delete` scoped by the caller's read permission; access management seed-only with a read-only `GET /groups` and group assignment in user management (subset escalation rule); groups stored in the DB with a closure table; permissions checked per request; seed group set (building blocks + admin/operator/agent/auditor); GsmDevice is seed/config only, owned by `system`.

Still open:
1. Which columns need filtering/sorting on each table page?
2. Retry/backoff expectations and whether `delivered` status is required.
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

**Phase 3: Users, contacts and groups API.** CRUD with phone handling, pagination, filter and sort; `GET /groups`; group assignment in user create/update; delete rules (contact linked to an active user cannot be deleted).

**Phase 4: Messages API.** `POST /messages/send` (enqueue with snapshot `phone_number`); `GET /messages` with computed `direction`, tabs and scoped counts; `DELETE /messages/{id}`.

**Phase 5: GSM worker.** `ChannelProvider` interface and a fake provider; outbound claim loop (`SKIP LOCKED`, retries); inbound polling with find-or-create contact and duplicate-key race handling; then the real modem provider once hardware is available.

**Phase 6: Frontend** (can start after Phase 2 and run alongside 3 to 5). App shell, login, route guards, permission-aware UI; shared `DataTable`; Users, Contacts, Messages pages; typed API client generated from FastAPI's OpenAPI schema.

**Phase 7: Hardening.** Logging and modem-error visibility, login rate limiting, deployment approach.

**Risks.** Phase 1 blocks almost everything and is intricate, so review it before moving on. Hardware is the main schedule risk, mitigated by the fake provider. Open items from section 5 are needed at: `username` reuse in Phase 1; filter/sort columns in Phases 3 and 6; retry policy and `delivered` in Phase 5; restore after Phase 3; dev seed data late.
