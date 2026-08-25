

# -- a standing choice that stopped standing ----------------------------------


def test_yolo_survives_a_restart(monkeypatch, tmp_path) -> None:
    """It lived only in memory, so every Gateway start put the mode quietly
    back to confirm.

    Believing you are in YOLO and not being is the mild version. The other
    direction — believing confirmations are on when they are not — is the one
    that matters, and both were possible.
    """
    from marvi_gateway.runtime import RuntimeStore

    saved: dict[str, str] = {}
    monkeypatch.setattr(
        "marvi_gateway.providers.config.update", lambda changes: saved.update(changes)
    )
    monkeypatch.delenv("MARVI_YOLO", raising=False)

    first = RuntimeStore(audit_path=tmp_path / "one.jsonl")
    assert first.assistant.yolo is False

    first.set_yolo(True)
    assert saved["MARVI_YOLO"] == "true"

    # A new Gateway, reading the setting the last one wrote.
    second = RuntimeStore(audit_path=tmp_path / "two.jsonl")
    assert second.assistant.yolo is True


def test_turning_yolo_off_is_remembered_too(monkeypatch, tmp_path) -> None:
    from marvi_gateway.runtime import RuntimeStore

    saved: dict[str, str] = {}
    monkeypatch.setattr(
        "marvi_gateway.providers.config.update", lambda changes: saved.update(changes)
    )
    monkeypatch.setenv("MARVI_YOLO", "true")

    store = RuntimeStore(audit_path=tmp_path / "a.jsonl")
    assert store.assistant.yolo is True

    store.set_yolo(False)

    # Cleared rather than written false: an empty value is how every other
    # setting in that file says "not set".
    assert saved["MARVI_YOLO"] == ""
    assert RuntimeStore(audit_path=tmp_path / "b.jsonl").assistant.yolo is False


def test_a_settings_file_that_cannot_be_written_does_not_break_the_mode(
    monkeypatch, tmp_path
) -> None:
    """The mode still changed. Failing the request over the bookkeeping would
    leave the user in neither state."""
    from marvi_gateway.runtime import RuntimeStore

    def refuse(_changes):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("marvi_gateway.providers.config.update", refuse)
    monkeypatch.delenv("MARVI_YOLO", raising=False)

    store = RuntimeStore(audit_path=tmp_path / "a.jsonl")
    assert store.set_yolo(True).yolo is True
