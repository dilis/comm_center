"""The client against the worker API contract (``contract/worker-api.json``, exported by the API).

Every request the client makes must match an operation in the contract, with a body that has only
fields the contract describes (and all it requires). Every response the client reads is built from
the contract, so a field the API dropped or renamed fails here, not in production.
"""

import json
import re
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator

from comm_center_worker.client import ApiClient
from comm_center_worker.provider import InboundSms

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contract" / "worker-api.json").read_text()
)
COMPONENTS = CONTRACT["components"]


def resolve(schema: dict) -> dict:
    while "$ref" in schema:
        schema = COMPONENTS["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def sample(schema: dict):
    """A minimal valid value for a schema."""
    schema = resolve(schema)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return sample(options[0])
    kind = schema.get("type")
    if kind == "object":
        return {name: sample(sub) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [sample(schema["items"])]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "string":
        return "2026-01-01T00:00:00" if schema.get("format") == "date-time" else "x"
    return None


def operation(method: str, path: str):
    for template, item in CONTRACT["paths"].items():
        if re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path) and method.lower() in item:
            return item[method.lower()]
    raise AssertionError(f"{method} {path} is not in the worker API contract")


def check_body(op: dict, body):
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    validator = Draft202012Validator({"$ref": schema["$ref"], "components": COMPONENTS})
    validator.validate(body)  # types and required fields
    unknown = set(body) - set(resolve(schema)["properties"])
    assert not unknown, f"the client sends fields the contract does not know: {sorted(unknown)}"


class ContractServer:
    def __init__(self, overrides=None):
        self.seen = []
        self.overrides = overrides or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        op = operation(request.method, request.url.path)
        body = json.loads(request.content) if request.content else None
        if "requestBody" in op:
            check_body(op, body)
        self.seen.append((request.method, request.url.path, body))
        if request.url.path in self.overrides:
            return httpx.Response(200, json=self.overrides[request.url.path])
        success = next(code for code in op["responses"] if code.startswith("2"))
        content = op["responses"][success].get("content")
        if not content:
            return httpx.Response(int(success))
        return httpx.Response(int(success), json=sample(content["application/json"]["schema"]))


def client(server: ContractServer) -> ApiClient:
    http = httpx.Client(base_url="http://api", transport=httpx.MockTransport(server))
    return ApiClient(http, "w1", "secret")


def test_the_contract_describes_the_operations_the_client_uses():
    paths = set(CONTRACT["paths"])
    assert {
        "/worker/token",
        "/worker/session",
        "/worker/claim",
        "/worker/messages/{message_id}/result",
        "/worker/messages/{message_id}/extend",
        "/worker/inbound",
        "/worker/devices/{device_id}/status",
    } <= paths


def test_every_call_matches_the_contract_in_both_directions():
    server = ContractServer()
    api = client(server)
    assert api.session("0.1.0", ["fake"], "instance-1")["devices"] is not None
    assert api.claim(3, 5) is not None  # a message, with its lease
    api.extend(7)
    api.result(7, "sent")
    api.result(7, "failed", "no signal")
    when = __import__("datetime").datetime(2026, 1, 2, 3, 4, 5)
    assert api.inbound(3, InboundSms("ref", "+639171234567", "hi", when)).stored in (True, False)
    api.device_status(3, "error", "boom")
    paths = {path for _, path, _ in server.seen}
    assert "/worker/token" in paths and len(server.seen) >= 8


def test_an_empty_queue_answer_is_understood():
    server = ContractServer({"/worker/claim": {"message": None, "lease_seconds": 120}})
    assert client(server).claim(3) is None


@pytest.mark.parametrize("field", ["devices"])
def test_the_session_answer_the_supervisor_reads_has_its_fields(field):
    props = resolve({"$ref": "#/components/schemas/SessionOut"})["properties"]
    assert field in props
    device = resolve({"$ref": "#/components/schemas/SessionDevice"})["properties"]
    assert {"id", "name", "provider", "config"} <= set(device)  # what make_worker reads


def test_the_protocol_version_the_client_speaks_is_accepted_by_the_contract():
    from comm_center_worker.protocol import PROTOCOL_VERSION

    body = {
        "version": "1",
        "protocol_version": PROTOCOL_VERSION,
        "providers": [],
        "instance_id": "i",
    }
    check_body(operation("POST", "/worker/session"), body)
