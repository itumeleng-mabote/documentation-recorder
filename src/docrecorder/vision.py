from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "qwen3.5:4b-mlx"
DEFAULT_HOST = "http://127.0.0.1:11434"
TIMEOUT_SECONDS = 45
VALID_KINDS = frozenset(
    {"button", "link", "menu", "tab", "checkbox", "toggle", "icon", "field", "item", "unknown"}
)
IDENTIFY_PROMPT = (
    "The red marker shows where the user clicked. Identify the UI control at that marker. "
    "Return JSON only with keys label and kind. "
    "label is the visible text or a short name (max 8 words). Use an empty string if unsure. "
    "kind is one of: button, link, menu, tab, checkbox, toggle, icon, field, item, unknown."
)
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "kind": {"type": "string"},
    },
    "required": ["label", "kind"],
}
UNREACHABLE_MESSAGE = (
    "Ollama is not running or qwen3.5:4b-mlx is unavailable. "
    "Click labels were skipped; captions use coordinates."
)

ChatFn = Callable[[bytes], str]


class OllamaUnreachable(Exception):
    """Raised when the local Ollama server cannot be reached."""


def ollama_host() -> str:
    host = (os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host


def ollama_model() -> str:
    return (os.environ.get("DOCRECORDER_OLLAMA_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def parse_target_json(text: str) -> dict[str, str] | None:
    data = extract_json_object(text)
    if data is None:
        return None
    label = str(data.get("label") or "").strip()
    kind = str(data.get("kind") or "unknown").strip().lower()
    if kind not in VALID_KINDS:
        kind = "unknown"
    return {"label": label, "kind": kind}


def chat_vision(image_bytes: bytes, *, model: str | None = None, host: str | None = None) -> str:
    payload = {
        "model": model or ollama_model(),
        "messages": [
            {
                "role": "user",
                "content": IDENTIFY_PROMPT,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }
        ],
        "stream": False,
        "think": False,
        "format": JSON_SCHEMA,
        "options": {"temperature": 0},
    }
    return _ollama_chat(payload, host=host, unreachable=UNREACHABLE_MESSAGE)


def chat_json(
    prompt: str,
    *,
    schema: dict[str, Any],
    model: str | None = None,
    host: str | None = None,
    unreachable: str | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> str:
    payload = {
        "model": model or ollama_model(),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0},
    }
    return _ollama_chat(
        payload,
        host=host,
        unreachable=unreachable or UNREACHABLE_MESSAGE,
        timeout=timeout,
    )


def _ollama_chat(
    payload: dict[str, Any],
    *,
    host: str | None = None,
    unreachable: str = UNREACHABLE_MESSAGE,
    timeout: int = TIMEOUT_SECONDS,
) -> str:
    request = urllib.request.Request(
        f"{host or ollama_host()}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 502, 503}:
            raise OllamaUnreachable(unreachable) from exc
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaUnreachable(unreachable) from exc
    message = body.get("message") if isinstance(body, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        return json.dumps(content)
    return str(content or "")


def identify_clicks(
    session: dict[str, Any],
    session_dir: Path,
    *,
    on_progress: Callable[[int, int], None] | None = None,
    chat: ChatFn | None = None,
) -> str | None:
    """Label click steps in place. Returns a warning if Ollama is unreachable."""
    steps = [step for step in session.get("steps") or [] if _needs_label(step)]
    if not steps:
        return None
    send = chat or chat_vision
    for index, step in enumerate(steps, start=1):
        if on_progress is not None:
            on_progress(index, len(steps))
        crop_path = session_dir / str(step["screenshot_crop"])
        if not crop_path.is_file():
            continue
        try:
            text = send(crop_path.read_bytes())
        except OllamaUnreachable as exc:
            return str(exc) or UNREACHABLE_MESSAGE
        except Exception:
            continue
        parsed = parse_target_json(text)
        if parsed and parsed["label"]:
            step["target"] = parsed
    return None


def _needs_label(step: dict[str, Any]) -> bool:
    return step.get("type") == "click" and bool(step.get("screenshot_crop"))
