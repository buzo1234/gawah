"""The speech detector, on synthetic room noise and clicks and on the recorded lines in
fixtures/audio. `python -m tests.mouth.measure_hearing` prints the numbers behind these."""

import numpy as np
import pytest

from app.mouth import tuning
from app.mouth.hearing import Hearing, frame_db
from tests.mouth import measure_interference as mi
from tests.mouth import sounds
from tests.mouth.measure_hearing import BROWSER_GAIN_DB, NOISES, cut_off_ms, noisy, on_noise, talking_ms

SPEECH = sounds.line("paint-09.wav") * 3


def hear(h: Hearing, who: str, samples: np.ndarray, gawah_ms: float | None = None) -> bool:
    return any([h.hear(who, frame, gawah_ms) for frame in sounds.frames(samples)])


def settled(noise_db: float = -45.0) -> Hearing:
    """Two people in a room with some noise, neither talking."""
    h = Hearing()
    for who in ("hirer", "worker"):
        hear(h, who, sounds.room_noise(2.0, noise_db))
    return h


def test_the_test_noise_is_what_it_says():
    assert abs(sounds.db_of(sounds.room_noise(5, -40)) + 40) < 0.5
    assert max(frame_db(f) for f in sounds.frames(sounds.clicks(5))) > -25


@pytest.mark.parametrize("name", NOISES)
def test_noise_and_clicks_never_cut_gawah_off_and_never_count_as_talking(name):
    cuts, talking_s = on_noise(*NOISES[name], seconds=60.0)
    assert cuts == 0 and talking_s == 0.0  # so Gawah is not cut off, and can still find a pause


def test_recorded_speech_over_noise_cuts_gawah_off():
    # At the level a browser's gain control gives, in a loud room (-40 dB and clicks): about half a second.
    times = [cut_off_ms(name, BROWSER_GAIN_DB) for name in sounds.LINES]
    assert all(ms is not None and not early for ms, early in times)
    assert np.median([ms for ms, _ in times]) <= tuning.BARGE_MS + 100 and max(ms for ms, _ in times) <= 2000
    # As recorded, 10 dB quieter, in a quiet room: slower, and still every time. (In the loud room, only
    # 7 dB above the noise, it is under BARGE_OVER_NOISE_DB and half the lines no longer cut in: the price
    # of not being cut off by a TV or passing traffic.)
    quiet = [cut_off_ms(name, noise_db=-50.0) for name in sounds.LINES]
    assert all(ms is not None and not early for ms, early in quiet)
    assert np.median([ms for ms, _ in quiet]) <= 800


def test_a_pause_is_found_after_speech_in_a_noisy_room():
    for name in sounds.LINES[:8]:
        noticed, share, paused = talking_ms(name, BROWSER_GAIN_DB)
        assert noticed is not None and noticed <= 500 and share > 0.85
        assert paused is not None and tuning.PAUSE_MS - 200 <= paused <= tuning.PAUSE_MS + 300


def test_a_breath_mid_sentence_is_not_a_pause():
    h = settled()
    hear(h, "hirer", SPEECH[: tuning.RATE])
    assert not h.in_pause() and h.talking() == ["hirer"]
    hear(h, "hirer", sounds.room_noise((tuning.PAUSE_MS - 100) / 1000, -45))
    assert not h.in_pause()
    hear(h, "hirer", sounds.room_noise(0.3, -45))
    assert h.in_pause()


