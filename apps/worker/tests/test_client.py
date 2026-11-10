"""The worker's HTTP client: sign-in, token reuse, and how API failures are told apart."""

from datetime import datetime

import httpx
import pytest

from comm_center_worker.client import (
    ApiClient,
    ApiConflict,
    ApiError,
    ApiUnavailable,
    ClaimedMessage,
)
from comm_center_worker.provider import InboundSms


class FakeApi:
    """A scripted API: ``routes`` maps (method, path) to a response or a list of them."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.tokens_issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        self.calls.append((key, request.headers.get("authorization")))
        if key == ("POST", "/worker/token"):
            self.tokens_issued += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok{self.tokens_issued}",
                    "token_type": "bearer",
                    "expires_in": 900,
                },
            )
        response = self.routes[key]
        if isinstance(response, list):
            response = response.pop(0)
        return response(request) if callable(response) else response


def make(api: FakeApi, clock=lambda: 0.0) -> ApiClient:
    http = httpx.Client(base_url="http://api", transport=httpx.MockTransport(api))
    return ApiClient(http, "w1", "secret", clock=clock)


def test_it_signs_in_once_and_reuses_the_token():
    api = FakeApi({("POST", "/worker/session"): httpx.Response(200, json={"devices": []})})
    client = make(api)
    client.session("0.1", "inst")
    client.session("0.1", "inst")
    assert api.tokens_issued == 1
    assert {auth for (_, auth) in api.calls if auth} == {"Bearer tok1"}


def test_it_signs_in_again_before_the_token_expires():
    now = {"t": 0.0}
    api = FakeApi({("POST", "/worker/session"): httpx.Response(200, json={"devices": []})})
    client = make(api, clock=lambda: now["t"])
    client.session("0.1", "inst")
    now["t"] = 900 - 10  # inside the safety margin
    client.session("0.1", "inst")
    assert api.tokens_issued == 2


def test_a_rejected_token_triggers_one_new_sign_in_and_a_retry():
    api = FakeApi(
        {
            ("POST", "/worker/session"): [
                httpx.Response(401),
                httpx.Response(200, json={"devices": []}),
            ]
        }
    )
    assert make(api).session("0.1", "inst") == {"devices": []}
    assert api.tokens_issued == 2


def test_bad_credentials_are_an_error_not_a_loop():
    def deny(request):
        return httpx.Response(401, json={"detail": "invalid credentials"})

    client = ApiClient(
        httpx.Client(base_url="http://api", transport=httpx.MockTransport(deny)), "w", "x"
    )
    with pytest.raises(ApiError, match="invalid credentials"):
        client.session("0.1", "inst")


def test_network_failures_and_server_errors_mean_the_api_is_unavailable():
    def down(request):
        raise httpx.ConnectError("refused")

    client = ApiClient(
        httpx.Client(base_url="http://api", transport=httpx.MockTransport(down)), "w", "x"
    )
    with pytest.raises(ApiUnavailable):
        client.session("0.1", "inst")
    api = FakeApi({("POST", "/worker/session"): httpx.Response(503)})
    with pytest.raises(ApiUnavailable):
        make(api).session("0.1", "inst")


def test_a_refused_request_is_an_api_error_with_the_servers_reason():
    api = FakeApi(
        {
            ("POST", "/worker/session"): httpx.Response(
                409, json={"detail": "unsupported protocol version 9"}
            )
        }
    )
    with pytest.raises(ApiError, match="protocol"):
        make(api).session("0.1", "inst")


def test_claim_returns_the_message_and_its_lease():
    body = {
        "message": {"id": 7, "phone_number": "+639171234567", "content": "hi"},
        "lease_seconds": 120,
    }
    api = FakeApi({("POST", "/worker/claim"): httpx.Response(200, json=body)})
    assert make(api).claim(3) == ClaimedMessage(7, "+639171234567", "hi", 120)


def test_claim_of_an_empty_queue_is_none():
    api = FakeApi(
        {
            ("POST", "/worker/claim"): httpx.Response(
                200, json={"message": None, "lease_seconds": 120}
            )
        }
    )
    assert make(api).claim(3) is None


def test_a_result_the_api_will_not_take_is_a_conflict():
    api = FakeApi(
        {("POST", "/worker/messages/7/result"): httpx.Response(409, json={"detail": "no lease"})}
    )
    with pytest.raises(ApiConflict):
        make(api).result(7, "sent")


def test_inbound_sends_the_message_and_reports_the_outcome():
    seen = []

    def respond(request):
        seen.append(request.read())
        return httpx.Response(200, json={"stored": True, "duplicate": False, "message_id": 5})

    api = FakeApi({("POST", "/worker/inbound"): respond})
    sms = InboundSms("ref1", "+639171234567", "hello", datetime(2026, 1, 2, 3, 4, 5))
    out = make(api).inbound(3, sms)
    assert out.stored and not out.duplicate
    assert b'"ref":"ref1"' in seen[0] and b"2026-01-02T03:04:05" in seen[0]


def test_extend_and_device_status_are_plain_calls():
    api = FakeApi(
        {
            ("POST", "/worker/messages/7/extend"): httpx.Response(200, json={"lease_seconds": 120}),
            ("POST", "/worker/devices/3/status"): httpx.Response(204),
        }
    )
    client = make(api)
    client.extend(7)
    client.device_status(3, "error", "boom")
    assert [k for (k, _) in api.calls if k[1] != "/worker/token"] == [
        ("POST", "/worker/messages/7/extend"),
        ("POST", "/worker/devices/3/status"),
    ]
