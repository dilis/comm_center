"""A ``ChannelProvider`` for an Android phone running SMS Gateway for Android (local server mode).

The phone serves an HTTP API on the local network (port 8080, HTTP Basic auth): ``POST /message``
hands it an SMS to send. A 2xx answer means the phone accepted the message into its own queue, not
that the carrier delivered it; delivery reports, and everything the phone receives, come back to the
API as signed webhooks (SPECS.md 4.7), not through this class.

We give the phone our message id as the gateway's own message id (``cc-<id>``), so that its
delivery events can be matched to the message, and so a retry after a lost answer is recognised by
the phone instead of sending the SMS twice.

Inbound is not polled here: the app's ``GET /inbox`` returns only a preview of each message and has
no way to mark one as handled, so reading it could store truncated text or duplicates. So
``poll_inbound`` only checks that the phone is reachable, which is what lets the worker flag the
device as ``error`` when it is not.
"""

import logging
from urllib.parse import urlsplit

import httpx

from comm_center_worker.provider import InboundSms, PermanentSendError, ProviderError

log = logging.getLogger(__name__)

# Keep in step with ``app.dispatch.GATEWAY_ID_PREFIX`` in the API, which reads it back.
GATEWAY_ID_PREFIX = "cc-"


class AndroidGatewayProvider:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if urlsplit(base_url).scheme not in ("http", "https"):
            raise ValueError(
                f"the phone's address must start with http:// or https://: {base_url!r}"
            )
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(username, password),
            timeout=timeout,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Only the exception text: it names the problem, never the request body or password.
            raise ProviderError(f"phone unreachable: {exc}") from exc

    def send(self, phone_number: str, content: str, message_id: int | None = None) -> None:
        body: dict = {"textMessage": {"text": content}, "phoneNumbers": [phone_number]}
        if message_id is not None:
            body["id"] = f"{GATEWAY_ID_PREFIX}{message_id}"
        response = self._request("POST", "/message", json=body)
        status = response.status_code
        if response.is_success:
            return
        if status == 409 and message_id is not None:
            # The phone already has this id: an earlier try (whose answer we lost) got through.
            # Sending again would text the person twice. (Assumed behaviour: confirm on the phone.)
            log.warning("the phone already has message %s; not sending it twice", message_id)
            return
        if status in (400, 422):
            raise PermanentSendError(f"the phone rejected the message (HTTP {status})")
        if status in (401, 403):
            raise ProviderError(f"the phone refused the credentials (HTTP {status})")
        raise ProviderError(f"the phone answered HTTP {status}")

    def poll_inbound(self) -> list[InboundSms]:
        response = self._request("GET", "/inbox", params={"type": "SMS", "limit": 1})
        if response.status_code in (401, 403):
            raise ProviderError(f"the phone refused the credentials (HTTP {response.status_code})")
        return []  # any other answer means the phone is up; inbound arrives by webhook

    def acknowledge(self, sms: InboundSms) -> None:
        """Nothing to forget: no inbound message is ever returned."""

    def close(self) -> None:
        self._client.close()


def from_config(
    base_url: str,
    username: str,
    password: str,
    *,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> AndroidGatewayProvider:
    """Build the provider from this worker's own settings (the phone's address and its login, which
    never leave this machine). Raises ``ValueError`` naming what is missing."""
    for name, value in (
        ("WORKER_ANDROID_BASE_URL", base_url),
        ("WORKER_ANDROID_USERNAME", username),
        ("WORKER_ANDROID_PASSWORD", password),
    ):
        if not value:
            raise ValueError(f"the android provider needs {name}")
    return AndroidGatewayProvider(base_url, username, password, timeout=timeout, transport=transport)
