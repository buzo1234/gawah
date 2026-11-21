from app.mouth import tuning
from app.mouth.hearing import Hearing, frame_db
from tests.mouth.world import LOUD, QUIET, frame


def hear(h: Hearing, who: str, db: float, ms: int, gawah_ms: float | None = None) -> bool:
    return any([h.hear(who, db, gawah_ms) for _ in range(ms // tuning.FRAME_MS)])


def test_loudness_of_a_frame():
    assert frame_db(frame(QUIET)) == -90.3 or frame_db(frame(QUIET)) < -90
    assert abs(frame_db(frame(-20.0)) + 20.0) < 0.1


def test_a_pause_is_quiet_for_long_enough_after_talking():
    h = Hearing()
    assert h.in_pause()
    hear(h, "hirer", LOUD, 40)
    assert h.in_pause()  # two frames is a click, not speech
    hear(h, "hirer", LOUD, 60)
    assert not h.in_pause() and h.talking() == ["hirer"]
    hear(h, "hirer", QUIET, tuning.PAUSE_MS - 20)
    assert not h.in_pause()  # a breath mid-sentence
    hear(h, "hirer", QUIET, 20)
    assert h.in_pause()


def test_either_person_talking_means_no_pause():
    h = Hearing()
    hear(h, "hirer", QUIET, 1000)
    hear(h, "worker", LOUD, 100)
    assert not h.in_pause()
    h.forget("worker")  # they left the room mid-word
    assert h.in_pause()


def test_cutting_gawah_off_takes_sustained_loud_speech_after_the_hold_off():
    h = Hearing()
    h.gawah_starts()
    assert not hear(h, "hirer", LOUD, 400, gawah_ms=tuning.BARGE_HOLDOFF_MS - 1)  # too early, however loud
    assert h.hear("hirer", LOUD, gawah_ms=tuning.BARGE_HOLDOFF_MS)  # still talking as the hold-off ends
    h = Hearing()
    h.gawah_starts()
    short = (tuning.BARGE_FRAMES - 1) * tuning.FRAME_MS
    assert not hear(h, "hirer", LOUD, short, gawah_ms=1000)  # a click or a cough
    assert not hear(h, "hirer", QUIET, 20, gawah_ms=1000)
    assert hear(h, "hirer", LOUD, short + 20, gawah_ms=1000)


def test_gawahs_own_voice_leaking_back_quietly_does_not_cut_it_off():
    h = Hearing()
    h.gawah_starts()
    echo = (tuning.SPEECH_DB + tuning.BARGE_DB) / 2  # loud enough to count as sound, not as talking over
    assert not hear(h, "hirer", echo, 2000, gawah_ms=1000)


def test_someone_gawah_spoke_over_must_pause_before_they_can_cut_it_off():
    h = Hearing()
    hear(h, "hirer", LOUD, 200)
    h.gawah_starts()  # no pause came, Gawah spoke anyway
    assert not hear(h, "hirer", LOUD, 2000, gawah_ms=1000)  # carrying on is not cutting in
    assert hear(h, "worker", LOUD, 200, gawah_ms=1000)  # the other person can
    hear(h, "hirer", QUIET, tuning.BARGE_REARM_MS, gawah_ms=1000)
    assert hear(h, "hirer", LOUD, 200, gawah_ms=1000)
