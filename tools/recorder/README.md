# Recorder

A local page for recording voice samples line by line. Standard library only, no outside services.

- Run: `uv run --python 3.12 tools/recorder/server.py`, then open `http://127.0.0.1:8765` (use `--port` to change it).
- Keys: space starts and stops, enter keeps the take and moves on. Click any line in the list to jump to it.
- Recordings land in `fixtures/audio/`, one per line, named from the line id (`paint-01.webm`). With `ffmpeg` installed a 16 kHz mono WAV is saved next to each one.
- `fixtures/audio/state.json` is the record of what is done: file, text read, speaker, time and length per line id. Recording a line again replaces its files and its entry. Commit the whole folder.
- Another script: `uv run --python 3.12 tools/recorder/server.py path/to/other-lines.json`. Same shape as `lines.json`: a list of `{"id", "speaker", "text"}`. Ids become file names, so keep them unique across scripts (`paint-01`, `plumber-01`).
