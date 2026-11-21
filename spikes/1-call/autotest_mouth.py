"""Spike 3 phases: trigger delay on both models, and barge-in. Run through autotest.py."""

import asyncio
import json

from autotest import ASKS, READ_BACK, Rig, count, save, transcribe, until
from lk import HERE
from mouth import Mouth


async def phase2() -> None:
    """Spike 3: trigger -> first audio heard in the room, both models, with samples and transcripts."""
    res: dict = {"runs": []}
    (HERE / "samples").mkdir(exist_ok=True)
    configs = [("gpt-realtime-2.1", None), ("gpt-realtime-2.1-mini", None), ("gpt-realtime-2.1", "minimal")]
    async with Rig("p2") as rig:
        agent, rec = rig.agent, rig.recorder
        await asyncio.sleep(2)
        for model, effort in configs:
            await agent.use_model(model, effort)
            asks = ASKS if effort is None else ASKS[:3]
            for i, ask in enumerate(asks):
                u = await agent.mouth.say(ask)
                try:
                    await agent.mouth.wait_done(30)
                except asyncio.TimeoutError:
                    await agent.mouth.stop("timeout")
                await asyncio.sleep(1.5)
                heard = rec.heard("gawah", after=u["t_trigger"])
                run = {
                    "model": model, "effort": effort or "default", "instruction": ask, "said_per_model": u.get("said"), "status": u.get("status"),
                    "ms_trigger_to_response_created": ms(u, "t_created"), "ms_trigger_to_first_audio_from_openai": ms(u, "t_first_delta"),
                    "ms_trigger_to_first_frame_published": ms(u, "t_first_frame"),
                    "ms_trigger_to_heard_in_room": round((heard[0] - u["t_trigger"]) * 1000) if heard else None,
                    "speech_ms": u["audio_ms"],
                    "ms_heard_after_playout_end": round((heard[-1] - u["t_play_end"]) * 1000) if heard and "t_play_end" in u else None,
                }
                tag = f"{model.removeprefix('gpt-realtime-')}{'-minimal' if effort else ''}-{i + 1}"
                clip = rig.out / f"gawah-{tag}.wav"
                rec.save("gawah", clip, after=u["t_trigger"])
                run["gpt_transcribe_of_room_recording"] = await transcribe(clip)
                if i < 2 and effort is None:
                    (HERE / "samples" / clip.name).write_bytes(clip.read_bytes())
                    run["sample"] = f"samples/{clip.name}"
                res["runs"].append(run)
                print(json.dumps(run, ensure_ascii=False), flush=True)
            res.setdefault("model_errors", {})[f"{model}/{effort}"] = agent.mouth.errors
            res.setdefault("unsolicited", {})[f"{model}/{effort}"] = agent.mouth.unsolicited
            res.setdefault("usage", []).extend(agent.mouth.usage)
    res["participant_minutes"] = rig.minutes
    save("phase2.json", res)


def ms(u: dict, key: str) -> int | None:
    return round((u[key] - u["t_trigger"]) * 1000) if key in u else None


