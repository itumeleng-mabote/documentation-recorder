from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from typing import Callable

SAMPLE_RATE = 16000
CHANNELS = 1
WHISPER_INSTALL_MESSAGE = (
    'Whisper extras are not installed. Run: pip install -e ".[whisper]"'
)


class ElapsedClock:
    """Accumulates time only while running, so pause does not advance elapsed_s."""

    def __init__(self, time_fn: Callable[[], float] | None = None) -> None:
        self._time = time_fn or time.monotonic
        self._elapsed = 0.0
        self._running_since: float | None = None

    def start(self) -> None:
        self._elapsed = 0.0
        self._running_since = self._time()

    def pause(self) -> None:
        if self._running_since is None:
            return
        self._elapsed += self._time() - self._running_since
        self._running_since = None

    def resume(self) -> None:
        if self._running_since is not None:
            return
        self._running_since = self._time()

    def stop(self) -> float:
        self.pause()
        return self._elapsed

    def elapsed(self) -> float:
        extra = 0.0
        if self._running_since is not None:
            extra = self._time() - self._running_since
        return self._elapsed + extra


def mic_available() -> bool:
    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        return False
    return True


def write_wav_pcm16(path: Path, pcm: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


class MicRecorder:
    def __init__(self, time_fn: Callable[[], float] | None = None) -> None:
        self._lock = threading.Lock()
        self._chunks: list = []
        self._stream = None
        self._clock = ElapsedClock(time_fn)
        self._paused = False

    def start(self) -> None:
        import sounddevice as sd

        self._chunks = []
        self._paused = False
        self._clock.start()

        def callback(indata, _frames, _time_info, status) -> None:
            if status:
                return
            with self._lock:
                if self._paused:
                    return
                self._chunks.append(indata.copy())

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
        )
        stream.start()
        self._stream = stream

    def pause(self) -> None:
        with self._lock:
            if self._paused:
                return
            self._paused = True
            self._clock.pause()

    def resume(self) -> None:
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            self._clock.resume()

    def elapsed_s(self) -> float:
        with self._lock:
            return self._clock.elapsed()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._clock.stop()
            self._chunks = []
            self._paused = True

    def stop(self, path: Path) -> bool:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._clock.stop()
            chunks = list(self._chunks)
            self._chunks = []
            self._paused = True
        if not chunks:
            return False
        import numpy as np

        samples = np.concatenate(chunks, axis=0).reshape(-1)
        if samples.size == 0:
            return False
        pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        write_wav_pcm16(path, pcm.tobytes())
        return path.is_file() and path.stat().st_size > 44
