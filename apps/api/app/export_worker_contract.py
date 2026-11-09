"""Print the part of the OpenAPI document that workers use (``python -m app.export_worker_contract``).

It is committed as ``apps/worker/contract/worker-api.json``. The worker never imports the API; this
file is the only thing the two share, and each side's tests check it: the API's that it is current,
the worker's that its client sends and reads what it describes.
"""

import json

from app.main import app

PREFIX = "/worker/"


def _refs(node, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def build() -> dict:
    full = app.openapi()
    paths = {p: v for p, v in full["paths"].items() if p.startswith(PREFIX)}
    needed: set[str] = set()
    _refs(paths, needed)
    schemas = full.get("components", {}).get("schemas", {})
    queue = list(needed)
    while queue:  # schemas that reference other schemas
        name = queue.pop()
        inner: set[str] = set()
        _refs(schemas[name], inner)
        for other in inner - needed:
            needed.add(other)
            queue.append(other)
    return {
        "openapi": full["openapi"],
        "info": {"title": "Comm Center worker API", "version": "1"},
        "paths": paths,
        "components": {"schemas": {n: schemas[n] for n in sorted(needed)}},
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    print(render(), end="")
