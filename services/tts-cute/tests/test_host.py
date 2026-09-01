import pytest
from marvi_tts_cute import host


def test_catalog_voice_resolves_to_upstream_reference(tmp_path, monkeypatch) -> None:
    reference = tmp_path / "share" / "cutetts" / "default_reference.wav"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"RIFF")
    monkeypatch.setattr(host.sysconfig, "get_path", lambda name: str(tmp_path))

    assert host._reference_voice("cute-reference") == reference


def test_unknown_cute_voice_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown CuteTTS voice"):
        host._reference_voice("cute-default")


def test_missing_reference_fails_before_synthesis(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(host.sysconfig, "get_path", lambda name: str(tmp_path))

    with pytest.raises(FileNotFoundError, match="reference voice is missing"):
        host._reference_voice("cute-reference")
