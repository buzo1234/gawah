"""HTML to PDF by printing it with the Chrome already on the laptop.

Chrome shapes Devanagari properly (joined letters, vowel signs) and uses the system's
Hindi font, so there is no PDF library and no font file to install.
"""

import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path

_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chromium-headless-shell",  # the server's image (Dockerfile): Debian's headless-only build
)
_TIMEOUT = 30
# Chrome's sandbox cannot start inside Docker's default seccomp profile. The image sets this;
# the page printed is our own contract, written from the deal.
_SANDBOX = ("--no-sandbox",) if os.environ.get("GAWAH_CHROME_NO_SANDBOX") == "1" else ()


def find_chrome() -> str | None:
    return next((found for c in _CANDIDATES if (found := shutil.which(c))), None)


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf))


async def render_pdf(html: str, out: Path) -> None:
    """Print the page to out. Tries once more if Chrome hangs or writes nothing."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("no Chrome, Chromium, Edge or Brave found to print the PDF")
    for attempt in (1, 2):
        try:
            await _print(chrome, html, out)
            return
        except (RuntimeError, TimeoutError):
            if attempt == 2:
                raise


async def _print(chrome: str, html: str, out: Path) -> None:
    # Its own profile folder, so it never attaches to a Chrome the user has open.
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "contract.html"
        page.write_text(html, encoding="utf-8")
        out.unlink(missing_ok=True)
        process = await asyncio.create_subprocess_exec(
            chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
            *_SANDBOX,
            f"--user-data-dir={tmp}/profile", f"--print-to-pdf={out}", page.as_uri(),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), _TIMEOUT)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
    if not out.exists() or not out.read_bytes().startswith(b"%PDF"):
        raise RuntimeError("Chrome did not write a PDF")
