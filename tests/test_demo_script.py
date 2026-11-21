"""The run sheet the user reads aloud and the script the dry run plays must be the same lines."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_SHEET = (ROOT / "tools" / "DEMO-RUN.md").read_text()


def test_every_line_of_both_calls_is_in_the_run_sheet_in_order():
    for no in (1, 2):
        lines = json.loads((ROOT / "fixtures" / "demo" / f"demo_call_{no}.json").read_text())["lines"]
        heading = RUN_SHEET.index(f"Call {no}:")
        at = heading
        for line in lines:
            device = "Phone" if line["speaker"] == "hirer" else "Laptop"
            row = f"| {line['line_no']} | {device}"
            at = RUN_SHEET.index(row, at)
            assert RUN_SHEET[at:RUN_SHEET.index("\n", at)].endswith(f"| {line['text']} |"), line


def test_a_recorded_line_says_what_its_recording_says():
    spoken = json.loads((ROOT / "fixtures" / "audio" / "state.json").read_text())
    for no in (1, 2):
        for line in json.loads((ROOT / "fixtures" / "demo" / f"demo_call_{no}.json").read_text())["lines"]:
            if line["audio"] != "voice":
                assert spoken[line["audio"]]["text"] == line["text"]
