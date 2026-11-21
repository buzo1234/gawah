"""Drives the Chrome installed on this Mac, headless, over its debugging socket. Used by
dashboard_live_shots.py. Not a test: pytest does not collect it."""

import asyncio
import base64
import json
import subprocess
import tempfile
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Chrome:
    def __init__(self, port: int = 9333, width: int = 1920, height: int = 1080) -> None:
        self.port, self.width, self.height = port, width, height
        self.errors: list[str] = []
        self._id = 0
        self._waiting: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> "Chrome":
        self._dir = tempfile.TemporaryDirectory()
        self._proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self._dir.name}",
             f"--window-size={self.width},{self.height}", "--no-first-run", "--disable-extensions", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        async with httpx.AsyncClient() as client:
            for _ in range(100):
                try:
                    pages = [t for t in (await client.get(f"http://127.0.0.1:{self.port}/json/list")).json() if t["type"] == "page"]
                    if pages:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Chrome did not start")
        self._ws = await connect(pages[0]["webSocketDebuggerUrl"], max_size=None)
        self._reader = asyncio.create_task(self._read())
        for domain in ("Page", "Runtime", "Log", "DOM"):
            await self.send(f"{domain}.enable")
        await self.send("Emulation.setDeviceMetricsOverride",
                        width=self.width, height=self.height, deviceScaleFactor=1, mobile=False)
        return self

    async def __aexit__(self, *exc) -> None:
        self._reader.cancel()
        await self._ws.close()
        self._proc.terminate()
        self._proc.wait(timeout=10)
        self._dir.cleanup()

    async def _read(self) -> None:
        async for raw in self._ws:
            msg = json.loads(raw)
            if "id" in msg:
                self._waiting.pop(msg["id"]).set_result(msg)
            elif msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append(f"exception: {d.get('text')} {d.get('exception', {}).get('description', '')}")
            elif msg.get("method") == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
                self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description"))) for a in msg["params"]["args"]))
            elif msg.get("method") == "Log.entryAdded" and msg["params"]["entry"]["level"] == "error":
                e = msg["params"]["entry"]
                self.errors.append(f"log: {e['text']} {e.get('url', '')}")

    async def send(self, method: str, **params):
        self._id += 1
        future = asyncio.get_running_loop().create_future()
        self._waiting[self._id] = future
        await self._ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        msg = await asyncio.wait_for(future, 30)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    async def goto(self, url: str) -> None:
        await self.send("Page.navigate", url=url)
        await self.wait_for("document.readyState === 'complete'")

    async def reload(self) -> None:
        await self.send("Page.reload", ignoreCache=True)
        await asyncio.sleep(0.2)
        await self.wait_for("document.readyState === 'complete'")

    async def js(self, expression: str):
        result = await self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description", str(result["exceptionDetails"])))
        return result["result"].get("value")

    async def wait_for(self, expression: str, timeout: float = 10.0) -> None:
        for _ in range(int(timeout / 0.05)):
            try:
                if await self.js(expression):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.05)
        raise TimeoutError(f"never true: {expression}")

    async def shot(self, path: str | Path) -> None:
        data = (await self.send("Page.captureScreenshot", format="png"))["data"]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))

    async def set_file(self, selector: str, path: str) -> None:
        root = (await self.send("DOM.getDocument"))["root"]["nodeId"]
        node = (await self.send("DOM.querySelector", nodeId=root, selector=selector))["nodeId"]
        await self.send("DOM.setFileInputFiles", files=[str(path)], nodeId=node)
