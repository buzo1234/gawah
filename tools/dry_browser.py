"""A headless Chrome that plays one person on a call page: its microphone is fed a line at a
time, when the dry run says so, instead of a fixed recording that runs on regardless of what
Gawah does. Not a test.

The page's getUserMedia is replaced before any of its scripts run: it returns a track fed by
an AudioContext, and say() plays 16 kHz PCM into it. Each getUserMedia gets a fresh clone of
that track, so the page can stop its microphone on leaving and join the next call."""

import asyncio
import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

MICROPHONE = """
(() => {
  const ctx = new AudioContext({ sampleRate: 48000 });
  const out = ctx.createMediaStreamDestination();
  // A faint room hiss, as a real microphone always has. Pure digital silence sends no audio, and the
  // server then waits out its timeouts: Gawah's opening line, and "this person has gone".
  const hiss = ctx.createBuffer(1, 48000, 48000);
  const h = hiss.getChannelData(0);
  for (let i = 0; i < h.length; i++) h[i] = (Math.random() * 2 - 1) * 0.004;
  const floor = ctx.createBufferSource();
  floor.buffer = hiss;
  floor.loop = true;
  floor.connect(out);
  floor.start();
  window.__say = async (b64, rate) => {
    if (ctx.state !== 'running') await ctx.resume();
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const pcm = new Int16Array(bytes.buffer);
    const buffer = ctx.createBuffer(1, pcm.length, rate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 32768;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(out);
    source.start();
    return pcm.length / rate;
  };
  const real = navigator.mediaDevices && navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  if (!real) return;
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    if (!constraints || !constraints.audio) return real(constraints);
    await ctx.resume();
    return new MediaStream([out.stream.getAudioTracks()[0].clone()]);
  };
})();
"""

# Whether Gawah is talking in the room, as LiveKit's active-speaker updates say. `room` is the
# call page's own top-level variable; the call-back page has one too.
GAWAH_TALKING = (
    "(typeof room !== 'undefined' && room) ? [...room.remoteParticipants.values()]"
    ".some((p) => p.identity === 'gawah' && p.isSpeaking) : false"
)


class Person:
    def __init__(self, folder: Path, port: int, who: str) -> None:
        self.who, self.port = who, port
        self.proc = subprocess.Popen(
            [
                CHROME, "--headless=new", f"--user-data-dir={tempfile.mkdtemp(prefix=who, dir=folder)}",
                f"--remote-debugging-port={port}", "--no-first-run", "--no-default-browser-check",
                "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-gpu", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._id = 0
        self.ws = None

    async def start(self) -> None:
        async with httpx.AsyncClient() as http:
            for _ in range(150):
                try:
                    pages = [t for t in (await http.get(f"http://127.0.0.1:{self.port}/json/list")).json() if t["type"] == "page"]
                    if pages:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError(f"{self.who}: Chrome did not start")
        self.ws = await connect(pages[0]["webSocketDebuggerUrl"], max_size=None)
        await self.send("Page.enable")
        await self.send("Page.addScriptToEvaluateOnNewDocument", source=MICROPHONE)

    async def send(self, method: str, **params):
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 60))
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{self.who}: {method}: {msg['error']}")
                return msg["result"]

    async def js(self, expression: str):
        result = await self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True, userGesture=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{self.who}: {str(result['exceptionDetails'])[:300]}")
        return result["result"].get("value")

    async def until(self, expression: str, timeout: float = 20.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if await self.js(expression):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(0.2)
        return False

    async def open(self, url: str, ready: str = "!!document.getElementById('join')") -> None:
        await self.send("Page.navigate", url=url)
        if not await self.until(f"document.readyState === 'complete' && {ready}", 30):
            raise TimeoutError(f"{self.who}: {url} did not load")

    async def click(self, element_id: str) -> None:
        await self.js(f"document.getElementById({json.dumps(element_id)}).click()")

    async def state(self) -> str | None:
        return await self.js("document.body.dataset.state")

    async def say(self, pcm: bytes, rate: int = 16000) -> float:
        """Play the line into the microphone and return when it has been said."""
        seconds = await self.js(f"__say({json.dumps(base64.b64encode(pcm).decode())}, {rate})")
        await asyncio.sleep(seconds)
        return seconds

    async def gawah_talking(self) -> bool:
        try:
            return bool(await self.js(GAWAH_TALKING))
        except (RuntimeError, asyncio.TimeoutError):
            return False

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
