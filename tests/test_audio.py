from pathlib import Path

from docrecorder.audio import ElapsedClock, write_wav_pcm16


def test_elapsed_clock_ignores_paused_time():
    ticks = iter([0.0, 1.5, 4.0, 5.0, 8.0])

    def time_fn() -> float:
        return next(ticks)

    clock = ElapsedClock(time_fn)
    clock.start()  # 0.0
    assert clock.elapsed() == 1.5
    clock.pause()  # 4.0 -> elapsed 4.0
    clock.resume()  # 5.0
    assert clock.stop() == 7.0  # 4.0 + (8.0 - 5.0)


def test_write_wav_pcm16(tmp_path: Path):
    path = tmp_path / "audio.wav"
    write_wav_pcm16(path, b"\x00\x00" * 160)
    assert path.is_file()
    assert path.stat().st_size > 44
