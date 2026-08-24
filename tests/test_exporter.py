import json
from pathlib import Path

from docrecorder.exporter import display_caption, render_html, render_markdown, step_caption, write_session


def _session() -> dict:
    return {
        "window_title": "Settings",
        "app_name": "System Settings",
        "platform": "darwin",
        "started_at": "2026-08-24T13:03:00+00:00",
        "ended_at": "2026-08-24T13:04:00+00:00",
        "window_size": [800, 600],
        "scale": 2.0,
        "steps": [
            {
                "index": 1,
                "type": "click",
                "button": "left",
                "x": 120,
                "y": 48,
                "screenshot_annotated": "annotated/step-01.png",
                "screenshot_raw": "raw/step-01.png",
            },
            {
                "index": 2,
                "type": "type",
                "text": "jane@example.com",
                "screenshot_annotated": "annotated/step-02.png",
            },
        ],
    }


def test_step_captions():
    session = _session()
    assert step_caption(session["steps"][0]) == "Click at (120, 48)."
    assert step_caption(session["steps"][1]) == "Type `jane@example.com`."
    assert step_caption({"type": "click", "button": "right", "x": 1, "y": 2}) == "Right click at (1, 2)."
    assert (
        step_caption(
            {
                "type": "click",
                "button": "left",
                "x": 1,
                "y": 2,
                "target": {"label": "Save", "kind": "button"},
            }
        )
        == "Click **Save**."
    )
    assert (
        step_caption(
            {
                "type": "click",
                "button": "right",
                "x": 1,
                "y": 2,
                "target": {"label": "File", "kind": "menu"},
            }
        )
        == "Right click **File**."
    )
    assert (
        step_caption(
            {
                "type": "click",
                "button": "left",
                "x": 8,
                "y": 9,
                "target": {"label": "", "kind": "unknown"},
            }
        )
        == "Click at (8, 9)."
    )


def test_markdown_contains_steps_and_images():
    markdown = render_markdown(_session())
    assert markdown.startswith("# Documentation: Settings")
    assert "Recorded on 2026-08-24 for **System Settings** (darwin)." in markdown
    assert "## Step 1" in markdown
    assert "![Step 1](annotated/step-01.png)" in markdown
    assert "Type `jane@example.com`." in markdown


def test_html_contains_escaped_type_step():
    html = render_html(_session())
    assert "<title>Documentation: Settings</title>" in html
    assert "Type <code>jane@example.com</code>." in html
    assert 'src="annotated/step-01.png"' in html


def test_html_uses_strong_for_click_target():
    session = _session()
    session["steps"][0]["target"] = {"label": "General <tab>", "kind": "tab"}
    html = render_html(session)
    assert "Click <strong>General &lt;tab&gt;</strong>." in html
    markdown = render_markdown(session)
    assert "Click **General <tab>**." in markdown


def test_write_session_creates_files(tmp_path: Path):
    session = _session()
    write_session(session, tmp_path)
    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    assert events["window_title"] == "Settings"
    assert (tmp_path / "guide.md").is_file()
    assert (tmp_path / "guide.html").is_file()
    assert "Step 2" in (tmp_path / "guide.md").read_text(encoding="utf-8")


def test_display_caption_prefers_rewrite():
    step = {
        "type": "click",
        "button": "left",
        "x": 120,
        "y": 48,
        "caption": "Click **Save** to keep your changes.",
    }
    assert display_caption(step) == "Click **Save** to keep your changes."
    assert step_caption(step) == "Click at (120, 48)."


def test_markdown_and_html_use_rewritten_caption():
    session = _session()
    session["steps"][0]["caption"] = "Open **General** in Settings."
    session["steps"][1]["caption"] = "Type `jane@example.com` in the email field."
    markdown = render_markdown(session)
    html = render_html(session)
    assert "Open **General** in Settings." in markdown
    assert "Click at (120, 48)." not in markdown
    assert "Open <strong>General</strong> in Settings." in html
    assert "Type <code>jane@example.com</code> in the email field." in html
