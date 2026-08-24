from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pynput import keyboard, mouse

from docrecorder.annotator import annotate_click, crop_around_click
from docrecorder.audio import MicRecorder, WHISPER_INSTALL_MESSAGE, mic_available
from docrecorder.capture.base import CaptureError, WindowInfo
from docrecorder.capture.coords import point_in_rect, scale_from_image, to_local
from docrecorder.exporter import write_session
from docrecorder.rewrite import rewrite_captions
from docrecorder.transcribe import transcribe_wav, whisper_available, whisper_model
from docrecorder.typing_buffer import TypingBuffer
from docrecorder.vision import identify_clicks

START_DELAY_SECONDS = 0.4
IDLE_SECONDS = 1.5
HOTKEY_DEBOUNCE_SECONDS = 0.5
RecorderBounds = Callable[[], tuple[int, int, int, int] | None]


class Recorder:
    def __init__(self, capture, events: queue.Queue, get_recorder_bounds: RecorderBounds) -> None:
        self.capture = capture
        self.events = events
        self.get_recorder_bounds = get_recorder_bounds

        self._lock = threading.Lock()
        self._state = "idle"
        self._armed_at = 0.0
        self._last_hotkey_at = 0.0
        self._window_id: int | None = None
        self._session_dir: Path | None = None
        self._session: dict[str, Any] | None = None
        self._save_raw = True
        self._identify_clicks = False
        self._rewrite = False
        self._mic: MicRecorder | None = None
        self._buffer = TypingBuffer(idle_seconds=IDLE_SECONDS)
        self._pressed: set[object] = set()
        self._mouse_listener: mouse.Listener | None = None
        self._keyboard_listener: keyboard.Listener | None = None
        self._finish_thread: threading.Thread | None = None

    @property
    def state(self) -> str:
        return self._state

    def start_listeners(self) -> None:
        if self._mouse_listener is not None:
            return
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def shutdown(self) -> None:
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is not None:
                listener.stop()
        self._mouse_listener = None
        self._keyboard_listener = None
        thread = self._finish_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=600)
        with self._lock:
            mic = self._mic
            self._mic = None
        if mic is not None:
            mic.close()

    def start(
        self,
        window: WindowInfo,
        output_dir: Path,
        save_raw: bool,
        identify_clicks: bool = False,
        record_audio: bool = False,
    ) -> None:
        with self._lock:
            if self._state in {"recording", "processing"}:
                return
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            session_dir = output_dir / stamp
            (session_dir / "annotated").mkdir(parents=True, exist_ok=True)
            if save_raw:
                (session_dir / "raw").mkdir(parents=True, exist_ok=True)
            if identify_clicks:
                (session_dir / "crops").mkdir(parents=True, exist_ok=True)
            self._window_id = window.window_id
            self._session_dir = session_dir
            self._save_raw = save_raw
            self._identify_clicks = identify_clicks
            self._rewrite = record_audio
            self._mic = None
            self._buffer = TypingBuffer(idle_seconds=IDLE_SECONDS)
            self._session = {
                "window_title": window.title or window.app_name,
                "app_name": window.app_name or window.title,
                "platform": sys.platform,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "ended_at": None,
                "window_size": [int(round(window.width)), int(round(window.height))],
                "scale": 1.0,
                "steps": [],
            }
            self._state = "recording"
            self._armed_at = time.monotonic() + START_DELAY_SECONDS
        warning = self._start_mic() if record_audio else None
        if warning:
            self._emit("error", warning)
        self._emit("status", self._status_text())

    def pause(self) -> None:
        with self._lock:
            if self._state != "recording":
                return
            self._commit_type_locked()
            self._state = "paused"
            if self._mic is not None:
                self._mic.pause()
        self._emit("status", self._status_text())

    def resume(self) -> None:
        with self._lock:
            if self._state != "paused":
                return
            self._state = "recording"
            self._armed_at = time.monotonic() + START_DELAY_SECONDS
            if self._mic is not None:
                self._mic.resume()
        self._emit("status", self._status_text())

    def stop(self) -> Path | None:
        with self._lock:
            if self._state == "processing":
                return None
            if self._state not in {"recording", "paused"} or self._session is None or self._session_dir is None:
                self._state = "idle"
                self._emit("status", "Idle")
                return None
            self._commit_type_locked()
            self._session["ended_at"] = datetime.now(timezone.utc).isoformat()
            session = dict(self._session)
            session["steps"] = [dict(step) for step in self._session["steps"]]
            session_dir = self._session_dir
            should_identify = self._identify_clicks and any(
                step.get("type") == "click" and step.get("screenshot_crop") for step in session["steps"]
            )
            should_rewrite = self._rewrite and bool(session["steps"])
            mic = self._mic
            self._mic = None
            self._window_id = None
            self._session = None
            self._session_dir = None
            self._identify_clicks = False
            self._rewrite = False
            if should_identify or should_rewrite:
                self._state = "processing"
            else:
                self._state = "idle"
        if mic is not None:
            wav_path = session_dir / "audio.wav"
            try:
                if mic.stop(wav_path):
                    session["audio"] = "audio.wav"
                else:
                    session.pop("audio", None)
            except Exception as exc:
                session.pop("audio", None)
                self._emit("error", f"Could not save microphone audio: {exc}")
        if should_identify or should_rewrite:
            self._emit("status", "Processing…")
            thread = threading.Thread(
                target=self._finish_session,
                args=(session, session_dir, should_identify, should_rewrite),
                daemon=True,
            )
            self._finish_thread = thread
            thread.start()
        else:
            self._finish_session(session, session_dir, False, False)
        return session_dir

    def _finish_session(
        self,
        session: dict[str, Any],
        session_dir: Path,
        identify: bool,
        rewrite: bool,
    ) -> None:
        warnings: list[str] = []
        try:
            if identify:
                def on_progress(current: int, total: int) -> None:
                    self._emit("status", f"Identifying clicks {current}/{total}…")

                warning = identify_clicks(session, session_dir, on_progress=on_progress)
                if warning:
                    warnings.append(warning)
            if rewrite:
                audio_warning = self._transcribe_session(session, session_dir)
                if audio_warning:
                    warnings.append(audio_warning)
                self._emit("status", "Writing steps…")
                warning = rewrite_captions(session)
                if warning:
                    warnings.append(warning)
            write_session(session, session_dir)
        except Exception as exc:
            warnings.append(str(exc))
        finally:
            with self._lock:
                self._state = "idle"
        if warnings:
            self._emit("error", "\n\n".join(warnings))
        self._emit("stopped", str(session_dir))
        self._emit("status", "Idle")

    def _transcribe_session(self, session: dict[str, Any], session_dir: Path) -> str | None:
        audio_name = session.get("audio")
        wav_path = session_dir / str(audio_name) if audio_name else None
        if wav_path is None or not wav_path.is_file() or wav_path.stat().st_size <= 44:
            return None
        if not whisper_available():
            return WHISPER_INSTALL_MESSAGE
        self._emit("status", "Transcribing audio…")
        try:
            result = transcribe_wav(wav_path)
        except Exception as exc:
            return f"Whisper transcription failed: {exc}"
        session["transcript"] = result.get("text") or ""
        session["transcript_segments"] = result.get("segments") or []
        session["whisper_model"] = result.get("model") or whisper_model()
        return None

    def _start_mic(self) -> str | None:
        if not mic_available():
            return None
        try:
            mic = MicRecorder()
            mic.start()
        except Exception as exc:
            return (
                f"Could not start the microphone: {exc}\n\n"
                "On macOS, grant Microphone permission to the app that launched this recorder, then relaunch."
            )
        with self._lock:
            if self._state != "recording" or self._session is None:
                mic.close()
                return None
            self._mic = mic
            self._session["audio"] = "audio.wav"
            self._session["audio_started_at"] = datetime.now(timezone.utc).isoformat()
        return None

    def poll_idle(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._state != "recording":
                return
            if self._buffer.idle_due(now):
                self._commit_type_locked()
                self._emit("status", self._status_text())

    def _on_click(self, x: float, y: float, button: mouse.Button, pressed: bool) -> None:
        if not pressed:
            return
        if self._in_recorder(x, y):
            return
        with self._lock:
            if not self._is_armed():
                return
            self._commit_type_locked()
            window = self._refresh_window_locked()
            if window is None:
                self._pause_with_error_locked(
                    "The selected window was closed or is no longer available."
                )
                return
            if not point_in_rect(x, y, window.x, window.y, window.width, window.height):
                return
            local_x, local_y = to_local(x, y, window.x, window.y)
            try:
                image = self.capture.capture(window.window_id)
            except CaptureError as exc:
                self._pause_with_error_locked(str(exc))
                return
            scale = scale_from_image(image.width, image.height, window.width, window.height)
            self._session["scale"] = scale
            self._session["window_size"] = [int(round(window.width)), int(round(window.height))]
            step_index = len(self._session["steps"]) + 1
            raw_name = f"step-{step_index:02d}.png"
            annotated = annotate_click(image, local_x, local_y, scale)
            annotated_rel = f"annotated/{raw_name}"
            annotated.save(self._session_dir / annotated_rel)
            step = {
                "index": step_index,
                "type": "click",
                "button": getattr(button, "name", str(button)),
                "x": int(round(local_x)),
                "y": int(round(local_y)),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "screenshot_annotated": annotated_rel,
            }
            elapsed = self._elapsed_s_locked()
            if elapsed is not None:
                step["elapsed_s"] = elapsed
            if self._save_raw:
                raw_rel = f"raw/{raw_name}"
                (self._session_dir / "raw").mkdir(parents=True, exist_ok=True)
                image.save(self._session_dir / raw_rel)
                step["screenshot_raw"] = raw_rel
            if self._identify_clicks:
                crop = crop_around_click(image, local_x, local_y, scale)
                crop_rel = f"crops/step-{step_index:02d}.jpg"
                (self._session_dir / "crops").mkdir(parents=True, exist_ok=True)
                crop.save(self._session_dir / crop_rel, format="JPEG", quality=85)
                step["screenshot_crop"] = crop_rel
            self._session["steps"].append(step)
            self._emit("status", self._status_text())

    def _on_press(self, key) -> None:
        self._pressed.add(key)
        if self._is_hotkey():
            now = time.monotonic()
            if now - self._last_hotkey_at >= HOTKEY_DEBOUNCE_SECONDS:
                self._last_hotkey_at = now
                self._emit("hotkey", "toggle")
            return
        with self._lock:
            if not self._is_armed():
                return
            if self._has_shortcut_modifier():
                return
            now = time.monotonic()
            if self._buffer.idle_due(now):
                self._commit_type_locked()
            special = _special_key(key)
            if special == "backspace":
                self._buffer.backspace(now)
                return
            if special in {"enter", "tab"}:
                self._commit_type_locked()
                self._emit("status", self._status_text())
                return
            char = _printable_char(key)
            if char is None:
                return
            self._buffer.push_char(char, now)

    def _on_release(self, key) -> None:
        self._pressed.discard(key)
        for candidate in list(self._pressed):
            if _key_equal(candidate, key):
                self._pressed.discard(candidate)

    def _commit_type_locked(self) -> None:
        text = self._buffer.flush()
        if not text or self._session is None or self._session_dir is None or self._window_id is None:
            return
        window = self._refresh_window_locked()
        if window is None:
            step_index = len(self._session["steps"]) + 1
            self._session["steps"].append(
                {
                    "index": step_index,
                    "type": "type",
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **self._elapsed_fields_locked(),
                }
            )
            self._pause_with_error_locked(
                "The selected window was closed or is no longer available."
            )
            return
        try:
            image = self.capture.capture(window.window_id)
        except CaptureError as exc:
            step_index = len(self._session["steps"]) + 1
            self._session["steps"].append(
                {
                    "index": step_index,
                    "type": "type",
                    "text": text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    **self._elapsed_fields_locked(),
                }
            )
            self._pause_with_error_locked(str(exc))
            return
        scale = scale_from_image(image.width, image.height, window.width, window.height)
        self._session["scale"] = scale
        self._session["window_size"] = [int(round(window.width)), int(round(window.height))]
        step_index = len(self._session["steps"]) + 1
        raw_name = f"step-{step_index:02d}.png"
        annotated_rel = f"annotated/{raw_name}"
        image.save(self._session_dir / annotated_rel)
        step = {
            "index": step_index,
            "type": "type",
            "text": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screenshot_annotated": annotated_rel,
        }
        elapsed = self._elapsed_s_locked()
        if elapsed is not None:
            step["elapsed_s"] = elapsed
        if self._save_raw:
            raw_rel = f"raw/{raw_name}"
            (self._session_dir / "raw").mkdir(parents=True, exist_ok=True)
            image.save(self._session_dir / raw_rel)
            step["screenshot_raw"] = raw_rel
        self._session["steps"].append(step)

    def _refresh_window_locked(self) -> WindowInfo | None:
        if self._window_id is None:
            return None
        return self.capture.get_window(self._window_id)

    def _elapsed_s_locked(self) -> float | None:
        if self._mic is None:
            return None
        return round(self._mic.elapsed_s(), 2)

    def _elapsed_fields_locked(self) -> dict[str, float]:
        elapsed = self._elapsed_s_locked()
        if elapsed is None:
            return {}
        return {"elapsed_s": elapsed}

    def _pause_with_error_locked(self, message: str) -> None:
        if self._state == "recording":
            self._state = "paused"
            self._buffer.flush()
            if self._mic is not None:
                self._mic.pause()
        self._emit("error", message)
        self._emit("status", self._status_text())

    def _is_armed(self) -> bool:
        return self._state == "recording" and time.monotonic() >= self._armed_at

    def _in_recorder(self, x: float, y: float) -> bool:
        bounds = self.get_recorder_bounds()
        if bounds is None:
            return False
        rx, ry, rw, rh = bounds
        return point_in_rect(x, y, rx, ry, rw, rh)

    def _status_text(self) -> str:
        steps = 0
        if self._session is not None:
            steps = len(self._session["steps"])
        if self._state == "recording":
            prefix = "Recording audio" if self._mic is not None else "Recording"
            return f"{prefix} · {steps} steps"
        if self._state == "paused":
            return f"Paused · {steps} steps"
        if self._state == "processing":
            return "Processing…"
        return "Idle"

    def _is_hotkey(self) -> bool:
        has_shift = any(_is_shift(k) for k in self._pressed)
        has_mod = any(_is_primary_mod(k) for k in self._pressed)
        has_r = any(_is_char(k, "r") for k in self._pressed)
        return has_shift and has_mod and has_r

    def _has_shortcut_modifier(self) -> bool:
        return any(_is_cmd(k) or _is_ctrl(k) or _is_alt(k) for k in self._pressed)

    def _emit(self, kind: str, payload: str) -> None:
        self.events.put((kind, payload))


def _printable_char(key) -> str | None:
    if key == keyboard.Key.space:
        return " "
    char = getattr(key, "char", None)
    if not char:
        return None
    if char.isprintable() and len(char) == 1:
        return char
    return None


def _special_key(key) -> str | None:
    mapping = {
        keyboard.Key.backspace: "backspace",
        keyboard.Key.enter: "enter",
        keyboard.Key.tab: "tab",
    }
    return mapping.get(key)


def _is_shift(key) -> bool:
    return key in {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}


def _is_ctrl(key) -> bool:
    return key in {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}


def _is_cmd(key) -> bool:
    names = {"cmd", "cmd_l", "cmd_r"}
    return getattr(key, "name", "") in names or key in {
        getattr(keyboard.Key, "cmd", None),
        getattr(keyboard.Key, "cmd_l", None),
        getattr(keyboard.Key, "cmd_r", None),
    }


def _is_alt(key) -> bool:
    return key in {
        keyboard.Key.alt,
        keyboard.Key.alt_l,
        keyboard.Key.alt_r,
        getattr(keyboard.Key, "alt_gr", None),
    }


def _is_primary_mod(key) -> bool:
    if sys.platform == "darwin":
        return _is_cmd(key)
    return _is_ctrl(key)


def _is_char(key, expected: str) -> bool:
    char = getattr(key, "char", None)
    return isinstance(char, str) and char.lower() == expected


def _key_equal(left, right) -> bool:
    return left == right or getattr(left, "vk", None) == getattr(right, "vk", None)
