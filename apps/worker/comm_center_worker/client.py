"""The worker's only way to the API: HTTP calls with a worker token (SPECS.md 4.7).

Failures are told apart so the loops can react correctly: ``ApiUnavailable`` (network, 5xx: try
again later), ``ApiConflict`` (the API will not take this report, e.g. the lease is gone) and
``ApiError`` (the request itself was refused, e.g. bad credentials or an unsupported protocol).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC

import httpx

from comm_center_worker.provider import InboundSms

log = logging.getLogger(__name__)
TOKEN_MARGIN_SECONDS = 30  # sign in again this long before the token runs out


class ApiError(Exception):
    """The API refused the request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ApiConflict(ApiError):
    """409: the API will not accept this (a lease that is gone, a message that is not ours)."""


class ApiUnavailable(Exception):
    """The API could not be reached or failed (network error, 5xx). Worth trying again later."""


@dataclass(frozen=True)
class ClaimedMessage:
    id: int
    phone_number: str
    content: str
    lease_seconds: int


@dataclass(frozen=True)
class InboundResult:
    stored: bool
    duplicate: bool
    message_id: int | None


def _reason(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) else f"HTTP {response.status_code}"


class ApiClient:
    def __init__(
        self,
        http: httpx.Client,
        name: str,
        secret: str,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._name = name
        self._secret = secret
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0

    def close(self) -> None:
        self._http.close()

    # --- plumbing ---

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiUnavailable(f"API unreachable: {exc}") from exc

    def _sign_in(self) -> None:
        response = self._send(
            "POST", "/worker/token", json={"name": self._name, "secret": self._secret}
        )
        if response.status_code >= 500:
            raise ApiUnavailable(f"API failed to sign in: HTTP {response.status_code}")
        if response.status_code == 429:
            raise ApiUnavailable("too many failed sign-ins; waiting")
        if not response.is_success:
            raise ApiError(f"sign-in refused: {_reason(response)}", response.status_code)
        body = response.json()
        self._token = body["access_token"]
        self._expires_at = self._clock() + body["expires_in"] - TOKEN_MARGIN_SECONDS

    def _call(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 204), **kwargs):
        if self._token is None or self._clock() >= self._expires_at:
            self._sign_in()
        for attempt in (1, 2):
            response = self._send(
                method, path, headers={"Authorization": f"Bearer {self._token}"}, **kwargs
            )
            if response.status_code == 401 and attempt == 1:
                self._sign_in()  # the token was refused: get a new one, once
                continue
            break
        if response.status_code >= 500:
            raise ApiUnavailable(f"API error on {path}: HTTP {response.status_code}")
        if response.status_code == 409:
            raise ApiConflict(_reason(response), 409)
        if response.status_code not in ok:
            raise ApiError(f"{path} refused: {_reason(response)}", response.status_code)
        return response

    # --- the worker API ---

    def session(self, version: str, instance_id: str, protocol_version: int = 2) -> dict:
        response = self._call(
            "POST",
            "/worker/session",
            json={
                "version": version,
                "protocol_version": protocol_version,
                "instance_id": instance_id,
            },
        )
        return response.json()

    def claim(self, device_id: int, wait_seconds: float = 0) -> ClaimedMessage | None:
        response = self._call(
            "POST", "/worker/claim", json={"device_id": device_id, "wait_seconds": wait_seconds}
        )
        body = response.json()
        message = body["message"]
        if message is None:
            return None
        return ClaimedMessage(
            message["id"], message["phone_number"], message["content"], body["lease_seconds"]
        )

    def extend(self, message_id: int) -> None:
        self._call("POST", f"/worker/messages/{message_id}/extend")

    def result(self, message_id: int, status: str, error: str | None = None) -> None:
        self._call(
            "POST", f"/worker/messages/{message_id}/result", json={"status": status, "error": error}
        )

    def inbound(self, device_id: int, sms: InboundSms) -> InboundResult:
        received = sms.received_at
        if received.tzinfo is not None:
            received = received.astimezone(UTC).replace(tzinfo=None)
        response = self._call(
            "POST",
            "/worker/inbound",
            json={
                "device_id": device_id,
                "ref": sms.ref,
                "sender": sms.sender,
                "content": sms.content,
                "received_at": received.isoformat(),
            },
        )
        body = response.json()
        return InboundResult(body["stored"], body["duplicate"], body["message_id"])

    def device_status(self, device_id: int, status: str, error: str | None = None) -> None:
        self._call(
            "POST", f"/worker/devices/{device_id}/status", json={"status": status, "error": error}
        )
