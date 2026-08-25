from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from docrecorder.annotator import annotate_click, apply_overlays, normalize_annotation
from docrecorder.exporter import write_session

SCREENSHOT_KEYS = (
    "screenshot_annotated",
    "screenshot_raw",
    "screenshot_crop",
    "screenshot_crop_marked",
    "screenshot_base",
)


def load_session(session_dir: Path) -> dict[str, Any]:
    path = Path(session_dir) / "events.json"
    if not path.is_file():
        raise FileNotFoundError(f"No events.json in {session_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError("events.json is not a valid session")
    return data


def reveal_folder(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
    except OSError:
        pass


def editor_base_path(session_dir: Path, step: dict[str, Any]) -> Path | None:
    for key in ("screenshot_raw", "screenshot_base", "screenshot_annotated"):
        rel = step.get(key)
        if rel:
            path = session_dir / str(rel)
            if path.is_file():
                return path
    return None


def uses_raw_base(session_dir: Path, step: dict[str, Any]) -> bool:
    rel = step.get("screenshot_raw")
    return bool(rel) and (session_dir / str(rel)).is_file()


def load_step_background(
    session: dict[str, Any],
    session_dir: Path,
    step: dict[str, Any],
) -> Image.Image | None:
    """Click-ring image without user overlays, for the editor canvas."""
    path = editor_base_path(session_dir, step)
    if path is None:
        return None
    image = Image.open(path).convert("RGB")
    if uses_raw_base(session_dir, step) and step.get("type") == "click":
        image = annotate_click(
            image,
            float(step.get("x") or 0),
            float(step.get("y") or 0),
            float(session.get("scale") or 1.0),
        )
    return image


def composite_step_image(
    session: dict[str, Any],
    session_dir: Path,
    step: dict[str, Any],
) -> Image.Image | None:
    background = load_step_background(session, session_dir, step)
    if background is None:
        return None
    return apply_overlays(background, step.get("annotations"))


def save_edited_session(
    session: dict[str, Any],
    session_dir: Path,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist edited steps, composite overlays, drop unused files, rewrite guides."""
    session_dir = Path(session_dir)
    prepared: list[tuple[dict[str, Any], int, Image.Image | None]] = []
    temps: set[str] = set()
    for index, original in enumerate(steps, start=1):
        step = dict(original)
        _normalize_step_annotations(step)
        _ensure_screenshot_base(session_dir, step, temps)
        image = composite_step_image(session, session_dir, step)
        prepared.append((step, index, image))

    old_rels = _screenshot_rels(session.get("steps") or [])
    used: set[str] = set()
    new_steps: list[dict[str, Any]] = []
    for step, index, image in prepared:
        step["index"] = index
        name = f"step-{index:02d}.png"
        if image is not None:
            rel = f"annotated/{name}"
            dest = session_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            image.save(dest)
            step["screenshot_annotated"] = rel
            used.add(rel)
        _relocate_sidecar(session_dir, step, "screenshot_raw", f"raw/{name}", used)
        _relocate_sidecar(session_dir, step, "screenshot_crop", f"crops/{name}", used)
        _relocate_sidecar(
            session_dir,
            step,
            "screenshot_crop_marked",
            f"crops/step-{index:02d}-marked.png",
            used,
        )
        _relocate_sidecar(
            session_dir,
            step,
            "screenshot_base",
            f"annotated/step-{index:02d}.base.png",
            used,
        )
        new_steps.append(step)

    for rel in (old_rels | temps) - used:
        leftover = session_dir / rel
        if leftover.is_file():
            leftover.unlink()

    session["steps"] = new_steps
    write_session(session, session_dir)
    return session


def _normalize_step_annotations(step: dict[str, Any]) -> None:
    items = [
        normalized
        for item in (step.get("annotations") or [])
        if (normalized := normalize_annotation(item))
    ]
    if items:
        step["annotations"] = items
    else:
        step.pop("annotations", None)
    caption = str(step.get("caption") or "").strip()
    if caption:
        step["caption"] = caption
    else:
        step.pop("caption", None)


def _ensure_screenshot_base(session_dir: Path, step: dict[str, Any], temps: set[str]) -> None:
    if not step.get("annotations"):
        return
    if uses_raw_base(session_dir, step):
        return
    existing = step.get("screenshot_base")
    if existing and (session_dir / str(existing)).is_file():
        return
    annotated = step.get("screenshot_annotated")
    if not annotated:
        return
    src = session_dir / str(annotated)
    if not src.is_file():
        return
    annotated_str = str(annotated)
    if annotated_str.endswith(".png"):
        base_rel = annotated_str[:-4] + ".base.png"
    else:
        base_rel = annotated_str + ".base.png"
    dest = session_dir / base_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    step["screenshot_base"] = base_rel
    temps.add(base_rel)


def _relocate_sidecar(
    session_dir: Path,
    step: dict[str, Any],
    key: str,
    new_rel: str,
    used: set[str],
) -> None:
    old_rel = step.get(key)
    if not old_rel:
        return
    src = session_dir / str(old_rel)
    dest = session_dir / new_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        step.pop(key, None)
        return
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    step[key] = new_rel
    used.add(new_rel)


def _screenshot_rels(steps: list[dict[str, Any]]) -> set[str]:
    rels: set[str] = set()
    for step in steps:
        for key in SCREENSHOT_KEYS:
            rel = step.get(key)
            if rel:
                rels.add(str(rel))
    return rels
