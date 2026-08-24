from docrecorder.rewrite import (
    REWRITE_UNREACHABLE_MESSAGE,
    apply_captions,
    parse_rewrite_json,
    rewrite_captions,
    step_payload,
)
from docrecorder.vision import OllamaUnreachable


def test_parse_rewrite_json_from_fences():
    text = '```json\n{"steps": [{"index": 1, "caption": "Click **Save**."}]}\n```'
    assert parse_rewrite_json(text) == [{"index": 1, "caption": "Click **Save**."}]


def test_parse_rewrite_json_strips_think():
    text = '<think>planning</think> {"steps": [{"index": 2, "caption": "Type `hi`."}]}'
    assert parse_rewrite_json(text) == [{"index": 2, "caption": "Type `hi`."}]


def test_parse_rewrite_json_rejects_invalid():
    assert parse_rewrite_json("no json here") is None
    assert parse_rewrite_json('{"steps": []}') is None
    assert parse_rewrite_json('{"steps": [{"index": "x", "caption": "no"}]}') is None


def test_apply_captions_matches_index_and_ignores_extra():
    session = {
        "steps": [
            {"index": 1, "type": "click", "x": 1, "y": 2},
            {"index": 2, "type": "type", "text": "hi"},
        ]
    }
    apply_captions(
        session,
        [
            {"index": 1, "caption": "Open **Settings**."},
            {"index": 9, "caption": "Should be ignored."},
        ],
    )
    assert session["steps"][0]["caption"] == "Open **Settings**."
    assert "caption" not in session["steps"][1]


def test_rewrite_captions_sets_from_chat():
    session = {
        "app_name": "Mail",
        "window_title": "Inbox",
        "transcript": "Click send after typing the address.",
        "steps": [
            {"index": 1, "type": "click", "x": 10, "y": 20, "button": "left"},
            {"index": 2, "type": "type", "text": "a@b.com"},
        ],
    }

    def fake_chat(prompt: str) -> str:
        assert "Click send" in prompt
        assert "a@b.com" in prompt
        return (
            '{"steps": ['
            '{"index": 1, "caption": "Click **Send** to deliver the message."},'
            '{"index": 2, "caption": "Type `a@b.com` in the address field."}'
            "]}"
        )

    warning = rewrite_captions(session, chat=fake_chat)
    assert warning is None
    assert session["steps"][0]["caption"] == "Click **Send** to deliver the message."
    assert session["steps"][1]["caption"] == "Type `a@b.com` in the address field."


def test_rewrite_captions_unreachable():
    session = {"steps": [{"index": 1, "type": "click", "x": 1, "y": 2}]}

    def fake_chat(_prompt: str) -> str:
        raise OllamaUnreachable(REWRITE_UNREACHABLE_MESSAGE)

    warning = rewrite_captions(session, chat=fake_chat)
    assert warning == REWRITE_UNREACHABLE_MESSAGE
    assert "caption" not in session["steps"][0]


def test_step_payload_includes_hint_and_elapsed():
    session = {
        "steps": [
            {
                "index": 1,
                "type": "click",
                "button": "left",
                "x": 4,
                "y": 5,
                "elapsed_s": 1.25,
                "target": {"label": "Save", "kind": "button"},
            }
        ]
    }
    payload = step_payload(session)
    assert payload == [
        {
            "index": 1,
            "type": "click",
            "hint": "Click **Save**.",
            "elapsed_s": 1.25,
            "target": "Save",
        }
    ]
