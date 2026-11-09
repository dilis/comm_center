"""An in-memory stand-in for the API's worker endpoints, for testing the worker's loops alone."""

import json
import threading

import httpx


class FakeServer:
    def __init__(self):
        self.lock = threading.Lock()
        self.queue: list[dict] = []  # messages to hand out: {"id", "phone_number", "content"}
        self.devices: list[dict] = []  # what the session returns
        self.results: list[tuple] = []  # (message_id, status, error)
        self.extended: list[int] = []
        self.inbound: list[dict] = []
        self.statuses: list[tuple] = []  # (device_id, status, error)
        self.sessions: list[dict] = []
        self.seen_refs: set[str] = set()
        self.fail: dict[str, list[int]] = {}  # path -> status codes to answer, in order

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            path = request.url.path
            body = json.loads(request.content) if request.content else {}
            if self.fail.get(path):
                return httpx.Response(self.fail[path].pop(0), json={"detail": "scripted failure"})
            if path == "/worker/token":
                return httpx.Response(
                    200, json={"access_token": "t", "token_type": "bearer", "expires_in": 900}
                )
            if path == "/worker/session":
                self.sessions.append(body)
                return httpx.Response(
                    200, json={"worker_id": 1, "protocol_version": 1, "devices": self.devices}
                )
            if path == "/worker/claim":
                message = self.queue.pop(0) if self.queue else None
                return httpx.Response(200, json={"message": message, "lease_seconds": 120})
            if path.endswith("/extend"):
                self.extended.append(int(path.split("/")[3]))
                return httpx.Response(200, json={"lease_seconds": 120})
            if path.endswith("/result"):
                self.results.append((int(path.split("/")[3]), body["status"], body.get("error")))
                return httpx.Response(204)
            if path == "/worker/inbound":
                duplicate = body["ref"] in self.seen_refs
                self.seen_refs.add(body["ref"])
                if not duplicate:
                    self.inbound.append(body)
                return httpx.Response(
                    200, json={"stored": not duplicate, "duplicate": duplicate, "message_id": 1}
                )
            if path.endswith("/status"):
                self.statuses.append((int(path.split("/")[3]), body["status"], body.get("error")))
                return httpx.Response(204)
        return httpx.Response(404)
