# Deployment and bootstrap

Three ways to run Comm Center. Run the commands from the repo root. Each mode was brought up from scratch and checked end to end (service health, the web page and the migration state). Two supporting items were not run: the `uv sync --no-dev` step in mode 2 and the SQL for a native MySQL install.

| Mode | Use it for | MySQL | API and web |
|---|---|---|---|
| [1. Separate containers](#1-separate-containers) | Hosts where you manage containers yourself (no compose) | container | containers |
| [2. Separate processes](#2-separate-processes) | Development, or a host that runs processes directly | container or native install | native processes |
| [3. Docker Compose](#3-docker-compose) | The simplest full deployment | container | containers |

> **Current scope:** the API serves `/health`, authentication, users, contacts, groups and messages, and there is a GSM worker (fake provider only until a modem is attached). The web app (sign-in, Messages, Contacts, Users) talks to the API only through its own `/api` path, so the browser needs no CORS and only the web port has to be reachable by users. A fresh deployment has the schema and seed data but no human user: create the first admin as described below.

## Environment variables

The same few variables drive every mode.

| Variable | Used by | Meaning | Default (dev only) |
|---|---|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL container | Root password, set on first start only. The app never uses it. | `root` |
| `MYSQL_DATABASE` | MySQL container | Database created on first start | `comm_center` |
| `MYSQL_USER` | MySQL container | Application user, granted rights on that database only | `comm_center` |
| `MYSQL_PASSWORD` | MySQL container | Application user's password | `comm_center` |
| `DATABASE_URL` | API | SQLAlchemy URL, `mysql+pymysql://USER:PASSWORD@HOST:PORT/DATABASE` | the dev values on `127.0.0.1:3307` |
| `JWT_SECRET` | API | Signs access and refresh tokens; use a long random value outside development (`openssl rand -hex 32`). Changing it logs everyone out. | a dev-only value |
| `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS`, `DEFAULT_PHONE_REGION` | API | Optional: token lifetimes and the region used to read phone numbers typed without a country code | `900`, `604800`, `PH` |
| `WORKER_POLL_INTERVAL_SECONDS`, `WORKER_MAX_ATTEMPTS`, `WORKER_BACKOFF_BASE_SECONDS`, `WORKER_HEARTBEAT_FILE` | GSM worker | Optional: idle wait between cycles, sends per message before it is marked `failed`, wait before the second attempt (doubles each retry), and the file touched every cycle for healthchecks | `2`, `3`, `2`, `/tmp/comm-center-worker.heartbeat` |
| `LOG_LEVEL` | API, GSM worker | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` | `INFO` |
| `LOGIN_MAX_FAILURES`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_LOCKOUT_SECONDS` | API | Login rate limiting: failed sign-ins allowed for one username, and for one client address, within the window; the window (and so the longest lockout) in seconds | `5`, `20`, `900` |
| `PASSWORD_MAX_FAILURES`, `REFRESH_MAX_FAILURES_PER_IP` | API | Same window: wrong current passwords allowed per user in `PUT /auth/me/password`, and invalid refresh tokens allowed per client address in `POST /auth/refresh` | `5`, `30` |
| `FORWARDED_ALLOW_IPS` | API (uvicorn) | Proxy addresses whose `X-Forwarded-For` is believed; see [Login rate limiting](#login-rate-limiting) | `127.0.0.1` (compose sets `*`) |
| `API_UPSTREAM` | Web container | `host:port` nginx forwards `/api/` to, as seen from the web container. Set with `-e` outside compose. | `api:8000` |
| `API_PROXY_TARGET` | `pnpm dev`, `vite preview` | URL those two forward `/api` to | `http://127.0.0.1:8000` |
| `WORKER_FAKE_SEND_DELAY_SECONDS`, `WORKER_FAKE_SEND_JITTER_SECONDS` | GSM worker (fake provider) | How long the fake modem takes to send each message: the delay plus up to the jitter, in seconds. `0` and `0` make sends instant. | `2`, `1` |
| `DB_PORT`, `API_PORT`, `WEB_PORT` | Compose only | Host ports for the three services | `3307`, `8000`, `8080` |

Rules:
- `DATABASE_URL` must use the same user, password and database as the `MYSQL_*` values. In compose the API's URL is built from them, so you set them once.
- Use **URL-safe passwords** (letters and digits). They are embedded in `DATABASE_URL`, and characters such as `@` or `/` would need percent-encoding.
- MySQL reads `MYSQL_*` only when it creates an empty data directory. Changing them later does not change an existing database.
- The web image is a static build; its only setting is `API_UPSTREAM`, read by nginx when the container starts. nginx resolves that name at start, so the API must already be running (compose and the steps below start it first).
- The web server adds a strict Content-Security-Policy (scripts only from its own origin, requests only to its own origin) and the usual hardening headers. `style-src` allows inline styles because the dialog library injects a `<style>` element; scripts stay strict. If you put another proxy in front, keep these headers.
- For real deployments, change every default password, and do not publish the database port to the network (remove the `db` `ports:` entry in compose, or bind it to `127.0.0.1`).

### Which file holds what

| File | Used in mode | Contents |
|---|---|---|
| `.env` (copy of `.env.example`) | 2 and 3 | All variables above. Compose reads it automatically; the natively run API reads `DATABASE_URL` from it. |
| `deploy/db.env` (copy of `deploy/db.env.example`) | 1 | The four `MYSQL_*` variables for the database container |
| `deploy/api.env` (copy of `deploy/api.env.example`) | 1 | `DATABASE_URL` for the API container, with the database container's name as host |

`.env` and `deploy/*.env` are git-ignored; only the `*.example` files are committed.

## Initial migrations

The schema and starting data are created by eight Alembic migrations in `apps/api/alembic/versions/`:

| Revision | What it does |
|---|---|
| `0001` | Creates all tables, indexes, CHECK constraints, generated-column unique indexes, and a trigger that makes `users.is_system` and `users.agent_direction` immutable |
| `0002` | Seeds the `system` and `notification` agents (users and contacts), the 16 permissions, the 9 building-block groups, the 4 roles (`admin`, `operator`, `agent`, `auditor`) and the precomputed group closure |
| `0003` | Adds `refresh_token`, so logout and token rotation can revoke refresh tokens |
| `0004` | Adds `messages.reply_to_id`, linking a reply to the received message it answers |
| `0005` | Adds `login_attempt`, the failed sign-ins behind login rate limiting |
| `0006` | Adds `gsm_device.last_error` and `last_error_at`, the latest modem problem shown in the app |
| `0007` | Adds `login_attempt.kind`, so sign-in, password-change and token-refresh failures are counted apart |
| `0008` | Adds `message_read`, the per-user read state of received messages (everything already received counts as read for the existing users) |
| `0009` | Adds `activity_log` and `login_log`, and the `logs:read_all` permission (new `logs_viewer` group, included by `admin` and `auditor`) |

What to know:
- **No human user is seeded.** There is no default credential. Create the first admin once, after migrating: `ADMIN_PASSWORD=... pnpm --filter @comm-center/api create-admin --username NAME` (it prompts for the password if `ADMIN_PASSWORD` is unset, needs at least 10 characters, and refuses to run once any human user exists). In the API container: `docker compose exec api /opt/venv/bin/python -m app.cli create-admin --username NAME`.
- **Containers migrate themselves.** The API image runs `alembic upgrade head` before it starts serving. It is idempotent, so restarts are safe.
- **Native processes migrate explicitly:** `pnpm db:migrate`.
- **The trigger needs a server setting.** `0001` creates a trigger, and MySQL only lets a non-SUPER user do that when `log_bin_trust_function_creators=1`. The compose file and the commands below already pass `--log-bin-trust-function-creators=1`. A MySQL you provide yourself needs it too, for example `SET GLOBAL log_bin_trust_function_creators = 1;` or the same line under `[mysqld]` in its config. Without it, migration `0001` fails with error 1419.
- **A failed migration leaves partial tables.** MySQL DDL is not transactional. If a migration fails midway, drop and recreate the database before retrying (the data is only what the migrations created).
- **Check the state** with `alembic current` (see each mode). A healthy database reports `0009 (head)`.

## 1. Separate containers

No compose; you create the network, the volume and each container yourself.

```sh
# 1. Environment files (edit the passwords)
cp deploy/db.env.example deploy/db.env
cp deploy/api.env.example deploy/api.env

# 2. Build the images
docker build -t comm-center-api apps/api
docker build -f apps/web/Dockerfile -t comm-center-web .    # the web build context is the repo root

# 3. Network and storage
docker network create cc-net
docker volume create cc-db-data

# 4. Database, with its own healthcheck
docker run -d --name cc-db --network cc-net --env-file deploy/db.env \
  -v cc-db-data:/var/lib/mysql \
  --health-cmd='mysqladmin ping -h 127.0.0.1 -p"$MYSQL_ROOT_PASSWORD"' \
  --health-interval=5s --health-timeout=3s --health-retries=20 \
  mysql:8.4 --log-bin-trust-function-creators=1

# 5. Wait for the database to be healthy before starting the API
until [ "$(docker inspect -f '{{.State.Health.Status}}' cc-db)" = healthy ]; do sleep 3; done

# 6. API (runs the migrations, then serves) and web. Both images define a HEALTHCHECK.
docker run -d --name cc-api --network cc-net --env-file deploy/api.env -p 8000:8000 comm-center-api
docker run -d --name cc-web --network cc-net -e API_UPSTREAM=cc-api:8000 -p 8080:80 comm-center-web
```

Add `-p 127.0.0.1:3306:3306` to step 4 only if you need to reach the database from the host.

Verify:
```sh
docker ps --format 'table {{.Names}}\t{{.Status}}'      # all three should say (healthy)
curl http://127.0.0.1:8000/health                        # {"status":"ok"}
curl -s http://127.0.0.1:8080/ | grep '<title>'          # <title>Comm Center</title>
curl http://127.0.0.1:8080/api/health                    # {"status":"ok"}: the web container reaches the API
docker run --rm --network cc-net --env-file deploy/api.env comm-center-api \
  /opt/venv/bin/alembic current                          # 0009 (head)
```

Run migrations by hand (for example after pulling a new version, before replacing the API container):
```sh
docker run --rm --network cc-net --env-file deploy/api.env comm-center-api /opt/venv/bin/alembic upgrade head
```

Stop and remove (add the last line only to delete the data):
```sh
docker rm -f cc-web cc-api cc-db && docker network rm cc-net
docker volume rm cc-db-data
```

## 2. Separate processes

The API and web run as ordinary processes on the host. MySQL is the only thing that may be a container.

**Prerequisites:** Node with Corepack, `uv`, and Python 3.13 (see the README).

**Environment:**
```sh
cp .env.example .env     # edit it; DATABASE_URL must match the database you use
```

**MySQL** (pick one):
- **Container (simplest):** `pnpm db:up`. It reads `.env`, creates the database and user, and waits until healthy.
- **A MySQL 8.4 you already run:** create the database and user, and enable the trigger setting from the section above.
  ```sql
  CREATE DATABASE comm_center CHARACTER SET utf8mb4;
  CREATE USER 'comm_center'@'%' IDENTIFIED BY 'your-password';
  GRANT ALL ON comm_center.* TO 'comm_center'@'%';
  SET GLOBAL log_bin_trust_function_creators = 1;
  ```
  I verified the container route; this SQL mirrors what the container does but was not run against a native MySQL install.

**Install, migrate and run:**
```sh
pnpm install                                  # JS dependencies into ./node_modules
(cd apps/api && uv sync --no-dev)             # Python dependencies into apps/api/.venv (use plain `uv sync` if you also want the tests)
pnpm db:migrate                               # applies 0001 to 0009

# API (keep it running; add --reload only for development)
cd apps/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Web: build once, then serve apps/web/dist (second terminal, from the repo root)
pnpm --filter @comm-center/web build
pnpm --filter @comm-center/web exec vite preview --host 127.0.0.1 --port 8080
```

`vite preview` is for checking the build; it forwards `/api` to the API like nginx does (`API_PROXY_TARGET` if the API is not on `127.0.0.1:8000`). In production serve `apps/web/dist` with a real web server and give it the same two rules as `apps/web/nginx.conf`: fall back to `index.html` for unknown paths, and forward `/api/` to the API with the prefix removed. For long-running use, put both processes under a supervisor such as systemd. For development, `pnpm dev` starts both with hot reload instead.

Verify:
```sh
curl http://127.0.0.1:8000/health                      # {"status":"ok"}
curl -s http://127.0.0.1:8080/ | grep '<title>'        # <title>Comm Center</title>
curl http://127.0.0.1:8080/api/health                  # {"status":"ok"}: the proxy reaches the API
(cd apps/api && uv run alembic current)                # 0009 (head)
```

## 3. Docker Compose

The simplest full deployment. `api` and `web` sit behind the `app` profile, so a plain `docker compose up` starts only MySQL.

```sh
cp .env.example .env          # edit the passwords and ports
docker compose --profile app up -d --build --wait     # or: pnpm docker:up
```

`--wait` returns once every service is healthy. Startup order is enforced: `web` waits for `api`, and `api` waits for `db`. The API applies the migrations itself on start.

Verify (use your `API_PORT` and `WEB_PORT`):
```sh
docker compose --profile app ps                        # db, api and web all (healthy)
curl http://127.0.0.1:8000/health                      # {"status":"ok"}
curl -s http://127.0.0.1:8080/ | grep '<title>'        # <title>Comm Center</title>
docker compose exec api /opt/venv/bin/alembic current  # 0009 (head)
```

Run migrations by hand:
```sh
docker compose --profile app run --rm api /opt/venv/bin/alembic upgrade head
```

Update to a new version: `git pull`, then `docker compose --profile app up -d --build --wait`. The API container migrates the database before it serves.

Stop: `docker compose --profile app down` keeps the data. `docker compose --profile app down -v` also deletes the database volume.

To run several copies side by side (for example a test copy), give each its own project name, env file and ports:
`docker compose -p cc-test --env-file other.env --profile app up -d --wait`.

## GSM worker

The worker sends queued messages and stores received ones. It is a **separate process**, never part of the API, because it owns the modem's serial port: run exactly one worker per set of devices, and never under `--reload`. It uses MySQL as its queue, so it needs the same `DATABASE_URL` as the API and a migrated database.

- **Compose:** the worker is the `worker` service and starts with the rest of the stack (`pnpm docker:up`). It is healthy while its heartbeat file is fresh, and it waits (healthy) if no device is registered yet.
- **Native:** `pnpm --filter @comm-center/api worker -- --provider fake`.
- **Devices:** the worker watches for devices, so one registered later is picked up within a few seconds, with no restart. Register a modem (creates the device and its inbound agent `gsm-<name>`) with `pnpm --filter @comm-center/api register-device --name main --serial-port /dev/ttyUSB0 --phone "+639170000000"` (in the API container: `docker compose exec api /opt/venv/bin/python -m app.cli register-device ...`).

**Only the fake provider exists yet.** It logs sends instead of transmitting them (they are still marked `sent`), but it behaves like a modem in timing: messages are sent strictly one at a time, each staying `sending` for `WORKER_FAKE_SEND_DELAY_SECONDS` plus up to `WORKER_FAKE_SEND_JITTER_SECONDS` seconds (about 2 to 3 by default), so a batch to many contacts completes gradually. If no device is registered it adds one called `fake` so a fresh stack works out of the box. Do not run it where real messages matter. `--fake-inbox FILE` makes it deliver SMS from a JSON-lines file (`{"from": "+639171234567", "text": "hi"}` per line) for trying things out; the compose worker reads `/tmp/fake-inbox.jsonl`, so you can "receive" a message with `docker compose exec worker sh -c "echo '{\"from\": \"0917 123 4567\", \"text\": \"hello\"}' >> /tmp/fake-inbox.jsonl"`. It goes through the real inbound path: the sender's contact is found or created, and the message appears on the Received tab. The real modem provider arrives with the hardware; compose will then also need the serial device passed through (`devices:`).

Behaviour to know:
- A message is attempted up to `WORKER_MAX_ATTEMPTS` times with doubling waits, then marked `failed` with the error. A number the modem rejects outright is failed at once.
- If the worker dies mid-send, those messages are marked `failed` on the next start (they may already have gone out; re-sending could duplicate them).
- Received SMS are removed from the modem only after they are stored. A sender that is not a phone number (such as an alphanumeric name) cannot be stored and is dropped with a warning in the log.
- Device status (`online`, `offline`, `error`) is kept in `gsm_device.status`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| API container exits; log shows `(1419, 'You do not have the SUPER privilege …')` | The MySQL server lacks `log_bin_trust_function_creators=1`. Start it with `--log-bin-trust-function-creators=1` (or `SET GLOBAL`), drop and recreate the database, and start the API again. |
| `Table … already exists` on a retry, or `access_group` missing | A previous migration failed midway. Drop and recreate the database (or `down -v` in compose), then retry. |
| API cannot connect (`Can't connect to MySQL server`, `Access denied`) | `DATABASE_URL` host, port, user, password or database does not match the database. In containers the host is the database container's name, not `127.0.0.1`. |
| Changed `MYSQL_PASSWORD` and the app cannot log in | MySQL only reads `MYSQL_*` on first start. Recreate the volume, or change the password inside MySQL. |
| `pnpm: command not found` | Run `corepack enable` once. |
| A port is already in use | Set another `DB_PORT`, `API_PORT` or `WEB_PORT` in `.env` (compose), or change the `-p` mapping. |

## Logging and modem errors

The API and the worker write one line per event to stderr (`2026-11-09 08:00:00 WARNING app.worker: ...`), at the level in `LOG_LEVEL`, so `docker compose logs api worker` (or journald, for native processes) is the log. What is logged at WARNING and above: failed and blocked sign-ins (with the username and address), a modem that cannot be reached, messages that fail after their retries (with the modem's error), SMS that could not be stored, and the worker marking messages `failed` after a crash.

Modem problems are also visible in the app. The worker records a device's `status` (`online`, `offline`, `error`) and its latest error and time, and people who can read every message (admin, operator, auditor) see them in `GET /devices` and in a banner on the Messages page whenever a modem is `error` or `offline`. The last error is kept after recovery, as history, until the next one replaces it. A message that could not be sent also shows its error in the Messages table.

## Login rate limiting

`POST /auth/login` counts failed attempts in the `login_attempt` table (so all API processes share the count). After `LOGIN_MAX_FAILURES` failures for one username (case and surrounding spaces ignored; unknown usernames count too, so nothing reveals which exist), or `LOGIN_MAX_FAILURES_PER_IP` from one address, within `LOGIN_LOCKOUT_SECONDS`, sign-in answers `429` with a `Retry-After` header until the oldest of those failures ages out. A correct password does not get through while locked; attempts made while locked are not counted, so they do not extend the lock; a successful sign-in clears that username's failures.

The same mechanism protects two more endpoints, each with its own counter: `PUT /auth/me/password` (someone at an unlocked session guessing the current password: `PASSWORD_MAX_FAILURES` per user) and `POST /auth/refresh` (invalid or replayed refresh tokens: `REFRESH_MAX_FAILURES_PER_IP` per address; a valid refresh is never counted). Both answer `429` the same way. Other endpoints need a valid access token and have no limit.

**Unlocking:** an administrator (anyone with `users:update`) can clear a user's lock at once with the unlock button on the Users page (`POST /users/{id}/unlock`), which also clears that user's password-guessing counter. Locked users show a *Locked* badge (`locked` in `GET /users`). An address blocked by the per-address limit cannot be unlocked this way; it waits out the window.

Two things to know:
- A lockout can be triggered against a real user by anyone who knows the username (the usual trade-off); it lifts by itself after the window.
- The per-address limit needs the real client address. Behind the bundled nginx the API sees nginx's address unless it believes `X-Forwarded-For`, which uvicorn does only for addresses in `FORWARDED_ALLOW_IPS`. Compose sets it to `*`, which is fine while only the web port is reachable by users; if the API port is exposed too, a caller could forge the header and dodge the per-address limit (the per-username limit still holds), so restrict the API port or set `FORWARDED_ALLOW_IPS` to the proxy's address. When you run the API containers yourself (mode 1), set it the same way.

## Activity and sign-in logs

Two append-only tables record what happens, both readable on the **Logs** page (or `GET /logs/activity`, `GET /logs/logins`) by people with `logs:read_all` (the `admin` and `auditor` roles):

- `activity_log`: who created, changed or deleted contacts, users and messages, sent or replied to messages, unlocked a user, or changed their own profile, phones or password; with the client address. Reading and failed or refused requests are not logged. Message text and passwords are never stored in it.
- `login_log`: sign-ins (`login`, `login_failed`, `login_blocked`), sign-outs (`logout`) and `sessions_revoked` (a spent refresh token was replayed). It is separate from `login_attempt`, which only drives rate limiting and is pruned.

Nothing prunes these tables; they grow with use. Archive or delete old rows with your usual database tooling if size matters.
