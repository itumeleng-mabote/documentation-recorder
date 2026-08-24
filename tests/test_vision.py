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
    (crops / "step-01.png").write_bytes(b"clean")
    (crops / "step-01-marked.png").write_bytes(b"marked")
    session = {
        "steps": [
            {
                "type": "click",
                "screenshot_crop": "crops/step-01.png",
                "screenshot_crop_marked": "crops/step-01-marked.png",
            },
            {"type": "type", "text": "hello"},
        ]
    }
    seen = {}

    def fake_chat(images: list[bytes], context: str | None) -> str:
        seen["images"] = images
        return '{"label": "Save", "kind": "button"}'

    warning = identify_clicks(session, tmp_path, chat=fake_chat)
    assert warning is None
    assert session["steps"][0]["target"] == {
        "label": "Save",
        "kind": "button",
        "source": "vision",
    }
    assert seen["images"] == [b"clean", b"marked"]
    assert "target" not in session["steps"][1]


def test_identify_clicks_skips_steps_labelled_by_accessibility(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.png").write_bytes(b"clean")
    session = {
        "steps": [
            {
                "type": "click",
                "screenshot_crop": "crops/step-01.png",
                "target": {"label": "annotated", "kind": "item", "source": "uia"},
            }
        ]
    }

    def fail(_images, _context):
        raise AssertionError("vision should not run for an already-labelled step")

    assert identify_clicks(session, tmp_path, chat=fail) is None
    assert session["steps"][0]["target"]["source"] == "uia"


def test_identify_clicks_passes_window_context(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.png").write_bytes(b"clean")
    session = {
        "app_name": "Explorer",
        "window_title": "recordings",
        "steps": [{"type": "click", "screenshot_crop": "crops/step-01.png"}],
    }
    seen = {}

    def fake_chat(_images, context: str | None) -> str:
        seen["context"] = context
        return '{"label": "annotated", "kind": "item"}'

    identify_clicks(session, tmp_path, chat=fake_chat)
    assert seen["context"] == "Explorer - recordings"


def test_identify_clicks_skips_empty_label(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.png").write_bytes(b"clean")
    session = {"steps": [{"type": "click", "screenshot_crop": "crops/step-01.png"}]}

    warning = identify_clicks(
        session,
        tmp_path,
        chat=lambda _images, _context: '{"label": "", "kind": "unknown"}',
    )
    assert warning is None
    assert "target" not in session["steps"][0]


def test_identify_clicks_unreachable_skips_remaining(tmp_path):
    crops = tmp_path / "crops"
    crops.mkdir()
    (crops / "step-01.png").write_bytes(b"one")
    (crops / "step-02.png").write_bytes(b"two")
    session = {
        "steps": [
            {"type": "click", "screenshot_crop": "crops/step-01.png"},
            {"type": "click", "screenshot_crop": "crops/step-02.png"},
        ]
    }
    calls = {"n": 0}

    def fake_chat(_images, _context) -> str:
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

    text = chat_vision(
        [b"clean-png", b"marked-png"],
        "Explorer - recordings",
        model="qwen3.5:4b",
        host="http://127.0.0.1:11434",
    )
    assert json.loads(text)["label"] == "OK"
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "qwen3.5:4b"
    assert body["think"] is False
    assert len(body["messages"][0]["images"]) == 2
    assert "Explorer - recordings" in body["messages"][0]["content"]


@patch("docrecorder.vision.urllib.request.urlopen")
def test_chat_vision_connection_error(mock_urlopen):
    mock_urlopen.side_effect = URLError("connection refused")
    try:
        chat_vision([b"png-bytes"])
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
