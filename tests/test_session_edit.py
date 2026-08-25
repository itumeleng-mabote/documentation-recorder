import json
from pathlib import Path

import pytest
from PIL import Image

from docrecorder.exporter import render_markdown
from docrecorder.session_edit import (
    load_session,
    load_step_background,
    save_edited_session,
)


def _write_png(path: Path, color=(255, 255, 255), size=(100, 80)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _session(tmp_path: Path, *, with_raw: bool = True, extra_step: bool = True) -> dict:
    steps = [
        {
            "index": 1,
            "type": "click",
            "button": "left",
            "x": 50,
            "y": 40,
            "screenshot_annotated": "annotated/step-01.png",
        },
        {
            "index": 2,
            "type": "type",
            "text": "hello",
            "screenshot_annotated": "annotated/step-02.png",
        },
    ]
    if not extra_step:
        steps = steps[:1]
    if with_raw:
        for step in steps:
            raw = f"raw/step-{step['index']:02d}.png"
            step["screenshot_raw"] = raw
            _write_png(tmp_path / raw, (240, 240, 240))
    for step in steps:
        _write_png(tmp_path / step["screenshot_annotated"], (250, 250, 250))
    session = {
        "window_title": "Settings",
        "app_name": "System Settings",
        "platform": "darwin",
        "started_at": "2026-08-24T13:03:00+00:00",
        "scale": 1.0,
        "steps": steps,
    }
    (tmp_path / "events.json").write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    return session


def test_load_session_requires_events(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_session(tmp_path)


def test_save_persists_caption_and_overlays(tmp_path: Path):
    session = _session(tmp_path)
    steps = list(session["steps"])
    steps[0]["caption"] = "Open **General**."
    steps[0]["annotations"] = [
        {"type": "rect", "color": "#E12D2D", "stroke": 6, "x1": 10, "y1": 10, "x2": 70, "y2": 60}
    ]
    saved = save_edited_session(session, tmp_path, steps)
    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    assert events["steps"][0]["caption"] == "Open **General**."
    assert events["steps"][0]["annotations"][0]["type"] == "rect"
    markdown = (tmp_path / "guide.md").read_text(encoding="utf-8")
    assert "Open **General**." in markdown
    image = Image.open(tmp_path / "annotated/step-01.png")
    assert any(
        pixel[0] > 150 and pixel[0] > pixel[1]
        for pixel in (image.getpixel((x, 30)) for x in range(7, 16))
    )
    assert saved["steps"][0]["caption"] == "Open **General**."


def test_delete_step_renumbers_and_removes_files(tmp_path: Path):
    session = _session(tmp_path)
    remaining = [dict(session["steps"][1])]
    remaining[0]["caption"] = "Type `hello` in the field."
    save_edited_session(session, tmp_path, remaining)
    events = json.loads((tmp_path / "events.json").read_text(encoding="utf-8"))
    assert len(events["steps"]) == 1
    assert events["steps"][0]["index"] == 1
    assert events["steps"][0]["type"] == "type"
    assert events["steps"][0]["screenshot_annotated"] == "annotated/step-01.png"
    assert events["steps"][0]["screenshot_raw"] == "raw/step-01.png"
    assert (tmp_path / "annotated/step-01.png").is_file()
    assert (tmp_path / "raw/step-01.png").is_file()
    assert not (tmp_path / "annotated/step-02.png").exists()
    assert not (tmp_path / "raw/step-02.png").exists()
    markdown = render_markdown(events)
    assert "## Step 1" in markdown
    assert "## Step 2" not in markdown
    assert "Type `hello` in the field." in markdown


def test_background_excludes_user_overlays_without_raw(tmp_path: Path):
    session = _session(tmp_path, with_raw=False, extra_step=False)
    steps = list(session["steps"])
    steps[0]["annotations"] = [
        {"type": "rect", "color": "#E12D2D", "stroke": 8, "x1": 8, "y1": 8, "x2": 80, "y2": 60}
    ]
    save_edited_session(session, tmp_path, steps)
    events = load_session(tmp_path)
    assert events["steps"][0]["screenshot_base"] == "annotated/step-01.base.png"
    annotated = Image.open(tmp_path / "annotated/step-01.png")
    base = Image.open(tmp_path / "annotated/step-01.base.png")
    assert annotated.tobytes() != base.tobytes()
    background = load_step_background(events, tmp_path, events["steps"][0])
    assert background is not None
    assert background.tobytes() == base.convert("RGB").tobytes()


def test_click_ring_reapplied_from_raw(tmp_path: Path):
    session = _session(tmp_path, extra_step=False)
    _write_png(tmp_path / "raw/step-01.png", (255, 255, 255), size=(120, 80))
    save_edited_session(session, tmp_path, list(session["steps"]))
    annotated = Image.open(tmp_path / "annotated/step-01.png")
    red, green, blue = annotated.getpixel((50, 40))
    assert red > 150
    assert red > green
    assert red > blue
