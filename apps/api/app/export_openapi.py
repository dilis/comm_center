"""Print the API's OpenAPI document (``python -m app.export_openapi``): the web client's input."""

import json

from app.main import app


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    print(render(), end="")
