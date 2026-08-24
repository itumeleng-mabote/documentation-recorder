from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "base"


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def whisper_extra_installed() -> bool:
    from docrecorder.audio import mic_available

    return mic_available() and whisper_available()


def whisper_model() -> str:
    return (os.environ.get("DOCRECORDER_WHISPER_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def format_transcript_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = float(segment.get("start") or 0)
        end = float(segment.get("end") or 0)
        lines.append(f"[{start:.1f}-{end:.1f}] {text}")
    return "\n".join(lines)


def transcribe_wav(path: Path, *, model_name: str | None = None) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    name = model_name or whisper_model()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    items: list[dict[str, Any]] = []
    texts: list[str] = []
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        items.append(
            {
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": text,
            }
        )
        texts.append(text)
    return {"text": " ".join(texts), "segments": items, "model": name}
