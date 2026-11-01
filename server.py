"""Transcriber — local transcription server (Whisper turbo via MLX).

Inputs: file upload, YouTube links and real-time microphone.
Usage: python server.py [--host 127.0.0.1] [--port 7100]
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "tmp"
TMP_DIR.mkdir(exist_ok=True)

MODEL_REPO = os.environ.get("TRANSCRIBER_MODEL", "mlx-community/whisper-large-v3-turbo")
SAMPLE_RATE = 16000

app = FastAPI(title="Transcriber")

# ------------------------------------------------------------------ model ---

_model_state = {"loaded": False, "error": None, "loading": False}


def _load_model():
    if _model_state["loaded"] or _model_state["loading"]:
        return
    _model_state["loading"] = True
    try:
        import mlx_whisper  # noqa: F401
        from mlx_whisper.load_models import load_model

        load_model(MODEL_REPO)
        _model_state["loaded"] = True
    except Exception as exc:  # noqa: BLE001
        _model_state["error"] = str(exc)
    finally:
        _model_state["loading"] = False


@app.on_event("startup")
async def _startup():
    threading.Thread(target=_load_model, daemon=True).start()


@app.get("/api/status")
async def status():
    return {**_model_state, "model": MODEL_REPO}


def _run_transcribe(audio, language=None, word_timestamps=False):
    import mlx_whisper

    opts = {
        "path_or_hf_repo": MODEL_REPO,
        "verbose": False,
        "word_timestamps": word_timestamps,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
        "hallucination_silence_threshold": 1.0,
    }
    if language and language != "auto":
        opts["language"] = language
    return mlx_whisper.transcribe(audio, **opts)


# -------------------------------------------------------------------- srt ---

def _fmt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(segments) -> str:
    blocks = []
    for i, seg in enumerate(segments, 1):
        blocks.append(f"{i}\n{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}\n{seg['text'].strip()}\n")
    return "\n".join(blocks)


# -------------------------------------------------------------- endpoints ---

@app.post("/api/transcribe/file")
async def transcribe_file(file: UploadFile = File(...), language: str = Form("auto")):
    if not _model_state["loaded"]:
        raise HTTPException(503, "Model still loading, try again in a few seconds.")
    suffix = Path(file.filename or "audio").suffix or ".bin"
    tmp = TMP_DIR / f"up-{uuid.uuid4().hex}{suffix}"
    try:
        tmp.write_bytes(await file.read())
        result = await asyncio.to_thread(_run_transcribe, str(tmp), language)
        return {
            "text": result["text"].strip(),
            "language": result.get("language"),
            "srt": _to_srt(result.get("segments", [])),
        }
    finally:
        tmp.unlink(missing_ok=True)


@app.post("/api/transcribe/youtube")
async def transcribe_youtube(payload: dict):
    if not _model_state["loaded"]:
        raise HTTPException(503, "Model still loading, try again in a few seconds.")
    url = (payload.get("url") or "").strip()
    language = payload.get("language", "auto")
    if not url:
        raise HTTPException(400, "Empty URL.")

    job = TMP_DIR / f"yt-{uuid.uuid4().hex}"
    job.mkdir()
    try:
        cmd = [
            "yt-dlp", "--no-playlist", "-x", "--audio-format", "wav",
            "--audio-quality", "0", "-o", str(job / "audio.%(ext)s"), url,
        ]
        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=1800
        )
        if proc.returncode != 0:
            raise HTTPException(400, f"yt-dlp failed: {proc.stderr.strip()[-400:]}")
        files = list(job.glob("audio.*"))
        if not files:
            raise HTTPException(400, "Could not extract audio.")
        result = await asyncio.to_thread(_run_transcribe, str(files[0]), language)
        return {
            "text": result["text"].strip(),
            "language": result.get("language"),
            "srt": _to_srt(result.get("segments", [])),
        }
    finally:
        for f in job.glob("*"):
            f.unlink(missing_ok=True)
        job.rmdir()


# ------------------------------------------------------------------- live ---

MIN_WINDOW_S = 4.0      # transcribe once this much new audio has arrived
OVERLAP_S = 0.5         # overlap so words are not cut at window edges
POLL_S = 1.0


def _decode_webm_to_pcm(path: Path) -> np.ndarray:
    """Decode the accumulated webm stream to 16 kHz mono float32 PCM."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _dedupe_overlap(prev_words, new_words, max_k=6):
    """Drop words repeated at the boundary between consecutive windows."""
    k = min(max_k, len(prev_words), len(new_words))
    while k > 0:
        if [w.lower().strip(".,!?;:") for w in prev_words[-k:]] == [
            w.lower().strip(".,!?;:") for w in new_words[:k]
        ]:
            return new_words[k:]
        k -= 1
    return new_words


@app.websocket("/ws/live")
async def live_ws(ws: WebSocket):
    await ws.accept()
    language = ws.query_params.get("language", "auto")

    session = TMP_DIR / f"live-{uuid.uuid4().hex}.webm"
    state = {
        "processed_samples": 0,
        "confirmed_words": [],
        "running": True,
        "lock": asyncio.Lock(),
        "file": open(session, "wb"),
        "bytes": 0,
    }

    async def process(final=False):
        async with state["lock"]:
            state["file"].flush()
            pcm = await asyncio.to_thread(_decode_webm_to_pcm, session)
            total = len(pcm)
            new_samples = total - state["processed_samples"]
            if new_samples < int(MIN_WINDOW_S * SAMPLE_RATE) and not final:
                return
            if new_samples <= 0:
                return

            start = max(0, state["processed_samples"] - int(OVERLAP_S * SAMPLE_RATE))
            window = pcm[start:total]
            # very low energy -> silence, skip
            if float(np.sqrt(np.mean(window**2) + 1e-12)) < 0.005:
                state["processed_samples"] = total
                return

            kwargs = {}
            if state["confirmed_words"]:
                kwargs["initial_prompt"] = " ".join(state["confirmed_words"][-40:])

            def _do():
                import mlx_whisper
                opts = {
                    "path_or_hf_repo": MODEL_REPO,
                    "verbose": False,
                    "condition_on_previous_text": False,
                    "no_speech_threshold": 0.6,
                    "hallucination_silence_threshold": 1.0,
                    **kwargs,
                }
                if language and language != "auto":
                    opts["language"] = language
                return mlx_whisper.transcribe(window, **opts)

            result = await asyncio.to_thread(_do)
            text = result["text"].strip()
            state["processed_samples"] = total
            if not text:
                return
            new_words = _dedupe_overlap(state["confirmed_words"], text.split())
            if new_words:
                state["confirmed_words"].extend(new_words)
                await ws.send_json({"type": "append", "text": " ".join(new_words)})

    async def ticker():
        try:
            while state["running"]:
                await asyncio.sleep(POLL_S)
                if state["bytes"] > 0:
                    await process(final=False)
        except Exception:  # noqa: BLE001
            pass

    tick_task = asyncio.create_task(ticker())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                state["file"].write(msg["bytes"])
                state["bytes"] += len(msg["bytes"])
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "stop":
                    await asyncio.sleep(0.6)  # let the last chunks arrive
                    await process(final=True)
                    await ws.send_json({"type": "done"})
                    break
    except WebSocketDisconnect:
        pass
    finally:
        state["running"] = False
        tick_task.cancel()
        state["file"].close()
        session.unlink(missing_ok=True)


# ----------------------------------------------------------------- static ---

@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "7100")))
    args, _ = parser.parse_known_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
