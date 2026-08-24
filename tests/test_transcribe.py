from docrecorder.transcribe import format_transcript_segments, whisper_model


def test_format_transcript_segments_skips_empty():
    text = format_transcript_segments(
        [
            {"start": 0, "end": 1.5, "text": " Open settings "},
            {"start": 2, "end": 2.2, "text": "  "},
            {"start": 3.04, "end": 4, "text": "then click Save"},
        ]
    )
    assert text == "[0.0-1.5] Open settings\n[3.0-4.0] then click Save"


def test_whisper_model_env(monkeypatch):
    monkeypatch.setenv("DOCRECORDER_WHISPER_MODEL", "small")
    assert whisper_model() == "small"
    monkeypatch.setenv("DOCRECORDER_WHISPER_MODEL", "  ")
    assert whisper_model() == "base"
