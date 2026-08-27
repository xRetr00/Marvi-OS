"""Routes whose body a caller can actually send.

Both of these answered 422 to every correct request, for months, because their
Pydantic model was declared inside `create_app` while the module is
`from __future__ import annotations`. FastAPI could not resolve the name, so it
read the parameter as a query string and demanded it there.

Nothing caught it because nothing posted to either route in a test -- the two
busiest paths in the Gateway, and the only two without one.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from marvi_gateway.app import create_app


def test_llm_accepts_a_json_body() -> None:
    """The seam every surface reaches a model through."""
    with TestClient(create_app()) as client:
        response = client.post("/llm", json={"messages": [{"role": "user", "content": "hi"}]})
    # Not 422: whether a provider is configured is a different question, and one
    # this endpoint answers inside the stream rather than in the status.
    assert response.status_code == 200, response.text


def test_transcript_accepts_a_json_body() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/voice/transcript", json={"heard": "hello", "spoken": ""})
    assert response.status_code == 200, response.text
    assert response.json()["assistant"]["heard"] == "hello"
