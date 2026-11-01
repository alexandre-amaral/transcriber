# Transcriber

Fully local audio transcription for macOS (Apple Silicon), with a web UI.
No cloud, no API keys — audio never leaves your machine.

## Features

- File upload — drag and drop any audio/video file (mp3, wav, m4a, mp4, mkv…)
- YouTube — paste a link, audio is extracted with yt-dlp and transcribed
- Real time — live microphone transcription over WebSocket
- 99 languages with automatic detection (Whisper large-v3-turbo)
- Export as `.txt` and `.srt`
- Runs on GPU via MLX/Metal — roughly 20–30x real time on an M5

## Stack

| Component | Purpose |
|---|---|
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) | Whisper `large-v3-turbo` optimized for Apple Silicon |
| FastAPI + Uvicorn | HTTP backend and WebSocket |
| yt-dlp | Audio extraction from YouTube links |
| ffmpeg | Format conversion and stream decoding |

## Setup

Prerequisites: macOS on Apple Silicon and [Homebrew](https://brew.sh).

```bash
brew install ffmpeg yt-dlp uv

git clone https://github.com/alexandre-amaral/transcriber.git
cd transcriber

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python \
  mlx-whisper fastapi "uvicorn[standard]" python-multipart websockets
```

Without `uv`:

```bash
python3 -m venv .venv
./.venv/bin/pip install mlx-whisper fastapi "uvicorn[standard]" python-multipart websockets
```

## Run

```bash
npm run dev
# or directly:
./.venv/bin/python server.py --port 7100
```

Open http://localhost:7100. On first run the model (~1.5 GB) is downloaded from
Hugging Face and cached in `~/.cache/huggingface`. The status indicator at the
top of the page shows when it is ready.

## Usage

- **File** — drop a file, pick a language (or auto-detect), transcribe, download `.txt`/`.srt`.
- **YouTube** — paste a video URL and transcribe. Works with any yt-dlp supported link.
- **Live** — start recording and speak; text appears in ~4-second windows.

To capture meetings (your mic plus other participants' audio):

```bash
brew install blackhole-2ch
```

Then open macOS **Audio MIDI Setup**, create an aggregate device combining your
microphone and BlackHole, and select it as the input device.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TRANSCRIBER_MODEL` | `mlx-community/whisper-large-v3-turbo` | Hugging Face model repo (e.g. `mlx-community/whisper-large-v3` for max quality) |
| `PORT` / `HOST` | `7100` / `127.0.0.1` | Server bind address |

## How live mode works

The browser captures the microphone with `MediaRecorder` (webm/opus) and streams
chunks over a WebSocket. The server decodes the accumulated stream to 16 kHz PCM
with ffmpeg and transcribes ~4-second windows with 0.5 s of overlap, removing
duplicated words at window boundaries. The model stays loaded in memory between
windows, so latency stays low.

## Project layout

```
transcriber/
├── server.py            # FastAPI backend (file, YouTube, live WebSocket)
├── static/index.html    # Web UI (single page, no build step)
├── package.json         # npm run dev starts the server
└── tmp/                 # temporary files (cleaned automatically)
```

## License

MIT
