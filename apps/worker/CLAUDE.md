# Worker (`apps/worker`)

Design and rationale: `SPECS.md` section 4.7 and the Phase 8 notes. Rules a session must not break:

- **No database, no API imports.** The worker talks to the API only over HTTP (`/worker/*`) and must not depend on the API, a database driver or `sqlalchemy` (`tests/test_isolation.py` enforces it). It signs in as the device's inbound agent `gsm-<name>`; token kind `worker` is never valid on user endpoints.
- **The only shared artifact is `contract/worker-api.json`**, exported by the API: after changing a `/worker/*` route run `pnpm --filter @comm-center/api gen:worker-contract` (the API's `tests/test_worker_contract.py` fails if it is stale; `tests/test_contract.py` here checks the client against it).
- **The API owns the queue and does not know the device kind.** The claim (`SELECT … FOR UPDATE SKIP LOCKED`) and the lease (`message_lease`) live in the API. The provider is chosen here (`WORKER_PROVIDER`: `fake` or `android`; Android address and login from `WORKER_ANDROID_*`, never from the API) behind `ChannelProvider` (`comm_center_worker/provider.py`).
- **Never re-send on doubt.** An expired lease or a worker restart (new `instance_id`) fails the message with "delivery unknown"; never retry it automatically.
- **Gateway message id:** `cc-<message id>` for the first send, `cc-<message id>-<n>` for a person's n-th retry. The phone refuses an id it has seen (409), so a retry needs a new one; the worker's own retries inside one claim keep the id.
- **Inbound:** `POST /worker/inbound` is idempotent per `(device, ref)`; acknowledge on the device only after the API stored it, so a provider's `ref` must identify one message for good.
- **Send spacing** (`WORKER_SEND_INTERVAL_SECONDS`) is enforced in `DeviceWorker` before claiming, never by the API.
- **Tests:** `pnpm --filter @comm-center/worker test` (no MySQL) runs the loops against the in-memory fake API (`tests/fake_server.py`). The API's `tests/worker/` run this worker's real code against the real API with real commits and need MySQL.
