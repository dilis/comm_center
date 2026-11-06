# Deployment and bootstrap

Three ways to run Comm Center. Run the commands from the repo root. Each mode was brought up from scratch and checked end to end (service health, the web page and the migration state). Two supporting items were not run: the `uv sync --no-dev` step in mode 2 and the SQL for a native MySQL install.

| Mode | Use it for | MySQL | API and web |
|---|---|---|---|
| [1. Separate containers](#1-separate-containers) | Hosts where you manage containers yourself (no compose) | container | containers |
| [2. Separate processes](#2-separate-processes) | Development, or a host that runs processes directly | container or native install | native processes |
| [3. Docker Compose](#3-docker-compose) | The simplest full deployment | container | containers |

> **Current scope:** the API exposes only `GET /health` and the web app is a placeholder page. Authentication, the first-admin command and the business endpoints arrive in later phases, so a fresh deployment has the schema and seed data but no human user and no secrets such as a JWT key. This guide gains those steps then.

## Environment variables

The same few variables drive every mode.

| Variable | Used by | Meaning | Default (dev only) |
|---|---|---|---|
| `MYSQL_ROOT_PASSWORD` | MySQL container | Root password, set on first start only. The app never uses it. | `root` |
| `MYSQL_DATABASE` | MySQL container | Database created on first start | `comm_center` |
| `MYSQL_USER` | MySQL container | Application user, granted rights on that database only | `comm_center` |
| `MYSQL_PASSWORD` | MySQL container | Application user's password | `comm_center` |
| `DATABASE_URL` | API | SQLAlchemy URL, `mysql+pymysql://USER:PASSWORD@HOST:PORT/DATABASE` | the dev values on `127.0.0.1:3307` |
| `DB_PORT`, `API_PORT`, `WEB_PORT` | Compose only | Host ports for the three services | `3307`, `8000`, `8080` |

Rules:
- `DATABASE_URL` must use the same user, password and database as the `MYSQL_*` values. In compose the API's URL is built from them, so you set them once.
- Use **URL-safe passwords** (letters and digits). They are embedded in `DATABASE_URL`, and characters such as `@` or `/` would need percent-encoding.
- MySQL reads `MYSQL_*` only when it creates an empty data directory. Changing them later does not change an existing database.
- The web image is a static build and reads no environment variables.
- For real deployments, change every default password, and do not publish the database port to the network (remove the `db` `ports:` entry in compose, or bind it to `127.0.0.1`).

### Which file holds what

| File | Used in mode | Contents |
|---|---|---|
| `.env` (copy of `.env.example`) | 2 and 3 | All variables above. Compose reads it automatically; the natively run API reads `DATABASE_URL` from it. |
| `deploy/db.env` (copy of `deploy/db.env.example`) | 1 | The four `MYSQL_*` variables for the database container |
| `deploy/api.env` (copy of `deploy/api.env.example`) | 1 | `DATABASE_URL` for the API container, with the database container's name as host |

`.env` and `deploy/*.env` are git-ignored; only the `*.example` files are committed.

## Initial migrations

The schema and starting data are created by two Alembic migrations in `apps/api/alembic/versions/`:

| Revision | What it does |
|---|---|
| `0001` | Creates all tables, indexes, CHECK constraints, generated-column unique indexes, and a trigger that makes `users.is_system` and `users.agent_direction` immutable |
| `0002` | Seeds the `system` and `notification` agents (users and contacts), the 16 permissions, the 9 building-block groups, the 4 roles (`admin`, `operator`, `agent`, `auditor`) and the precomputed group closure |

What to know:
- **No human user is seeded.** There is no default credential. The first admin is created by a bootstrap command that arrives with authentication.
- **Containers migrate themselves.** The API image runs `alembic upgrade head` before it starts serving. It is idempotent, so restarts are safe.
- **Native processes migrate explicitly:** `pnpm db:migrate`.
- **The trigger needs a server setting.** `0001` creates a trigger, and MySQL only lets a non-SUPER user do that when `log_bin_trust_function_creators=1`. The compose file and the commands below already pass `--log-bin-trust-function-creators=1`. A MySQL you provide yourself needs it too, for example `SET GLOBAL log_bin_trust_function_creators = 1;` or the same line under `[mysqld]` in its config. Without it, migration `0001` fails with error 1419.
- **A failed migration leaves partial tables.** MySQL DDL is not transactional. If a migration fails midway, drop and recreate the database before retrying (the data is only what the migrations created).
- **Check the state** with `alembic current` (see each mode). A healthy database reports `0002 (head)`.

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
docker run -d --name cc-web --network cc-net -p 8080:80 comm-center-web
```

Add `-p 127.0.0.1:3306:3306` to step 4 only if you need to reach the database from the host.

Verify:
```sh
docker ps --format 'table {{.Names}}\t{{.Status}}'      # all three should say (healthy)
curl http://127.0.0.1:8000/health                        # {"status":"ok"}
curl -s http://127.0.0.1:8080/ | grep '<title>'          # <title>Comm Center</title>
docker run --rm --network cc-net --env-file deploy/api.env comm-center-api \
  /opt/venv/bin/alembic current                          # 0002 (head)
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
pnpm db:migrate                               # applies 0001 and 0002

# API (keep it running; add --reload only for development)
cd apps/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Web: build once, then serve apps/web/dist (second terminal, from the repo root)
pnpm --filter @comm-center/web build
pnpm --filter @comm-center/web exec vite preview --host 127.0.0.1 --port 8080
```

`vite preview` is for checking the build. In production serve `apps/web/dist` with a real web server; `apps/web/nginx.conf` shows the one rule needed (fall back to `index.html` for unknown paths). For long-running use, put both processes under a supervisor such as systemd. For development, `pnpm dev` starts both with hot reload instead.

Verify:
```sh
curl http://127.0.0.1:8000/health                      # {"status":"ok"}
curl -s http://127.0.0.1:8080/ | grep '<title>'        # <title>Comm Center</title>
(cd apps/api && uv run alembic current)                # 0002 (head)
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
docker compose exec api /opt/venv/bin/alembic current  # 0002 (head)
```

Run migrations by hand:
```sh
docker compose --profile app run --rm api /opt/venv/bin/alembic upgrade head
```

Update to a new version: `git pull`, then `docker compose --profile app up -d --build --wait`. The API container migrates the database before it serves.

Stop: `docker compose --profile app down` keeps the data. `docker compose --profile app down -v` also deletes the database volume.

To run several copies side by side (for example a test copy), give each its own project name, env file and ports:
`docker compose -p cc-test --env-file other.env --profile app up -d --wait`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| API container exits; log shows `(1419, 'You do not have the SUPER privilege …')` | The MySQL server lacks `log_bin_trust_function_creators=1`. Start it with `--log-bin-trust-function-creators=1` (or `SET GLOBAL`), drop and recreate the database, and start the API again. |
| `Table … already exists` on a retry, or `access_group` missing | A previous migration failed midway. Drop and recreate the database (or `down -v` in compose), then retry. |
| API cannot connect (`Can't connect to MySQL server`, `Access denied`) | `DATABASE_URL` host, port, user, password or database does not match the database. In containers the host is the database container's name, not `127.0.0.1`. |
| Changed `MYSQL_PASSWORD` and the app cannot log in | MySQL only reads `MYSQL_*` on first start. Recreate the volume, or change the password inside MySQL. |
| `pnpm: command not found` | Run `corepack enable` once. |
| A port is already in use | Set another `DB_PORT`, `API_PORT` or `WEB_PORT` in `.env` (compose), or change the `-p` mapping. |
