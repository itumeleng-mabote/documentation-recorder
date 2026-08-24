import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from docrecorder.vision import (
    OllamaUnreachable,
    chat_json,
    chat_vision,
    identify_clicks,
    ollama_host,
    parse_target_json,
)


def test_parse_target_json_from_fences():
    text = 'Here you go:\n```json\n{"label": "Save", "kind": "button"}\n```\n'
    assert parse_target_json(text) == {"label": "Save", "kind": "button"}


def test_parse_target_json_strips_think_and_unknown_kind():
    text = '<think>looking</think> {"label": "Search", "kind": "widget"}'
    assert parse_target_json(text) == {"label": "Search", "kind": "unknown"}


def test_parse_target_json_rejects_invalid():
    assert parse_target_json("no json here") is None


def test_identify_clicks_sets_target(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.jpg").write_bytes(b"fake-jpeg")
    session = {
        "steps": [
            {"type": "click", "screenshot_crop": "crops/step-01.jpg"},
            {"type": "type", "text": "hello"},
        ]
    }

    def fake_chat(_image_bytes: bytes) -> str:
        return '{"label": "Save", "kind": "button"}'

    warning = identify_clicks(session, tmp_path, chat=fake_chat)
    assert warning is None
    assert session["steps"][0]["target"] == {"label": "Save", "kind": "button"}
    assert "target" not in session["steps"][1]


def test_identify_clicks_skips_empty_label(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.jpg").write_bytes(b"fake-jpeg")
    session = {"steps": [{"type": "click", "screenshot_crop": "crops/step-01.jpg"}]}

    warning = identify_clicks(
        session,
        tmp_path,
        chat=lambda _data: '{"label": "", "kind": "unknown"}',
    )
    assert warning is None
    assert "target" not in session["steps"][0]


def test_identify_clicks_unreachable_skips_remaining(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.jpg").write_bytes(b"one")
    (crops / "step-02.jpg").write_bytes(b"two")
    session = {
        "steps": [
            {"type": "click", "screenshot_crop": "crops/step-01.jpg"},
            {"type": "click", "screenshot_crop": "crops/step-02.jpg"},
        ]
    }
    calls = {"n": 0}

    def fake_chat(_image_bytes: bytes) -> str:
        calls["n"] += 1
        raise OllamaUnreachable("down")

    warning = identify_clicks(session, tmp_path, chat=fake_chat)
    assert warning == "down"
    assert calls["n"] == 1
    assert "target" not in session["steps"][0]
    assert "target" not in session["steps"][1]


def test_ollama_host_adds_scheme(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert ollama_host() == "http://127.0.0.1:11434"


@patch("docrecorder.vision.urllib.request.urlopen")
def test_chat_vision_posts_image(mock_urlopen):
    payload = {"message": {"content": '{"label": "OK", "kind": "button"}'}}
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    mock_urlopen.return_value = response

    text = chat_vision(b"jpeg-bytes", model="qwen3.5:4b-mlx", host="http://127.0.0.1:11434")
    assert json.loads(text)["label"] == "OK"
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "qwen3.5:4b-mlx"
    assert body["think"] is False
    assert body["messages"][0]["images"]


@patch("docrecorder.vision.urllib.request.urlopen")
def test_chat_vision_connection_error(mock_urlopen):
    mock_urlopen.side_effect = URLError("connection refused")
    try:
        chat_vision(b"jpeg-bytes")
    except OllamaUnreachable as exc:
        assert "Ollama is not running" in str(exc)
        return
    raise AssertionError("expected OllamaUnreachable")


@patch("docrecorder.vision.urllib.request.urlopen")
def test_chat_json_posts_text(mock_urlopen):
    payload = {"message": {"content": '{"steps": []}'}}
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__.return_value = response
    mock_urlopen.return_value = response
    schema = {"type": "object"}

    text = chat_json("rewrite these steps", schema=schema, timeout=90)
    assert text == '{"steps": []}'
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["messages"][0]["content"] == "rewrite these steps"
    assert "images" not in body["messages"][0]
    assert body["format"] == schema
    assert body["think"] is False
    assert mock_urlopen.call_args.kwargs["timeout"] == 90
