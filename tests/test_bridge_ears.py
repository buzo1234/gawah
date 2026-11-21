import asyncio
import io
import wave

import httpx
import numpy as np
import pytest
from bridge_world import SILENT_FRAME, SPOKEN, frames, recorded, world  # noqa: F401

from app.config import Settings
from app.contracts import Deal, Person, Role
from app.ears.transcribe import Transcriber, prompt_for
from app.ears.vad import END_SILENCE, FRAME_SECONDS, RATE, Segmenter
from fakes import RAMESH, SUNITA

GAP = 1.5  # silence between one recorded line and the next, in the tests below


async def start_call(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)


def lines_in(segmenter: Segmenter, pcm: bytes, at: float) -> list:
    found = []
    for i, frame in enumerate(frames(pcm)):
        line = segmenter.feed(frame, at + i * FRAME_SECONDS)
        if line:
            found.append((line, at + (i + 1) * FRAME_SECONDS))  # the line, and when we knew it had ended
    return found


def loud_part(pcm: bytes) -> tuple[float, float]:
    """Where the words are in one recorded line, found a different way from the segmenter:
    the stretch between the first and last tenth of a second within 12 dB of the loudest."""
    audio = np.frombuffer(pcm, dtype=np.int16).astype(float)
    tenths = audio[: len(audio) // 1600 * 1600].reshape(-1, 1600)
    spectrum = np.abs(np.fft.rfft(tenths, axis=1)) ** 2
    band = spectrum[:, 50:340].sum(axis=1)  # 500-3400 Hz
    strong = np.nonzero(band > band.max() / 16)[0]
    return strong[0] / 10, (strong[-1] + 1) / 10


@pytest.mark.parametrize("speaker", ["Sunita", "Ramesh"])
def test_end_of_line_detection_on_the_recorded_lines(speaker):
    """One person's side of the 24-line call: their own lines, silence while the other talks."""
    segmenter, at, pieces = Segmenter(), 0.0, 0
    for name in sorted(SPOKEN):
        pcm = recorded(name)
        seconds = len(pcm) / 2 / RATE
        mine = SPOKEN[name]["speaker"] == speaker
        found = lines_in(segmenter, (pcm if mine else bytes(len(pcm))) + bytes(int(GAP * RATE) * 2), at)
        if not mine:
            assert found == [], f"{name}: heard a line in silence"
        else:
            spoken = [line for line, _ in found if not line.is_noise]
            first_word, last_word = loud_part(pcm)
            assert len(spoken) == 1, f"{name}: {len(spoken)} lines for one spoken line"
            # Every piece lies inside this recording: no line runs into the next one.
            assert all(at - 0.01 <= line.start < line.end <= at + seconds + 0.1 for line in spoken), name
            assert spoken[0].start <= at + first_word + 0.4, f"{name}: the start was missed"
            assert spoken[-1].end >= at + last_word - 0.4, f"{name}: the end was missed"
            # We know the line is over soon after the last word: the silence we wait for, and no more.
            _, known_at = found[-1]
            assert known_at - spoken[-1].end == pytest.approx(END_SILENCE, abs=0.03), name
            # The audio handed to transcription covers the line, with a little kept either side.
            for line in spoken:
                assert line.end - line.start <= len(line.pcm) / 2 / RATE <= line.end - line.start + 0.45
        at += seconds + GAP


def noise(seconds: float, kind: str, seed: int, level: float = -40.0) -> np.ndarray:
    """Steady noise at `level` dB with a sharp click every second or two. "room" has most of
    its energy below 500 Hz, like the hum and rumble a laptop microphone picks up in a quiet
    room; "hiss" is white, which puts about 15 dB more of it in the voice band."""
    rng = np.random.default_rng(seed)
    count = int(seconds * RATE)
    sound = rng.standard_normal(count)
    if kind == "room":
        spectrum = np.fft.rfft(sound)
        spectrum /= np.maximum(np.fft.rfftfreq(count, 1 / RATE), 40.0)
        sound = np.fft.irfft(spectrum, count)
    sound *= 32768 * 10 ** (level / 20) / np.sqrt(np.mean(sound * sound))
    at = 1.0
    while at < seconds - 0.1:
        start, length = int(at * RATE), int(rng.integers(16, 80))  # 1 to 5 ms
        sound[start : start + length] += rng.choice([-1, 1]) * rng.uniform(8000, 20000) * np.exp(-np.arange(length) / 20)
        at += rng.uniform(0.7, 2.5)
    return sound


def as_pcm(sound: np.ndarray) -> bytes:
    return np.clip(sound, -32768, 32767).astype(np.int16).tobytes()


@pytest.mark.parametrize("speaker", ["Sunita", "Ramesh"])
def test_recorded_lines_over_room_noise_and_clicks_still_give_one_line_each(speaker):
    spoken_at, parts, at = [], [], 0.0
    for name in sorted(SPOKEN):
        pcm = np.frombuffer(recorded(name), dtype=np.int16).astype(float)
        mine = SPOKEN[name]["speaker"] == speaker
        parts += [pcm if mine else np.zeros(len(pcm)), np.zeros(int(GAP * RATE))]
        if mine:
            spoken_at.append((name, at, at + len(pcm) / RATE))
        at += len(pcm) / RATE + GAP
    track = np.concatenate(parts)
    track += noise(len(track) / RATE, "room", seed=5)[: len(track)]
    found = [line for line, _ in lines_in(Segmenter(), as_pcm(track), 0.0)]
    assert found, "nothing heard at all"
    lines = [line for line in found if not line.is_noise]
    for name, start, end in spoken_at:
        mine = [line for line in lines if line.start < end and line.end > start]
        assert len(mine) == 1, f"{name}: {len(mine)} lines for one spoken line"
        assert start - 0.3 <= mine[0].start and mine[0].end <= end + 0.3, f"{name}: ran into the next line"
    assert len(lines) == len(spoken_at) == 12  # and nothing in the gaps, where there is only noise


@pytest.mark.parametrize("kind", ["room", "hiss"])
def test_noise_alone_gives_no_lines(kind):
    found = lines_in(Segmenter(), as_pcm(noise(180.0, kind, seed=9)), 0.0)
    assert [line for line, _ in found if not line.is_noise] == []


async def test_noise_alone_on_a_call_makes_no_transcription_calls(world):
    await start_call(world)
    world.talk(hirer=as_pcm(noise(60.0, "room", seed=1)), worker=as_pcm(noise(60.0, "hiss", seed=2)))
    await world.settle()
    assert world.transcribed == [] and world.named("transcript.line") == []
    world.talk(worker=recorded("paint-23"), seconds=3)  # and it has not gone deaf
    await world.settle()
    assert [e.speaker for e in world.named("transcript.line")] == [Role.WORKER]


async def test_a_muted_track_is_silence_on_the_timeline_and_not_an_absence(world):
    await start_call(world)
    world.talk(worker=recorded("paint-23"), seconds=3)
    world.room().muted("worker", True)  # the phone's screen locked
    world.talk(seconds=5)  # a muted track delivers digital silence...
    world.talk(seconds=3, no_frames_from="worker")  # ...or nothing at all
    await asyncio.sleep(0.3)  # longer than the "gone" limit
    world.room().muted("worker", False)
    world.talk(worker=recorded("paint-23"), seconds=3)
    await world.settle()
    assert world.named("call.ended") == [] and world.room().present == {Role.HIRER, Role.WORKER}
    first, second = world.named("transcript.line")
    assert 0.5 < first.start < 1.0 and 11.0 < second.start < 12.0  # 3 s + 5 s + 3 s later
    world.room().left("hirer"), world.room().left("worker")
    ended = await world.ended()
    with wave.open(io.BytesIO(world.uploads[ended.recording_keys["worker"]])) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    assert len(audio) == round(ended.duration * RATE) == 14 * RATE
    assert not audio[3 * RATE : 11 * RATE].any()
    assert np.array_equal(audio[: 3 * RATE], audio[11 * RATE :])  # the same three seconds, 11 s on, to the sample


def test_short_replies_are_kept_whole():
    for name, text in (("paint-12", "Haan theek hai."), ("paint-22", "Pakka?"), ("paint-23", "Pakka.")):
        assert SPOKEN[name]["text"] == text
        [(line, _)] = lines_in(Segmenter(), recorded(name) + bytes(RATE * 2), 0.0)
        assert not line.is_noise and line.end - line.start >= 0.3


def burst(seconds: float, level: float = 6000, seed: int = 1) -> bytes:
    noise = np.random.default_rng(seed).standard_normal(int(seconds * RATE))
    return (noise * level).astype(np.int16).tobytes()


def test_clicks_knocks_and_steady_noise_are_not_lines():
    hiss = burst(8.0, level=40)  # a live microphone's background
    for sound in (burst(0.03), burst(0.08, level=12000), bytes(RATE)):
        segmenter = Segmenter()
        lines_in(segmenter, hiss, 0.0)
        found = lines_in(segmenter, sound + hiss, 8.0)
        assert [line for line, _ in found if not line.is_noise] == []
    # Noise that starts and does not stop is taken for one line at most, then becomes the background.
    segmenter = Segmenter()
    lines_in(segmenter, hiss, 0.0)
    found = lines_in(segmenter, burst(60.0, level=1500), 8.0)
    assert len(found) <= 1 and not segmenter.speaking


def test_a_line_that_never_pauses_is_cut_so_it_cannot_hold_the_transcript_back():
    talk = recorded("paint-03")[: int(4.0 * RATE) * 2] * 8  # 32 s with no half-second pause
    found = lines_in(Segmenter(), bytes(RATE) + talk + bytes(RATE * 2), 0.0)
    assert len(found) >= 2 and all(line.end - line.start <= 20.0 for line, _ in found)


async def test_lines_are_numbered_and_timed_across_both_speakers(world):
    await start_call(world)
    # Sunita 22 ("Pakka?"), then Ramesh 23 ("Pakka.") while she is quiet, then Sunita 12.
    world.talk(hirer=recorded("paint-22"), seconds=4)
    world.talk(worker=recorded("paint-23"), seconds=3)
    world.talk(hirer=recorded("paint-12"), seconds=4)
    await world.settle()
    lines = world.named("transcript.line")
    assert [(e.line_no, e.speaker, e.text) for e in lines] == [
        (1, Role.HIRER, "line 1"), (2, Role.WORKER, "line 2"), (3, Role.HIRER, "line 3")]
    # Seconds from time zero. The word starts 1.05 s into paint-22 and 0.74 s into paint-23,
    # which began 4 s into the call; paint-12 began at 7 s. The recordings are noisy to their
    # last sample, so a line's end is only known to lie inside its recording.
    assert [e.start for e in lines] == pytest.approx([1.05, 4.74, 7.26], abs=0.1)
    assert 1.4 < lines[0].end <= 2.8 and 5.0 < lines[1].end <= 5.8 and 8.5 < lines[2].end <= 9.5
    assert all(e.deal_id == "d1" for e in lines)


async def test_lines_come_out_in_the_order_they_ended_even_when_a_later_one_is_transcribed_first(world):
    release = asyncio.Event()

    async def slow_first(pcm: bytes, prompt: str) -> str:
        world.transcribed.append(pcm)
        mine = len(world.transcribed)
        if mine == 1:
            await release.wait()
        return f"line {mine}"

    world.calls.transcribe = slow_first
    await start_call(world)
    world.talk(hirer=recorded("paint-22"), seconds=4)
    world.talk(worker=recorded("paint-23"), seconds=3)
    await world.settle()
    assert world.named("transcript.line") == []  # line 2 is ready but waits its turn
    release.set()
    await world.settle()
    assert [(e.line_no, e.speaker, e.text) for e in world.named("transcript.line")] == [
        (1, Role.HIRER, "line 1"), (2, Role.WORKER, "line 2")]


async def test_a_failed_transcription_loses_that_line_and_nothing_else(world, caplog):
    async def fails_once(pcm: bytes, prompt: str) -> str:
        world.transcribed.append(pcm)
        if len(world.transcribed) == 1:
            raise httpx.ReadTimeout("openai did not answer")
        return f"line {len(world.transcribed)}"

    world.calls.transcribe = fails_once
    await start_call(world)
    world.talk(hirer=recorded("paint-22"), seconds=4)
    world.talk(worker=recorded("paint-23"), seconds=3)
    world.talk(hirer=recorded("paint-12"), seconds=4)
    await world.settle()
    assert [(e.line_no, e.speaker) for e in world.named("transcript.line")] == [(1, Role.WORKER), (2, Role.HIRER)]
    assert "deal=d1 lost the line from hirer" in caplog.text
    world.room().left("hirer"), world.room().left("worker")
    assert (await world.ended()).reason == "both_left"


async def test_a_transcript_with_no_words_and_a_cough_sized_sound_do_not_reach_the_bus(world):
    async def nothing_said(pcm: bytes, prompt: str) -> str:
        world.transcribed.append(pcm)
        return " ।" if len(world.transcribed) == 1 else "पक्का।"

    world.calls.transcribe = nothing_said
    await start_call(world)
    world.talk(hirer=recorded("paint-22"), seconds=4)  # comes back with no words in it
    world.talk(hirer=burst(0.06), seconds=2)  # a knock: never sent for transcription
    world.talk(worker=recorded("paint-23"), seconds=3)
    await world.settle()
    assert len(world.transcribed) == 2
    assert [(e.line_no, e.speaker, e.text) for e in world.named("transcript.line")] == [(1, Role.WORKER, "पक्का।")]


async def test_a_line_being_spoken_when_the_call_ends_is_still_published_before_call_ended(world):
    await start_call(world)
    world.talk(hirer=recorded("paint-23")[: int(1.2 * RATE) * 2])  # cut off mid-air, no pause after it
    world.room().left("hirer"), world.room().left("worker")
    await world.ended()
    assert [e.name for e in world.events if e.name != "deal.requested"] == ["call.started", "transcript.line", "call.ended"]


def test_the_prompt_names_the_people_when_we_know_them():
    deal = Deal(id="d1", people=[SUNITA, Person(role=Role.WORKER, phone=RAMESH.phone)])
    prompt = prompt_for(deal, f"Ramesh painter {RAMESH.phone} se flat paint karwana hai, 98765 43210 pe bhi")
    assert "Hinglish" in prompt and "Sunita" in prompt and "painter" in prompt and "hazaar" in prompt
    assert "None" not in prompt and "flat paint karwana hai" in prompt
    assert not any(number in prompt for number in ("0000000002", "98765", "43210"))  # no phone numbers to OpenAI
    assert "first described" not in prompt_for(deal, RAMESH.phone) and "first described" not in prompt_for(deal)


async def test_transcriber_sends_the_spike_settings_and_retries_once():
    seen = []

    def openai(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ConnectError("no route")
        return httpx.Response(200, json={"text": " पक्का। ", "languages": ["hi"]})

    transcriber = Transcriber(Settings(_env_file=None, openai_api_key="sk-test"), httpx.MockTransport(openai))
    assert await transcriber.transcribe(SILENT_FRAME * 50, "the prompt") == "पक्का।"
    body = seen[1].content
    assert seen[1].url == "https://api.openai.com/v1/audio/transcriptions" and transcriber.calls == 2
    assert b"gpt-transcribe" in body and b"the prompt" in body and body.count(b'name="languages[]"') == 2
    assert b"RIFF" in body and b"server_vad" not in body and b"turn_detection" not in body

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    broken = Transcriber(Settings(_env_file=None, openai_api_key="sk-test"), httpx.MockTransport(down))
    with pytest.raises(httpx.HTTPStatusError):
        await broken.transcribe(SILENT_FRAME, "p")
    assert broken.calls == 2
    await transcriber.close(), await broken.close()