async def phase3() -> None:
    """Spike 3: barge-in. Sunita's fake mic loops 7 s of speech and 9 s of silence; Ramesh's is silent."""
    res: dict = {"trials": []}
    async with Rig("p3") as rig:
        agent, rec = rig.agent, rig.recorder
        rig.browser("sunita", "barge.wav")
        rig.browser("ramesh", "silent.wav")
        if await until(lambda: count(agent, "first_audio_frame", "sunita") and count(agent, "first_audio_frame", "ramesh"), 40, "both tracks") is None:
            raise RuntimeError(f"browsers did not join; page reports: {rig.app.state.reports}")
        sunita = agent.person("sunita")
        plan = [("gpt-realtime-2.1", ASKS[0], "short, in the gap: must finish untouched"),
                ("gpt-realtime-2.1", READ_BACK, "long: Sunita talks over it"),
                ("gpt-realtime-2.1", READ_BACK, "long: Sunita talks over it"),
                ("gpt-realtime-2.1", READ_BACK, "long: Sunita talks over it"),
                ("gpt-realtime-2.1-mini", READ_BACK, "long: Sunita talks over it"),
                ("gpt-realtime-2.1-mini", READ_BACK, "long: Sunita talks over it")]
        for model, ask, what in plan:
            if agent.model != model:
                await agent.use_model(model)
            await until(lambda: sunita.speaking, 30, "sunita speaking")
            await until(lambda: not sunita.speaking, 30, "sunita quiet")
            barges_before = len(agent.barge_ins)
            u = await agent.mouth.say(ask)
            try:
                await agent.mouth.wait_done(40)
            except asyncio.TimeoutError:
                await agent.mouth.stop("timeout")
            await asyncio.sleep(1.5)
            trial = {"model": model, "what": what, "status": u.get("status"), "stop_reason": u.get("stop_reason"),
                     "speech_generated_ms": u["audio_ms"], "speech_played_ms": u["played_ms"], "said_per_model": u.get("said")}
            if len(agent.barge_ins) > barges_before:
                b = agent.barge_ins[-1]
                # Sunita's onset as the recorder heard it: first loud frame after a quiet stretch, near the agent's detection
                loud = rec.heard("sunita", after=b["t_detected"] - 1.0, before=b["t_detected"] + 0.5, db=-40)
                onset = loud[0] if loud else None
                gawah = rec.heard("gawah", after=u["t_trigger"], before=b["t_detected"] + 5)
                trial.update({
                    "who": b["who"],
                    "ms_agent_detect_to_stop_sent": round((u["t_stop"] - b["t_detected"]) * 1000),
                    "ms_person_onset_in_room_to_agent_detect": round((b["t_detected"] - onset) * 1000) if onset else None,
                    "ms_person_onset_in_room_to_gawah_silent_in_room": round((gawah[-1] - onset) * 1000) if onset and gawah else None,
                    "ms_agent_detect_to_gawah_silent_in_room": round((gawah[-1] - b["t_detected"]) * 1000) if gawah else None,
                })
                rec.save("gawah", rig.out / f"barge-{len(res['trials'])}-gawah.wav", after=u["t_trigger"], before=b["t_detected"] + 3)
            res["trials"].append(trial)
            print(json.dumps(trial, ensure_ascii=False), flush=True)
        res["page_stats"] = {k: v for k, v in rig.app.state.reports.items()}
        res["model_errors"] = agent.mouth.errors
        res["usage"] = agent.mouth.usage
        rig.app.state.leave.update({"sunita", "ramesh"})
        await asyncio.sleep(2.5)
    res["participant_minutes"] = rig.minutes
    save("phase3.json", res)


async def phase2b() -> None:
    """Same question to both models, alternating, with the arrival time of every audio chunk."""
    res: dict = {"runs": []}
    async with Rig("p2b") as rig:
        agent, rec = rig.agent, rig.recorder
        mouths = {"gpt-realtime-2.1": agent.mouth, "gpt-realtime-2.1-mini": Mouth("gpt-realtime-2.1-mini", agent.source)}
        await mouths["gpt-realtime-2.1-mini"].connect()
        await asyncio.sleep(2)
        for ask in ASKS[:4]:
            for model, mouth in mouths.items():
                u = await mouth.say(ask)
                await mouth.wait_done(30)
                await asyncio.sleep(1.5)
                heard = rec.heard("gawah", after=u["t_trigger"])
                deltas = u.get("deltas", [])
                # how far ahead of real-time playback the received audio was, at its worst (negative = ran dry)
                lead = min(audio_ms - (t - deltas[0][0]) for t, audio_ms in deltas) if deltas else None
                run = {"model": model, "instruction": ask, "said_per_model": u.get("said"),
                       "ms_trigger_to_first_audio_from_openai": ms(u, "t_first_delta"), "ms_trigger_to_heard_in_room": round((heard[0] - u["t_trigger"]) * 1000) if heard else None,
                       "speech_ms": u["audio_ms"], "ms_openai_took_to_send_all_audio": deltas[-1][0] - deltas[0][0] if deltas else None,
                       "first_chunk_ms_of_audio": deltas[0][1] if deltas else None, "worst_lead_over_realtime_ms": lead, "starved_ms": u.get("starved_ms", 0),
                       "heard_span_ms": round((heard[-1] - heard[0]) * 1000) if heard else None, "chunks": deltas[:6]}
                res["runs"].append(run)
                print(json.dumps(run, ensure_ascii=False), flush=True)
        await mouths["gpt-realtime-2.1-mini"].close()
        res["usage"] = agent.mouth.usage + mouths["gpt-realtime-2.1-mini"].usage
    res["participant_minutes"] = rig.minutes
    save("phase2b.json", res)
