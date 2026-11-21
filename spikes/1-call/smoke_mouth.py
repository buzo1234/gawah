"""No LiveKit room: checks the realtime protocol only. Prints event names and timings, saves the audio."""
import asyncio, base64, json, sys, time, wave
import websockets
from lk import ENV, OUT
from mouth import PERSONA

async def main(model):
    t0 = time.monotonic()
    ws = await websockets.connect(f"wss://api.openai.com/v1/realtime?model={model}",
        additional_headers={"Authorization": f"Bearer {ENV['OPENAI_API_KEY']}"}, max_size=None)
    first = json.loads(await ws.recv()); print(first["type"], round(time.monotonic()-t0, 2), "s to connect")
    s = first["session"]; print("defaults:", json.dumps({k: s.get(k) for k in ("type","model","output_modalities","reasoning","audio")})[:900])
    await ws.send(json.dumps({"type": "session.update", "session": {"type": "realtime", "output_modalities": ["audio"], "instructions": PERSONA,
        "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None}, "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "marin"}}}}))
    t = time.monotonic()
    await ws.send(json.dumps({"type": "response.create", "response": {"conversation": "none", "input": [], "output_modalities": ["audio"],
        "instructions": PERSONA + "\n\nThe instruction: Ask Sunita when the balance will be paid."}}))
    pcm = bytearray(); seen = {}
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 30)); k = ev["type"]
        if k not in seen: seen[k] = round(time.monotonic()-t, 3)
        if k == "session.updated": print("turn_detection now:", ev["session"]["audio"]["input"].get("turn_detection"))
        if k.endswith("audio.delta"): pcm.extend(base64.b64decode(ev["delta"]))
        if k.endswith("audio_transcript.done"): print("said:", ev["transcript"])
        if k == "error": print("ERROR", ev["error"])
        if k == "response.done": print("status", ev["response"]["status"], "usage", json.dumps(ev["response"].get("usage"))); break
    print("first time each event was seen (s after trigger):", seen)
    print("audio seconds:", round(len(pcm)/2/24000, 2))
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / f"smoke-{model}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(pcm))
    # does it say anything more, unprompted?
    try:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 4)); print("AFTER DONE got", ev["type"])
    except asyncio.TimeoutError:
        print("nothing more in 4 s after response.done")
    await ws.close()

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "gpt-realtime-2.1"))
