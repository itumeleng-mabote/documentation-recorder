from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def step_caption(step: dict[str, Any]) -> str:
    kind = step.get("type")
    if kind == "click":
        button = str(step.get("button") or "left")
        prefix = "Click" if button == "left" else f"{button.capitalize()} click"
        label = _click_label(step)
        if label:
            return f"{prefix} **{label}**."
        return f"{prefix} at ({step['x']}, {step['y']})."
    if kind == "type":
        text = str(step.get("text") or "").replace("`", "\\`")
        return f"Type `{text}`."
    return ""


def display_caption(step: dict[str, Any]) -> str:
    custom = str(step.get("caption") or "").strip()
    if custom:
        return custom
    return step_caption(step)


def write_session(session: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "events.json").write_text(
        json.dumps(session, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "guide.md").write_text(render_markdown(session), encoding="utf-8")
    (output_dir / "guide.html").write_text(render_html(session), encoding="utf-8")


def render_markdown(session: dict[str, Any]) -> str:
    title = session.get("window_title") or session.get("app_name") or "Untitled"
    app_name = session.get("app_name") or title
    recorded = _recorded_on(session)
    lines = [
        f"# Documentation: {title}",
        "",
        f"Recorded on {recorded} for **{app_name}** ({session.get('platform', 'unknown')}).",
        "",
    ]
    for step in session.get("steps") or []:
        index = step.get("index", 0)
        image = step.get("screenshot_annotated") or step.get("screenshot_raw")
        lines.extend(
            [
                f"## Step {index}",
                "",
                display_caption(step),
                "",
            ]
        )
        if image:
            lines.extend([f"![Step {index}]({image})", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_html(session: dict[str, Any]) -> str:
    title = session.get("window_title") or session.get("app_name") or "Untitled"
    app_name = session.get("app_name") or title
    recorded = _recorded_on(session)
    steps_html = []
    for step in session.get("steps") or []:
        index = step.get("index", 0)
        caption = _html_caption(step)
        image = step.get("screenshot_annotated") or step.get("screenshot_raw")
        img = (
            f'<img src="{html.escape(image)}" alt="Step {index}">'
            if image
            else ""
        )
        steps_html.append(
            f"""<section class="step">
  <h2>Step {index}</h2>
  <p>{caption}</p>
  {img}
</section>"""
        )
    body = "\n".join(steps_html)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Documentation: {html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; max-width: 920px; margin: 2rem auto; padding: 0 1.25rem; color: #1f2933; line-height: 1.5; }}
    h1 {{ font-size: 1.75rem; margin-bottom: 0.25rem; }}
    .meta {{ color: #52606d; margin-bottom: 2rem; }}
    .step {{ margin-bottom: 2.5rem; }}
    img {{ max-width: 100%; height: auto; border: 1px solid #d8dee6; border-radius: 8px; }}
    code {{ background: #f5f7fa; padding: 0.1em 0.35em; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Documentation: {html.escape(title)}</h1>
  <p class="meta">Recorded on {html.escape(recorded)} for <strong>{html.escape(app_name)}</strong> ({html.escape(str(session.get("platform") or "unknown"))}).</p>
  {body}
</body>
</html>
"""


def _html_caption(step: dict[str, Any]) -> str:
    escaped = html.escape(display_caption(step))
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)


def _click_label(step: dict[str, Any]) -> str:
    target = step.get("target")
    if isinstance(target, dict):
        return str(target.get("label") or "").strip()
    return str(target or "").strip()


def _recorded_on(session: dict[str, Any]) -> str:
    started = str(session.get("started_at") or "")
    try:
        return datetime.fromisoformat(started).strftime("%Y-%m-%d")
    except ValueError:
        return started[:10] if started else "unknown"
