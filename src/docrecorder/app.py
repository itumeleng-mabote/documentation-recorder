from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from docrecorder.audio import WHISPER_INSTALL_MESSAGE
from docrecorder.capture import CaptureError, get_capture
from docrecorder.capture.base import WindowInfo
from docrecorder.labels import unique_labels
from docrecorder.recorder import Recorder
from docrecorder.transcribe import whisper_extra_installed

HOTKEY_HINT = "Cmd+Shift+R" if sys.platform == "darwin" else "Ctrl+Shift+R"


class DocRecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Documentation Recorder")
        self.root.attributes("-topmost", True)
        self.root.resizable(True, False)
        self.root.geometry("760x210")
        self.root.minsize(640, 200)

        self.capture = get_capture()
        self.events: queue.Queue = queue.Queue()
        self._bounds: tuple[int, int, int, int] | None = None
        self.windows: list[WindowInfo] = []
        self.recorder = Recorder(self.capture, self.events, lambda: self._bounds)

        self.window_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str((Path.cwd() / "recordings").resolve()))
        self.save_raw_var = tk.BooleanVar(value=True)
        self.identify_var = tk.BooleanVar(value=True)
        self.narrate_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Idle")

        self._build()
        self.refresh_windows()
        self._sync_buttons()
        try:
            self.recorder.start_listeners()
        except Exception as exc:
            messagebox.showerror(
                "Documentation Recorder",
                f"Could not start input listeners.\n\n{exc}\n\n"
                "On macOS, grant Accessibility permission to the app that launched this recorder, then relaunch.",
            )
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._poll)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Window").grid(row=0, column=0, sticky=tk.W, **pad)
        self.window_combo = ttk.Combobox(
            frame,
            textvariable=self.window_var,
            state="readonly",
            width=50,
        )
        self.window_combo.grid(row=0, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Refresh", command=self.refresh_windows).grid(row=0, column=2, **pad)

        ttk.Label(frame, text="Output").grid(row=1, column=0, sticky=tk.W, **pad)
        ttk.Entry(frame, textvariable=self.output_var).grid(row=1, column=1, sticky=tk.EW, **pad)
        ttk.Button(frame, text="Browse", command=self._browse_output).grid(row=1, column=2, **pad)

        options = ttk.Frame(frame)
        options.grid(row=2, column=0, columnspan=3, sticky=tk.EW, **pad)
        ttk.Checkbutton(options, text="Save raw screenshots", variable=self.save_raw_var).pack(side=tk.LEFT)
        self.identify_check = ttk.Checkbutton(
            options,
            text="Identify clicks with Ollama",
            variable=self.identify_var,
        )
        self.identify_check.pack(side=tk.LEFT, padx=(16, 0))

        options2 = ttk.Frame(frame)
        options2.grid(row=3, column=0, columnspan=3, sticky=tk.EW, **pad)
        self.narrate_check = ttk.Checkbutton(
            options2,
            text="Record narration (Whisper)",
            variable=self.narrate_var,
        )
        self.narrate_check.pack(side=tk.LEFT)
        ttk.Label(options2, text=f"Hotkey: {HOTKEY_HINT}").pack(side=tk.RIGHT)

        controls = ttk.Frame(frame)
        controls.grid(row=4, column=0, columnspan=3, sticky=tk.EW, **pad)
        self.start_btn = ttk.Button(controls, text="Start", command=self._on_start)
        self.pause_btn = ttk.Button(controls, text="Pause", command=self._on_pause)
        self.stop_btn = ttk.Button(controls, text="Stop", command=self._on_stop)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(controls, textvariable=self.status_var).pack(side=tk.LEFT)

    def refresh_windows(self) -> None:
        previous_index = self.window_combo.current()
        try:
            self.windows = self.capture.list_windows(exclude_pids=[os.getpid()])
        except CaptureError as exc:
            messagebox.showerror("Documentation Recorder", str(exc))
            return
        labels = unique_labels(self.windows)
        self.window_combo["values"] = labels
        if labels:
            index = previous_index if 0 <= previous_index < len(labels) else 0
            self.window_combo.current(index)
            self.window_var.set(labels[index])
        else:
            self.window_var.set("")

    def _selected_window(self) -> WindowInfo | None:
        index = self.window_combo.current()
        if 0 <= index < len(self.windows):
            return self.windows[index]
        label = self.window_var.get()
        for window in self.windows:
            if window.label == label:
                return window
        return None

    def _on_start(self) -> None:
        if self.recorder.state == "paused":
            self.recorder.resume()
            self._sync_buttons()
            return
        window = self._selected_window()
        if window is None:
            self.status_var.set("Select a window first")
            return
        if self.narrate_var.get() and not whisper_extra_installed():
            messagebox.showwarning("Documentation Recorder", WHISPER_INSTALL_MESSAGE)
        output_dir = Path(self.output_var.get()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Documentation Recorder", f"Could not create output folder:\n{exc}")
            return
        self.recorder.start(
            window,
            output_dir,
            self.save_raw_var.get(),
            self.identify_var.get(),
            self.narrate_var.get(),
        )
        self._sync_buttons()

    def _on_pause(self) -> None:
        if self.recorder.state == "paused":
            self.recorder.resume()
        elif self.recorder.state == "recording":
            self.recorder.pause()
        self._sync_buttons()

    def _on_stop(self) -> None:
        self.recorder.stop()
        self._sync_buttons()

    def _on_hotkey(self) -> None:
        if self.recorder.state == "processing":
            return
        if self.recorder.state in {"recording", "paused"}:
            self._on_stop()
        else:
            self._on_start()

    def _browse_output(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if chosen:
            self.output_var.set(chosen)

    def _sync_buttons(self) -> None:
        state = self.recorder.state
        recording = state == "recording"
        paused = state == "paused"
        processing = state == "processing"
        busy = recording or paused or processing
        self.start_btn.configure(state=tk.DISABLED if recording or processing else tk.NORMAL)
        self.pause_btn.configure(
            text="Resume" if paused else "Pause",
            state=tk.NORMAL if recording or paused else tk.DISABLED,
        )
        self.stop_btn.configure(state=tk.NORMAL if recording or paused else tk.DISABLED)
        self.window_combo.configure(state=tk.DISABLED if busy else "readonly")
        self.identify_check.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.narrate_check.configure(state=tk.DISABLED if busy else tk.NORMAL)

    def _poll(self) -> None:
        self._update_bounds()
        self.recorder.poll_idle()
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status_var.set(payload)
                self._sync_buttons()
            elif kind == "error":
                self.status_var.set(payload)
                self._sync_buttons()
                messagebox.showwarning("Documentation Recorder", payload)
            elif kind == "stopped":
                self.status_var.set("Idle")
                self._sync_buttons()
                _open_folder(Path(payload))
            elif kind == "hotkey":
                self._on_hotkey()
        self.root.after(50, self._poll)

    def _update_bounds(self) -> None:
        try:
            self.root.update_idletasks()
            title = 36 if sys.platform == "darwin" else 40
            self._bounds = (
                int(self.root.winfo_rootx()),
                int(self.root.winfo_rooty()) - title,
                int(self.root.winfo_width()),
                int(self.root.winfo_height()) + title,
            )
        except tk.TclError:
            self._bounds = None

    def _on_close(self) -> None:
        if self.recorder.state in {"recording", "paused"}:
            self.recorder.stop()
        self.recorder.shutdown()
        self.root.destroy()


def _open_folder(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
    except OSError:
        pass


def main() -> None:
    if sys.platform not in {"darwin", "win32"}:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Documentation Recorder",
            "This app supports macOS and Windows only.",
        )
        root.destroy()
        raise SystemExit(1)
    root = tk.Tk()
    try:
        DocRecorderApp(root)
    except CaptureError as exc:
        messagebox.showerror("Documentation Recorder", str(exc))
        root.destroy()
        raise SystemExit(1) from exc
    root.mainloop()


if __name__ == "__main__":
    main()
