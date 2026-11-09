"""The Android provider (SMS Gateway for Android, local server) against a scripted phone."""

import base64
import json

import httpx
import pytest

from comm_center_worker.android import AndroidGatewayProvider, from_device
from comm_center_worker.provider import PermanentSendError, ProviderError


def make(handler, **kwargs) -> AndroidGatewayProvider:
    return AndroidGatewayProvider(
        "http://192.168.1.50:8080/",
        "user",
        "pass",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_send_posts_the_documented_body_with_basic_auth_and_our_message_id():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"id": "cc-42", "state": "Pending"})

    make(handler).send("+639171234567", "Hello", message_id=42)
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "http://192.168.1.50:8080/message"  # trailing slash tolerated
    assert request.headers["authorization"].startswith("Basic ")
    assert json.loads(request.content) == {
        "id": "cc-42",  # how the phone's delivery events are matched to this message
        "textMessage": {"text": "Hello"},
        "phoneNumbers": ["+639171234567"],
    }


def test_without_a_message_id_the_phone_picks_its_own():
    seen = []
    make(lambda r: seen.append(json.loads(r.content)) or httpx.Response(200)).send(
        "+639171234567", "x"
    )
    assert "id" not in seen[0]


def test_send_accepts_any_2xx_even_with_an_unexpected_body():
    make(lambda r: httpx.Response(200, text="ok")).send("+639171234567", "x", message_id=1)


def test_an_id_the_phone_already_has_means_an_earlier_try_got_through():
    """A retry after a lost answer must not send the SMS twice. Assumes the phone refuses a repeated
    message id with 409; the real phone's behaviour is to be confirmed."""
    make(lambda r: httpx.Response(409, json={"message": "duplicate id"})).send(
        "+639171234567", "x", message_id=7
    )


def test_a_409_without_an_id_of_ours_is_still_an_error():
    with pytest.raises(ProviderError):
        make(lambda r: httpx.Response(409)).send("+639171234567", "x")


@pytest.mark.parametrize("status", [400, 422])
def test_the_phone_rejecting_the_message_is_permanent(status):
    with pytest.raises(PermanentSendError):
        make(lambda r: httpx.Response(status, json={"message": "bad number"})).send(
            "+639171234567", "x", message_id=1
        )


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_other_http_errors_may_pass_so_they_are_retried(status):
    with pytest.raises(ProviderError) as exc_info:
        make(lambda r: httpx.Response(status)).send("+639171234567", "x", message_id=1)
    assert not isinstance(exc_info.value, PermanentSendError)
    assert str(status) in str(exc_info.value)


def test_an_unreachable_phone_is_a_retryable_provider_error():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    with pytest.raises(ProviderError, match="no route to host"):
        make(handler).send("+639171234567", "x", message_id=1)


def test_a_timeout_is_a_retryable_provider_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderError):
        make(handler).poll_inbound()


def test_error_messages_never_contain_the_password_or_message_text():
    with pytest.raises(ProviderError) as exc_info:
        make(lambda r: httpx.Response(500, text="secret body")).send(
            "+639171234567", "my secret", message_id=1
        )
    assert "pass" not in str(exc_info.value)
    assert "my secret" not in str(exc_info.value)


def test_poll_inbound_only_checks_the_phone_is_reachable():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[])

    assert make(handler).poll_inbound() == []
    assert seen  # it did contact the phone


def test_poll_inbound_treats_any_answer_but_bad_credentials_as_reachable():
    assert make(lambda r: httpx.Response(404)).poll_inbound() == []
    for status in (401, 403):
        with pytest.raises(ProviderError, match="credentials"):
            make(lambda r, s=status: httpx.Response(s)).poll_inbound()


def test_acknowledge_is_a_no_op_and_close_closes_the_client():
    provider = make(lambda r: httpx.Response(200))
    provider.acknowledge(None)  # type: ignore[arg-type]
    provider.close()
    with pytest.raises(RuntimeError):
        provider.send("+639171234567", "x", message_id=1)  # httpx refuses a closed client


def test_a_base_url_must_be_http_or_https():
    with pytest.raises(ValueError, match="http"):
        AndroidGatewayProvider("/dev/ttyUSB0", "u", "p")


# --- building it from a device's config and the worker's own environment ---

DEVICE = {
    "id": 3,
    "name": "phone1",
    "provider": "android",
    "config": {
        "base_url": "http://192.168.1.50:8080",
        "username_ref": "PHONE1_USERNAME",
        "password_ref": "PHONE1_PASSWORD",
    },
}


def test_the_login_is_read_from_the_workers_environment_not_from_the_config():
    env = {"PHONE1_USERNAME": "sms", "PHONE1_PASSWORD": "s3cret"}
    seen = []
    provider = from_device(
        DEVICE,
        env,
        timeout=5,
        transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200)),
    )
    provider.send("+639171234567", "x", message_id=1)
    expected = "Basic " + base64.b64encode(b"sms:s3cret").decode()
    assert seen[0].headers["authorization"] == expected
    assert "s3cret" not in json.dumps(DEVICE)  # nothing secret ever travels in the config


@pytest.mark.parametrize(
    "config, env, complaint",
    [
        ({}, {}, "base_url"),
        ({"base_url": "http://p"}, {}, "username_ref"),
        ({"base_url": "http://p", "username_ref": "U", "password_ref": "P"}, {}, "U"),
        ({"base_url": "http://p", "username_ref": "U", "password_ref": "P"}, {"U": "x"}, "P"),
        (
            {"base_url": "ftp://p", "username_ref": "U", "password_ref": "P"},
            {"U": "x", "P": "y"},
            "http",
        ),
    ],
)
def test_a_device_that_cannot_be_set_up_says_what_is_missing(config, env, complaint):
    with pytest.raises(ValueError, match=complaint):
        from_device({**DEVICE, "config": config}, env, timeout=5)
