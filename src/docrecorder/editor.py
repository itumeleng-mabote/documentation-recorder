from __future__ import annotations

import copy
import json
import math
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from PIL import Image, ImageTk

from docrecorder.annotator import (
    DEFAULT_OVERLAY_COLOR,
    DEFAULT_OVERLAY_STROKE,
    DEFAULT_TEXT_SIZE,
    normalize_annotation,
)
from docrecorder.exporter import display_caption
from docrecorder.history import EditHistory
from docrecorder.session_edit import (
    load_session,
    load_step_background,
    reveal_folder,
    save_edited_session,
)

UNDO_ACCEL = "Cmd+Z" if sys.platform == "darwin" else "Ctrl+Z"
REDO_ACCEL = "Cmd+Shift+Z" if sys.platform == "darwin" else "Ctrl+Shift+Z"

MAX_DISPLAY_WIDTH = 920
MIN_DRAG = 4
HIT_PADDING = 8
COLORS = ("#E12D2D", "#FF5A14", "#F5C518", "#2563EB", "#111827", "#FFFFFF")
STROKES = (("Thin", 2), ("Medium", 4), ("Thick", 8))
TOOLS = (
    ("select", "Select"),
    ("arrow", "Arrow"),
    ("rect", "Rectangle"),
    ("circle", "Circle"),
    ("text", "Text"),
)

_open_editors: dict[str, "PreviewEditor"] = {}


def open_preview_editor(parent: tk.Misc, session_dir: Path) -> PreviewEditor | None:
    key = str(Path(session_dir).resolve())
    existing = _open_editors.get(key)
    if existing is not None:
        try:
            existing.window.lift()
            existing.window.focus_force()
            return existing
        except tk.TclError:
            _open_editors.pop(key, None)
    try:
        session = load_session(session_dir)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        messagebox.showerror("Documentation Recorder", f"Could not open session.\n\n{exc}")
        return None
    editor = PreviewEditor(parent, Path(session_dir), session)
    _open_editors[key] = editor
    return editor


