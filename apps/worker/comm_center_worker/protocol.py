"""What the worker and the API agree on. Bump together with ``app.routers.worker`` when the worker
endpoints change in a way an older worker cannot follow."""

PROTOCOL_VERSION = 1
WORKER_VERSION = "0.1.0"