def test_a_short_sound_does_not_cut_gawah_off_and_sustained_speech_does():
    h = settled()
    h.gawah_starts()
    assert not hear(h, "hirer", SPEECH[: tuning.RATE * 200 // 1000], gawah_ms=1000)  # a "haan", a cough
    assert not hear(h, "hirer", sounds.room_noise(2.0, -45), gawah_ms=1000)
    assert hear(h, "hirer", SPEECH[: tuning.RATE * 600 // 1000], gawah_ms=1000)


def test_nobody_can_cut_gawah_off_in_its_first_moments():
    h = settled()
    h.gawah_starts()
    assert not hear(h, "hirer", SPEECH[: tuning.RATE], gawah_ms=tuning.BARGE_HOLDOFF_MS - 1)
    assert h.hear("hirer", sounds.frames(SPEECH[tuning.RATE:])[0], gawah_ms=tuning.BARGE_HOLDOFF_MS)  # still talking as it ends


def test_gawahs_own_voice_coming_back_faintly_does_not_cut_it_off():
    h = settled(-45.0)
    h.gawah_starts()
    echo = SPEECH * 10 ** ((-45 + 2 - sounds.db_of(SPEECH)) / 20)  # speech, a little above the room's noise
    assert not hear(h, "hirer", echo + sounds.room_noise(len(echo) / tuning.RATE, -45), gawah_ms=1000)
    assert hear(h, "hirer", SPEECH[: tuning.RATE], gawah_ms=1000)  # the person speaking up still does


def test_someone_gawah_spoke_over_must_pause_before_they_can_cut_it_off():
    h = settled()
    hear(h, "hirer", SPEECH[: tuning.RATE])
    h.gawah_starts()  # no pause came, Gawah spoke anyway
    assert not hear(h, "hirer", SPEECH[tuning.RATE: 3 * tuning.RATE], gawah_ms=1000)  # carrying on is not cutting in
    assert hear(h, "worker", SPEECH[: tuning.RATE], gawah_ms=1000)  # the other person can
    hear(h, "hirer", sounds.room_noise((tuning.BARGE_REARM_MS + 100) / 1000, -45), gawah_ms=1000)
    assert hear(h, "hirer", SPEECH[: tuning.RATE], gawah_ms=1000)


def test_a_microphone_that_is_digitally_silent_between_lines_works_too():
    """The fake microphones in the real-room check, and any microphone with a noise gate."""
    h = Hearing()
    for who in ("hirer", "worker"):
        hear(h, who, sounds.silence(3.0))
    for _ in range(3):
        hear(h, "hirer", SPEECH[: 2 * tuning.RATE])
        assert h.talking() == ["hirer"]
        hear(h, "hirer", sounds.silence((tuning.PAUSE_MS + 20) / 1000))
        assert h.in_pause()
    h.gawah_starts()
    # With no room noise to go by, the floor is the recording's own hiss, 8 dB under the voice and so
    # under BARGE_OVER_NOISE_DB: this is the slow case, nearly three seconds, where 17 dB of headroom takes 0.4 s.
    cut = next(i for i, f in enumerate(sounds.frames(SPEECH)) if h.hear("hirer", f, gawah_ms=1000))
    assert (cut + 1) * tuning.FRAME_MS <= 3000


def test_each_person_has_their_own_noise_floor():
    h = Hearing()
    hear(h, "hirer", sounds.room_noise(3.0, -55))
    hear(h, "worker", sounds.room_noise(3.0, -35))
    assert h.in_pause()
    assert abs(h.people["hirer"].floor + 56) < 3 and abs(h.people["worker"].floor + 36) < 3
    quiet_voice = SPEECH * 10 ** ((-38 - sounds.db_of(SPEECH)) / 20)  # below the worker's noise, well above the hirer's
    hear(h, "hirer", quiet_voice[: tuning.RATE] + sounds.room_noise(1.0, -55))
    assert h.talking() == ["hirer"]


def test_a_muted_track_is_silence():
    h = settled()
    hear(h, "hirer", SPEECH[: tuning.RATE])
    assert not h.in_pause()
    floor = h.people["hirer"].floor
    hear(h, "hirer", sounds.silence(5.0))  # the phone's screen locked: the track delivers digital silence
    assert h.in_pause() and h.people["hirer"].floor == floor
    assert not hear(h, "hirer", sounds.silence(5.0), gawah_ms=1000)
    assert not hear(h, "hirer", noisy(5.0, -45), gawah_ms=1000)  # unmuted while Gawah is speaking
    hear(h, "hirer", noisy(3.0, -45))  # unmuted, back in the room's noise
    assert h.in_pause()
    hear(h, "hirer", SPEECH[: tuning.RATE])
    assert not h.in_pause()
    h.forget("hirer")  # or the track is muted mid-word and no more frames come
    assert h.in_pause()


def test_someone_who_joins_muted_and_unmutes_into_a_noisy_room_is_not_talking():
    h, talking = Hearing(), 0
    for frame in sounds.frames(np.concatenate([sounds.silence(3.0), noisy(10.0, -40)])):
        assert not h.hear("worker", frame, gawah_ms=1000)
        talking += not h.in_pause()
    assert talking == 0


def test_room_noise_getting_louder_is_learned_within_seconds():
    """A fan comes on, 10 dB above the room. The detector can take the new noise for a voice
    until the floor catches up, and that can cut Gawah off if it is speaking just then: a
    known limit. After that it is noise again: a pause is found, and nothing cuts Gawah off."""
    h = settled(-50.0)
    hear(h, "worker", noisy(8.0, -40))
    assert h.in_pause() and abs(h.people["worker"].floor + 41) < 3
    assert not hear(h, "worker", noisy(20.0, -40, seed=5), gawah_ms=1000)


def test_echo_traffic_and_a_tv_across_the_room_never_cut_gawah_off():
    """measure_interference.py's cases, at the levels that cut Gawah off before."""
    gawah = mi.gawah_level()
    n = len(gawah)
    assert mi.steady(mi.echo(gawah, 15.0)[:n]).cuts == 0  # a phone on loudspeaker
    assert mi.steady(mi.echo(gawah, 20.0)[:n]).cuts == 0
    assert mi.steady(sounds.traffic(mi.LEAD_S + mi.SECONDS, -35)).cuts == 0
    assert mi.steady(sounds.tv(mi.LEAD_S + mi.SECONDS, -40)).cuts == 0


def test_a_short_haan_never_stops_gawah_for_good():
    haan = mi.bursts(lambda k: mi.short_word(k, 400))
    assert haan.final == 0 and haan.cuts < haan.events / 2


def test_a_line_over_gawahs_echo_still_stops_it_for_good_in_about_half_a_second():
    stops = mi.real(BROWSER_GAIN_DB, echo_loss_db=20.0)
    assert len(stops) == len(sounds.LINES) and all(final for _, final in stops)
    assert np.median([ms for ms, _ in stops]) <= 500 and max(ms for ms, _ in stops) <= 1000
