# Notifier (`apps/notifier`)

Design and rationale: `SPECS.md` Phase 9 notes. Rules a session must not break:

- **The API never sends a push and never holds the VAPID private key**; it queues, this program sends. Run exactly one instance.
- **Only two tables are shared with the API:** `push_subscription` and `push_outbox`, written down in `contract/outbox.sql` (the API's `tests/test_notifier_contract.py` fails on drift; `tests/test_isolation.py` fails if this imports the API's code or an ORM). Plain SQL on `pymysql`.
- **Locking:** find rows with a plain read and lock by primary key (`SKIP LOCKED`), on both sides. Range locks deadlock.
- **Aggregation:** at most one `pending` row per subscription (generated column `pending_key`, unique); later messages join it. A `sending` row (with a lease) is never joined.
- **Outcomes:** success deletes the row; 404/410 deletes the subscription; another 4xx drops the row and keeps the subscription (`PushRejected`); temporary failures (`PushError.retryable`) retry with doubling delay up to `PUSH_MAX_ATTEMPTS`. No transaction stays open while a push service answers.
- **Payloads never contain SMS text.**
- **Polling:** every second (MySQL has no `LISTEN`). Idles unless the private key and subject are set (`python -m app.cli vapid-keys` in the API makes the pair).
- **Tests:** `pnpm --filter @comm-center/notifier test` (`test:unit` needs no MySQL, the rest needs `pnpm db:up`; own `comm_center_notifier_test` database built from the contract file). Tests replace `sender.send_push` and pass the clock to `runner.run_once`, so none reaches a push service.
