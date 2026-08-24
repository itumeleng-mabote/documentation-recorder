# Documentation Recorder

A Tkinter desktop app that records a chosen application window: click positions, typed keys, and screenshots. When you stop, it writes annotated (and optional raw) PNGs plus a JSON log, Markdown guide, and HTML page. If Ollama is running, click steps are labeled with the UI control that was pressed. Optionally record a voice narration; Whisper transcribes it and Qwen rewrites each step.

Works on **macOS** and **Windows**.

## Install

Python 3.10+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

To enable microphone narration and Whisper transcription:

```bash
pip install -e ".[dev,whisper]"
```

On macOS, `pyobjc-framework-Quartz` is installed automatically for window listing and capture.

Homebrew Python builds often ship without Tk. If `python -m docrecorder` fails with `No module named '_tkinter'`, install the matching Tk package (for example `brew install python-tk@3.14`) or use the python.org installer.

## Run

```bash
python -m docrecorder
```

or:

```bash
docrecorder
```

1. Pick the target window from the dropdown (Refresh if it is not listed yet).
2. Choose an output folder (default: `./recordings`).
3. Leave **Save raw screenshots** checked if you also want unmarked PNGs.
4. Leave **Identify clicks with Ollama** checked to name clicked buttons after you stop (requires a local Ollama model; see below).
5. Optionally check **Record narration (Whisper)** and speak while you demonstrate the flow.
6. Click **Start** (or press **Cmd+Shift+R** / **Ctrl+Shift+R**).
7. Click and type in the target app. Use **Pause** to skip sensitive input such as passwords (Pause also mutes the microphone).
8. **Stop** (or the same hotkey). A session folder opens with `guide.md`, `guide.html`, `events.json`, and screenshots.

## Session output

```
recordings/2026-08-24_15-03-00/
  raw/step-01.png
  annotated/step-01.png
  crops/step-01.jpg
  audio.wav
  events.json
  guide.md
  guide.html
```

Clicks are drawn as a high-contrast circle on the annotated images. Typed text is grouped into one step until you press Enter or Tab, click, or pause typing for about 1.5 seconds.

When identification is on, Stop sends a cropped screenshot of each click to local Ollama. Successful labels become captions such as `Click **Save**.`; if Ollama is not running, captions fall back to coordinates such as `Click at (120, 48).`

When narration is on, Stop transcribes `audio.wav` with local [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (model `base`, or `DOCRECORDER_WHISPER_MODEL` to override). The same local `qwen3.5:4b-mlx` model then writes fuller step captions. If the microphone, Whisper, or Ollama is unavailable, the guide keeps the mechanical captions.

## Ollama click labels

Install [Ollama](https://ollama.com), then pull the vision model:

```bash
ollama pull qwen3.5:4b-mlx
```

The recorder talks to `http://127.0.0.1:11434` (`OLLAMA_HOST` if set) using `qwen3.5:4b-mlx` (`DOCRECORDER_OLLAMA_MODEL` to override). Crops stay on disk under `crops/` and are sent only to that local server.

Uncheck **Identify clicks with Ollama** to skip labeling. Recording itself does not wait on the model; identification runs after Stop.

## Whisper narration

Install the optional extra (`pip install -e ".[whisper]"`), then check **Record narration (Whisper)** before Start. Speak while you click and type. After Stop, faster-whisper transcribes the session WAV (model `base`, or `DOCRECORDER_WHISPER_MODEL` to override). The same local `qwen3.5:4b-mlx` model then writes fuller step captions. If the microphone, Whisper, or Ollama is unavailable, the guide keeps the mechanical captions.

The first transcription downloads the Whisper model. Later sessions reuse it.

## macOS permissions

The recorder uses global mouse/keyboard listeners and window screenshots. Grant these to the app that *launches* Python (Terminal, iTerm, VS Code/Cursor, etc.):

1. **Accessibility** — System Settings → Privacy & Security → Accessibility.
   Needed to read window titles and to listen for clicks and keys.
2. **Screen Recording** — System Settings → Privacy & Security → Screen Recording.
   Needed to capture the selected window.
3. **Microphone** — System Settings → Privacy & Security → Microphone.
   Needed only when **Record narration (Whisper)** is on.

After changing permissions, quit and relaunch the recorder.

If captures come back black or empty, Screen Recording is usually missing. If the window list has no titles, Accessibility is usually missing. If narration is silent, Microphone is usually missing.

## Privacy

Every keystroke that is recorded is stored in `events.json` and copied into the Markdown/HTML guides. Pause recording before typing passwords or other secrets. Click crops used for identification are sent only to your local Ollama process. Narration is stored as `audio.wav` plus a transcript in `events.json` and is sent only to local Whisper and Ollama.

## Tests

```bash
pytest
```
