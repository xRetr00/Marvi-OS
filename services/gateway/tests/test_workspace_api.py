"""The settings page behind the file tools.

Every field is optional and `None` means "leave it alone", so the page can send
one switch rather than the whole policy back. Two panels editing different
parts of it then cannot overwrite each other, which is the failure this shape
exists to prevent.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.filepolicy import BLACKLIST_SETTING, ROOT_SETTING


def test_it_reports_the_policy_and_the_rules_that_cannot_be_removed() -> None:
    with TestClient(create_app()) as client:
        page = client.get("/workspace").json()

    assert page["read_scope"] in page["scopes"]
    assert page["builtin"], "the built-in rules must be visible"
    assert "file_edit" in page["tools"]["write"]
    assert "file_read" in page["tools"]["read"]


def test_setting_one_switch_leaves_the_others_alone(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.setenv(BLACKLIST_SETTING, "*.key")
    with TestClient(create_app()) as client:
        page = client.put("/workspace", json={"read_scope": "general"}).json()

    assert page["read_scope"] == "general"
    assert page["blacklist"] == ["*.key"]
    assert page["root"] == str(tmp_path)


def test_a_root_that_does_not_exist_is_refused(tmp_path) -> None:
    """Accepting it means every tool refuses while the page says configured."""
    with TestClient(create_app()) as client:
        response = client.put("/workspace", json={"root": str(tmp_path / "nowhere")})

    assert response.status_code == 400
    assert "not a folder" in response.text


def test_an_unknown_scope_is_refused() -> None:
    with TestClient(create_app()) as client:
        assert client.put("/workspace", json={"write_scope": "everywhere"}).status_code == 400


def test_the_blacklist_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    with TestClient(create_app()) as client:
        page = client.put("/workspace", json={"blacklist": ["*.pem", " ", str(tmp_path)]}).json()

    # The blank entry is dropped rather than stored as a rule matching nothing.
    assert page["blacklist"] == ["*.pem", str(tmp_path)]
