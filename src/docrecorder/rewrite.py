from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from docrecorder.exporter import step_caption
from docrecorder.transcribe import format_transcript_segments
from docrecorder.vision import (
    DEFAULT_MODEL,
    OllamaUnreachable,
    chat_json,
    extract_json_object,
)

REWRITE_UNREACHABLE_MESSAGE = (
    f"Ollama is not running or {DEFAULT_MODEL} is unavailable. "
    "Step captions were not rewritten."
)
REWRITE_PROMPT = (
    "You write step-by-step software documentation. "
    "Given recorded UI actions and an optional voice transcript, write one short instruction per step. "
    "Return JSON only with key steps: an array of objects with index and caption. "
    "Keep the same step count and indexes. "
    "One or two sentences per step. "
    "Use the transcript to explain intent. "
    "For click steps, prefer the identified target label and wrap it in **bold**. "
    "For type steps, include the typed text in backticks. "
    "Do not invent UI that was not recorded."
)
REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "caption": {"type": "string"},
                },
                "required": ["index", "caption"],
            },
        }
    },
    "required": ["steps"],
}

ChatTextFn = Callable[[str], str]


def parse_rewrite_json(text: str) -> list[dict[str, Any]] | None:
    data = extract_json_object(text)
    if data is None:
        return None
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return None
    parsed: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        caption = str(item.get("caption") or "").strip()
        if caption:
            parsed.append({"index": index, "caption": caption})
    return parsed or None


def apply_captions(session: dict[str, Any], captions: list[dict[str, Any]]) -> None:
    by_index = {item["index"]: item["caption"] for item in captions}
    for step in session.get("steps") or []:
        try:
            index = int(step.get("index"))
        except (TypeError, ValueError):
            continue
        caption = by_index.get(index)
        if caption:
            step["caption"] = caption


def step_payload(session: dict[str, Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for step in session.get("steps") or []:
        item: dict[str, Any] = {
            "index": step.get("index"),
            "type": step.get("type"),
            "hint": step_caption(step),
        }
        if step.get("elapsed_s") is not None:
            item["elapsed_s"] = step["elapsed_s"]
        if step.get("type") == "type":
            item["text"] = step.get("text")
        target = step.get("target")
        if isinstance(target, dict) and str(target.get("label") or "").strip():
            item["target"] = str(target["label"]).strip()
        payload.append(item)
    return payload


def build_rewrite_prompt(session: dict[str, Any]) -> str:
    transcript = str(session.get("transcript") or "").strip()
    segments = session.get("transcript_segments") or []
    timed = format_transcript_segments(segments) if isinstance(segments, list) else ""
    body = {
        "app_name": session.get("app_name") or session.get("window_title"),
        "window_title": session.get("window_title"),
        "steps": step_payload(session),
        "transcript": transcript,
        "transcript_segments": timed,
    }
    return f"{REWRITE_PROMPT}\n\n{json.dumps(body, ensure_ascii=False)}"


def rewrite_captions(
    session: dict[str, Any],
    *,
    chat: ChatTextFn | None = None,
) -> str | None:
    """Write caption onto each matching step. Returns a warning if Ollama is unreachable."""
    steps = session.get("steps") or []
    if not steps:
        return None
    send = chat or (
        lambda prompt: chat_json(
            prompt,
            schema=REWRITE_SCHEMA,
            unreachable=REWRITE_UNREACHABLE_MESSAGE,
            timeout=90,
        )
    )
    try:
        text = send(build_rewrite_prompt(session))
    except OllamaUnreachable as exc:
        return str(exc) or REWRITE_UNREACHABLE_MESSAGE
    except Exception as exc:
        return f"Step captions were not rewritten: {exc}"
    parsed = parse_rewrite_json(text)
    if parsed:
        apply_captions(session, parsed)
    return None
