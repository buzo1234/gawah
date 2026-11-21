"""Local page for recording voice samples. Standard library only.

Run: uv run --python 3.12 tools/recorder/server.py [lines.json] [--port 8765]
"""

import argparse
import json
import re
import shutil
import subprocess
import threading
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
AUDIO_DIR = HERE.parents[1] / "fixtures" / "audio"
STATE_FILE = AUDIO_DIR / "state.json"
EXTENSIONS = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg"}
MAX_BYTES = 50 * 1024 * 1024
LOCK = threading.Lock()


def load_lines(path: Path) -> list[dict]:
    lines = json.loads(path.read_text(encoding="utf-8"))
    if not lines or any(not {"id", "speaker", "text"} <= line.keys() for line in lines):
        raise SystemExit(f"{path}: every line needs an id, a speaker and a text")
    ids = [line["id"] for line in lines]
    # Ids become file names next to state.json, so keep them safe in a path and off that name.
    bad = [i for i in ids if not re.fullmatch(r"[A-Za-z0-9_-]+", i) or i == "state"]
    if bad or len(set(ids)) != len(ids):
        raise SystemExit(f"{path}: line ids must be unique and made of letters, digits, - and _ (bad: {bad})")
    return lines


def read_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def write_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def to_wav(original: Path) -> Path | None:
    """16 kHz mono WAV next to the original, or None if ffmpeg is missing or fails."""
    if not shutil.which("ffmpeg"):
        return None
    wav = original.with_suffix(".wav")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(original),
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
            check=True, timeout=60, stdin=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError) as error:
        print(f"ffmpeg failed for {original.name}, keeping the original only: {error}")
        wav.unlink(missing_ok=True)
        return None
    return wav


def save_recording(line: dict, ext: str, body: bytes, client_seconds: float | None) -> dict:
    with LOCK:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        original = AUDIO_DIR / f"{line['id']}.{ext}"
        original.write_bytes(body)
        # An earlier take may have come from another browser with another format.
        for old in AUDIO_DIR.glob(f"{line['id']}.*"):
            if old != original:
                old.unlink()
        wav = to_wav(original)
        seconds = client_seconds
        if wav:
            with wave.open(str(wav)) as w:
                seconds = w.getnframes() / w.getframerate()
        entry = {
            "file": original.name,
            "wav": wav.name if wav else None,
            "speaker": line["speaker"],
            "text": line["text"],
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "seconds": round(seconds, 2) if seconds is not None else None,
        }
        state = read_state()
        state[line["id"]] = entry
        write_state(state)
        return entry


class Handler(BaseHTTPRequestHandler):
    lines: list[dict] = []

    def send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, data) -> None:
        self.send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/lines":
            self.send_json(200, self.lines)
        elif path == "/api/state":
            with LOCK:
                self.send_json(200, read_state())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        prefix = "/api/recordings/"
        if not url.path.startswith(prefix):
            return self.send_json(404, {"error": "not found"})
        line_id = unquote(url.path[len(prefix):])
        line = next((l for l in self.lines if l["id"] == line_id), None)
        if line is None:
            return self.send_json(404, {"error": f"no line with id {line_id!r}"})
        media_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        ext = EXTENSIONS.get(media_type)
        if ext is None:
            return self.send_json(415, {"error": f"unsupported audio type {media_type!r}"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BYTES:
            return self.send_json(400, {"error": "empty or oversized recording"})
        body = self.rfile.read(length)
        try:
            seconds = float(parse_qs(url.query)["seconds"][0])
        except (KeyError, ValueError):
            seconds = None
        self.send_json(200, save_recording(line, ext, body, seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Record voice samples line by line.")
    parser.add_argument("lines", nargs="?", type=Path, default=HERE / "lines.json", help="lines file to read from")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    Handler.lines = load_lines(args.lines)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"{len(Handler.lines)} lines from {args.lines}")
    print(f"Saving to {AUDIO_DIR}" + ("" if shutil.which("ffmpeg") else " (ffmpeg not found, no WAV copies)"))
    print(f"Open http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