class PreviewEditor:
    def __init__(self, parent: tk.Misc, session_dir: Path, session: dict[str, Any]) -> None:
        self.session_dir = session_dir
        self.session = json.loads(json.dumps(session))
        self.steps: list[dict[str, Any]] = list(self.session.get("steps") or [])
        self._cards: list[StepCard] = []
        self._selected: tuple[AnnotationCanvas, int] | None = None
        self.history = EditHistory()
        self._committed: list[dict[str, Any]] = copy.deepcopy(self.steps)
        self._rebuilding = False

        self.window = tk.Toplevel(parent)
        self.window.title(self._title())
        self.window.geometry("1100x800")
        self.window.minsize(720, 480)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self.tool_var = tk.StringVar(value="select")
        self.color_var = tk.StringVar(value=DEFAULT_OVERLAY_COLOR)
        self.stroke_var = tk.IntVar(value=DEFAULT_OVERLAY_STROKE)
        self.status_var = tk.StringVar(value="")

        self._build()
        self._rebuild_cards()
        self._committed = copy.deepcopy(self._collect_steps())
        self._sync_history_buttons()
        self.window.bind("<Delete>", self._on_delete_key)
        self.window.bind("<BackSpace>", self._on_delete_key)
        self.window.bind("<Escape>", self._on_escape)
        self.window.bind("<MouseWheel>", self._on_mousewheel)
        self._bind_history_keys(self.window)
        if sys.platform != "darwin":
            self.window.bind("<Button-4>", self._on_mousewheel)
            self.window.bind("<Button-5>", self._on_mousewheel)

    def _title(self) -> str:
        name = self.session.get("window_title") or self.session.get("app_name") or "Untitled"
        return f"Guide preview — {name}"

    def _build(self) -> None:
        toolbar = ttk.Frame(self.window, padding=(12, 8, 12, 4))
        toolbar.pack(fill=tk.X)
        ttk.Label(toolbar, text="Tool").pack(side=tk.LEFT, padx=(0, 6))
        for value, label in TOOLS:
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.tool_var).pack(
                side=tk.LEFT, padx=(0, 4)
            )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Label(toolbar, text="Color").pack(side=tk.LEFT, padx=(0, 6))
        swatches = ttk.Frame(toolbar)
        swatches.pack(side=tk.LEFT)
        self._swatches: list[tk.Canvas] = []
        for color in COLORS:
            chip = tk.Canvas(
                swatches,
                width=18,
                height=18,
                highlightthickness=1,
                highlightbackground="#94a3b8",
                background=color,
                cursor="hand2",
            )
            chip.pack(side=tk.LEFT, padx=2)
            chip.bind("<Button-1>", lambda _event, value=color: self._set_color(value))
            self._swatches.append(chip)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Label(toolbar, text="Stroke").pack(side=tk.LEFT, padx=(0, 6))
        for label, value in STROKES:
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.stroke_var).pack(
                side=tk.LEFT, padx=(0, 4)
            )
        ttk.Button(toolbar, text="Delete annotation", command=self.delete_selected_annotation).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        self.undo_btn = ttk.Button(toolbar, text=f"Undo ({UNDO_ACCEL})", command=self.undo)
        self.redo_btn = ttk.Button(toolbar, text=f"Redo ({REDO_ACCEL})", command=self.redo)
        self.undo_btn.pack(side=tk.LEFT)
        self.redo_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._refresh_swatches()

        meta = ttk.Frame(self.window, padding=(12, 0, 12, 4))
        meta.pack(fill=tk.X)
        app_name = self.session.get("app_name") or self.session.get("window_title") or "Untitled"
        recorded = str(self.session.get("started_at") or "")[:10] or "unknown"
        ttk.Label(
            meta,
            text=f"Recorded on {recorded} for {app_name} ({self.session.get('platform') or 'unknown'})",
            foreground="#52606d",
        ).pack(anchor=tk.W)

        body = ttk.Frame(self.window)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.scroll = tk.Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.scroll.yview)
        self.inner = ttk.Frame(self.scroll)
        self._inner_window = self.scroll.create_window((0, 0), window=self.inner, anchor="nw")
        self.scroll.configure(yscrollcommand=scrollbar.set)
        self.inner.bind("<Configure>", lambda _event: self.scroll.configure(scrollregion=self.scroll.bbox("all")))
        self.scroll.bind("<Configure>", self._on_scroll_configure)
        self.scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        footer = ttk.Frame(self.window, padding=(12, 4, 12, 10))
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Save", command=self._on_save).pack(side=tk.LEFT)
        ttk.Button(footer, text="Reveal folder", command=lambda: reveal_folder(self.session_dir)).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Label(footer, textvariable=self.status_var).pack(side=tk.LEFT, padx=(16, 0))

    def _set_color(self, color: str) -> None:
        self.color_var.set(color)
        self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        current = self.color_var.get()
        for chip, color in zip(self._swatches, COLORS):
            chip.configure(highlightbackground="#111827" if color == current else "#94a3b8")
            chip.configure(highlightthickness=2 if color == current else 1)

    def _on_scroll_configure(self, event: tk.Event) -> None:
        self.scroll.itemconfigure(self._inner_window, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> str | None:
        widget = self.window.winfo_containing(event.x_root, event.y_root)
        if _is_text_widget(widget):
            return None
        if getattr(event, "num", None) == 4:
            self.scroll.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.scroll.yview_scroll(1, "units")
        elif sys.platform == "darwin":
            self.scroll.yview_scroll(int(-1 * event.delta), "units")
        else:
            self.scroll.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _rebuild_cards(self) -> None:
        self._rebuilding = True
        self._selected = None
        try:
            for child in self.inner.winfo_children():
                child.destroy()
            self._cards.clear()
            if not self.steps:
                ttk.Label(self.inner, text="No steps in this session.").pack(anchor=tk.W, padx=12, pady=24)
                return
            for index, step in enumerate(self.steps):
                card = StepCard(self.inner, self, index, step)
                card.pack(fill=tk.X, padx=8, pady=(0, 18))
                self._cards.append(card)
            self.window.after_idle(lambda: self.scroll.configure(scrollregion=self.scroll.bbox("all")))
        finally:
            self._rebuilding = False

    def delete_step(self, index: int) -> None:
        self.steps = self._collect_steps()
        if not (0 <= index < len(self.steps)):
            return
        self._push_undo()
        del self.steps[index]
        self._rebuild_cards()
        self._after_change("Step deleted. Save to write the session.")

    def record_annotation_change(self) -> None:
        self._push_undo()

    def finish_annotation_change(self, status: str) -> None:
        self._after_change(status)

    def select_annotation(self, canvas: AnnotationCanvas, index: int | None) -> None:
        previous = self._selected
        if index is None:
            self._selected = None
        else:
            self._selected = (canvas, index)
        if previous is not None:
            previous[0].redraw()
        canvas.redraw()

    def delete_selected_annotation(self) -> None:
        selected = self._selected
        if selected is None:
            return
        canvas, index = selected
        if not (0 <= index < len(canvas.annotations)):
            return
        self._push_undo()
        del canvas.annotations[index]
        self._selected = None
        canvas.redraw()
        self._after_change("Annotation deleted.")

    def _on_delete_key(self, event: tk.Event) -> str | None:
        if _is_text_widget(self.window.focus_get()):
            return None
        self.delete_selected_annotation()
        return "break"

    def _on_escape(self, _event: tk.Event) -> None:
        if self._selected is not None:
            canvas = self._selected[0]
            self._selected = None
            canvas.redraw()
        self.tool_var.set("select")

    def _collect_steps(self) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for card in self._cards:
            step = dict(card.step)
            caption = card.caption.get("1.0", "end").strip()
            if caption:
                step["caption"] = caption
            else:
                step.pop("caption", None)
            annotations = [
                normalized
                for item in card.canvas.annotations
                if (normalized := normalize_annotation(item))
            ]
            if annotations:
                step["annotations"] = annotations
            else:
                step.pop("annotations", None)
            collected.append(step)
        return collected

    def _bind_history_keys(self, widget: tk.Misc) -> None:
        if sys.platform == "darwin":
            widget.bind("<Command-z>", self._on_undo_key)
            widget.bind("<Command-Z>", self._on_redo_key)
            widget.bind("<Command-y>", self._on_redo_key)
        else:
            widget.bind("<Control-z>", self._on_undo_key)
            widget.bind("<Control-Z>", self._on_redo_key)
            widget.bind("<Control-y>", self._on_redo_key)

    def _on_undo_key(self, _event: tk.Event | None = None) -> str:
        widget = self.window.focus_get()
        if isinstance(widget, tk.Text):
            try:
                widget.edit_undo()
                return "break"
            except tk.TclError:
                pass
        self.undo()
        return "break"

    def _on_redo_key(self, _event: tk.Event | None = None) -> str:
        widget = self.window.focus_get()
        if isinstance(widget, tk.Text):
            try:
                widget.edit_redo()
                return "break"
            except tk.TclError:
                pass
        self.redo()
        return "break"

    def _commit_caption_if_changed(self) -> None:
        if self._rebuilding or not self._cards:
            return
        current = self._collect_steps()
        if current == self._committed:
            return
        self.history.push(self._committed)
        self._committed = copy.deepcopy(current)
        self._sync_history_buttons()

    def _push_undo(self) -> None:
        self._commit_caption_if_changed()
        self.history.push(self._collect_steps())
        self._sync_history_buttons()

    def _after_change(self, status: str) -> None:
        self._committed = copy.deepcopy(self._collect_steps())
        self._sync_history_buttons()
        self.status_var.set(status)

    def _sync_history_buttons(self) -> None:
        self.undo_btn.configure(state=tk.NORMAL if self.history.can_undo() else tk.DISABLED)
        self.redo_btn.configure(state=tk.NORMAL if self.history.can_redo() else tk.DISABLED)

    def _restore_steps(self, steps: list[dict[str, Any]], status: str) -> None:
        self.steps = copy.deepcopy(steps)
        self._rebuild_cards()
        self._committed = copy.deepcopy(self._collect_steps())
        self._sync_history_buttons()
        self.status_var.set(status)

    def undo(self) -> None:
        restored = self.history.undo(self._collect_steps())
        if restored is None:
            self.status_var.set("Nothing to undo.")
            return
        self._restore_steps(restored, "Undid last change.")

    def redo(self) -> None:
        restored = self.history.redo(self._collect_steps())
        if restored is None:
            self.status_var.set("Nothing to redo.")
            return
        self._restore_steps(restored, "Redid last change.")

    def _on_save(self) -> None:
        try:
            steps = self._collect_steps()
            self.session = save_edited_session(self.session, self.session_dir, steps)
            self.steps = list(self.session.get("steps") or [])
            self._rebuild_cards()
            self._committed = copy.deepcopy(self._collect_steps())
            self._sync_history_buttons()
            self.status_var.set("Saved.")
        except OSError as exc:
            messagebox.showerror("Documentation Recorder", f"Could not save session.\n\n{exc}")

    def _on_close(self) -> None:
        key = str(self.session_dir.resolve())
        _open_editors.pop(key, None)
        self.window.destroy()


class StepCard(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        editor: PreviewEditor,
        index: int,
        step: dict[str, Any],
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        self.index = index
        self.step = step

        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        ttk.Label(header, text=f"Step {index + 1}", font=("TkDefaultFont", 14, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Button(header, text="Delete step", command=lambda: editor.delete_step(index)).pack(
            side=tk.RIGHT
        )

        self.caption = tk.Text(self, height=3, wrap=tk.WORD, undo=True)
        self.caption.pack(fill=tk.X, pady=(6, 8))
        self.caption.insert("1.0", display_caption(step))
        self.caption.edit_reset()
        self.caption.bind("<FocusOut>", lambda _event: editor._commit_caption_if_changed())
        editor._bind_history_keys(self.caption)

        background = load_step_background(editor.session, editor.session_dir, step)
        self.canvas = AnnotationCanvas(self, editor, step, background)
        self.canvas.pack(anchor=tk.W)


class AnnotationCanvas(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        editor: PreviewEditor,
        step: dict[str, Any],
        background: Image.Image | None,
    ) -> None:
        self.editor = editor
        self.annotations = [
            normalized
            for item in (step.get("annotations") or [])
            if (normalized := normalize_annotation(item))
        ]
        self._photo: ImageTk.PhotoImage | None = None
        self.scale = 1.0
        self.img_w = 1
        self.img_h = 1
        self._drag_start: tuple[float, float] | None = None
        self._preview_id: int | None = None

        width, height = 200, 40
        if background is not None:
            self.img_w, self.img_h = background.size
            self.scale = min(1.0, MAX_DISPLAY_WIDTH / max(1, self.img_w))
            disp_w = max(1, int(round(self.img_w * self.scale)))
            disp_h = max(1, int(round(self.img_h * self.scale)))
            display = background.resize((disp_w, disp_h), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(display)
            width, height = disp_w, disp_h

        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=1,
            highlightbackground="#d8dee6",
            background="#f8fafc",
            cursor="crosshair",
        )
        if self._photo is not None:
            self.create_image(0, 0, image=self._photo, anchor="nw", tags=("bg",))
        else:
            self.create_text(
                width // 2,
                height // 2,
                text="No screenshot",
                fill="#64748b",
                tags=("bg",),
            )
        self.redraw()
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        return x / self.scale, y / self.scale

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale, y * self.scale

    def redraw(self) -> None:
        self.delete("overlay")
        selected = self.editor._selected
        selected_index = selected[1] if selected is not None and selected[0] is self else None
        for index, item in enumerate(self.annotations):
            self._draw_item(item, selected=index == selected_index)

    def _draw_item(self, item: dict[str, Any], *, selected: bool) -> None:
        color = str(item.get("color") or DEFAULT_OVERLAY_COLOR)
        stroke = max(1, int(round(int(item.get("stroke") or DEFAULT_OVERLAY_STROKE) * self.scale)))
        x1, y1 = self.to_canvas(item["x1"], item["y1"])
        x2, y2 = self.to_canvas(item["x2"], item["y2"])
        kind = item["type"]
        kwargs: dict[str, Any] = {"fill": color, "width": stroke, "tags": ("overlay",)}
        if selected:
            kwargs["dash"] = (6, 3)
        if kind == "arrow":
            self.create_line(x1, y1, x2, y2, arrow=tk.LAST, **kwargs)
            return
        if kind == "rect":
            self.create_rectangle(x1, y1, x2, y2, outline=color, width=stroke, dash=kwargs.get("dash"), tags=("overlay",))
            return
        if kind == "circle":
            self.create_oval(x1, y1, x2, y2, outline=color, width=stroke, dash=kwargs.get("dash"), tags=("overlay",))
            return
        size = max(8, int(round(int(item.get("size") or DEFAULT_TEXT_SIZE) * self.scale)))
        text_id = self.create_text(
            x1,
            y1,
            text=str(item.get("text") or ""),
            fill=color,
            anchor="nw",
            font=("Helvetica", size),
            tags=("overlay",),
        )
        if selected:
            bbox = self.bbox(text_id)
            if bbox:
                self.create_rectangle(*bbox, outline="#2563EB", dash=(4, 2), tags=("overlay",))

    def _on_press(self, event: tk.Event) -> None:
        if self._photo is None:
            return
        tool = self.editor.tool_var.get()
        ix, iy = self.to_image(event.x, event.y)
        if tool == "select":
            hit = self._hit_test(ix, iy)
            self.editor.select_annotation(self, hit)
            return
        if tool == "text":
            text = simpledialog.askstring("Annotation text", "Text:", parent=self.editor.window)
            if text and text.strip():
                self.editor.record_annotation_change()
                self.annotations.append(
                    {
                        "type": "text",
                        "color": self.editor.color_var.get(),
                        "stroke": self.editor.stroke_var.get(),
                        "x1": int(round(ix)),
                        "y1": int(round(iy)),
                        "x2": int(round(ix)),
                        "y2": int(round(iy)),
                        "text": text.strip(),
                        "size": DEFAULT_TEXT_SIZE,
                    }
                )
                self.editor.select_annotation(self, len(self.annotations) - 1)
                self.editor.finish_annotation_change("Text added.")
            return
        self._drag_start = (ix, iy)
        self._clear_preview()

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        ix, iy = self.to_image(event.x, event.y)
        self._draw_preview(self._drag_start[0], self._drag_start[1], ix, iy)

    def _on_release(self, event: tk.Event) -> None:
        start = self._drag_start
        self._drag_start = None
        self._clear_preview()
        if start is None:
            return
        ix, iy = self.to_image(event.x, event.y)
        if math.hypot(ix - start[0], iy - start[1]) < MIN_DRAG / self.scale:
            return
        tool = self.editor.tool_var.get()
        if tool not in {"arrow", "rect", "circle"}:
            return
        self.editor.record_annotation_change()
        self.annotations.append(
            {
                "type": tool,
                "color": self.editor.color_var.get(),
                "stroke": int(self.editor.stroke_var.get()),
                "x1": int(round(start[0])),
                "y1": int(round(start[1])),
                "x2": int(round(ix)),
                "y2": int(round(iy)),
            }
        )
        self.editor.select_annotation(self, len(self.annotations) - 1)
        self.editor.finish_annotation_change("Annotation added.")

    def _draw_preview(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self._clear_preview()
        tool = self.editor.tool_var.get()
        c1 = self.to_canvas(x1, y1)
        c2 = self.to_canvas(x2, y2)
        color = self.editor.color_var.get()
        stroke = max(1, int(round(int(self.editor.stroke_var.get()) * self.scale)))
        if tool == "arrow":
            self._preview_id = self.create_line(
                *c1, *c2, fill=color, width=stroke, arrow=tk.LAST, tags=("preview",)
            )
        elif tool == "rect":
            self._preview_id = self.create_rectangle(
                *c1, *c2, outline=color, width=stroke, tags=("preview",)
            )
        elif tool == "circle":
            self._preview_id = self.create_oval(
                *c1, *c2, outline=color, width=stroke, tags=("preview",)
            )

    def _clear_preview(self) -> None:
        self.delete("preview")
        self._preview_id = None

    def _hit_test(self, ix: float, iy: float) -> int | None:
        threshold = max(HIT_PADDING / self.scale, 6)
        for index in range(len(self.annotations) - 1, -1, -1):
            if _hits(self.annotations[index], ix, iy, threshold, self):
                return index
        return None


def _hits(
    item: dict[str, Any],
    ix: float,
    iy: float,
    threshold: float,
    canvas: AnnotationCanvas,
) -> bool:
    kind = item["type"]
    x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]
    if kind == "arrow":
        return _distance_to_segment(ix, iy, x1, y1, x2, y2) <= threshold
    if kind == "text":
        cx1, cy1 = canvas.to_canvas(x1, y1)
        size = max(8, int(round(int(item.get("size") or DEFAULT_TEXT_SIZE) * canvas.scale)))
        width = max(12, len(str(item.get("text") or "")) * size * 0.6)
        height = size * 1.3
        px, py = canvas.to_canvas(ix, iy)
        return cx1 - threshold <= px <= cx1 + width + threshold and cy1 - threshold <= py <= cy1 + height + threshold
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    if left - threshold <= ix <= right + threshold and top - threshold <= iy <= bottom + threshold:
        return True
    return False


def _distance_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _is_text_widget(widget: tk.Misc | None) -> bool:
    return isinstance(widget, (tk.Text, tk.Entry, ttk.Entry))
