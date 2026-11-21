"""The access key: on a public server (ACCESS_KEY set) the board and the routes behind it
ask for one value, once, and keep it in an http-only cookie. With it unset (the laptop)
nothing here runs.

Guarded: /dashboard (the board, the second phone, their state and websocket), /actor,
/dev, /memory (clips, the chain, the lookups). Public: everything else, which is the
WhatsApp webhook, the call and call-back pages with their token routes, and /health.
Two guarded paths have their own way in, because someone without the key opens them:
- a clip sent on WhatsApp carries a signed expiry (signed_links), checked here;
- an image the second phone attached (/dashboard/media/<32 hex>.<ext>) is fetched by the
  model that reads it; its name is unguessable, as a signed link's would be.
A request with no key gets 401: the key form for a browser page, JSON for anything else.
Scripts send the key in the X-Access-Key header instead of the cookie.
"""

import hashlib
import hmac
import re
import time
from collections.abc import Callable
from html import escape
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, parse_qsl, urlencode

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import Settings

GUARDED = ("/dashboard", "/actor", "/dev", "/memory")
OPEN_MEDIA = re.compile(r"/dashboard/media/[0-9a-f]{32}\.(jpg|png|webp)")
SIGNED = ("/memory/clip/",)
COOKIE = "gawah_access"
HEADER = "x-access-key"
FORM_PATH = "/access"
CLIP_LINK_SECONDS = 24 * 3600  # a clip link sent on WhatsApp works for a day
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


def _key(settings: Settings) -> str | None:
    return settings.access_key.get_secret_value() if settings.access_key else None


def _mac(key: str, message: str) -> str:
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def guarded(path: str) -> bool:
    if OPEN_MEDIA.fullmatch(path):
        return False
    return any(path == p or path.startswith(p + "/") for p in GUARDED)


def sign_path(key: str, path: str, now: float | None = None, seconds: int = CLIP_LINK_SECONDS) -> str:
    expires = int((now or time.time()) + seconds)
    return f"{path}?{urlencode({'exp': expires, 'sig': _mac(key, f'link|{path}|{expires}')})}"


def signed_links(settings: Settings, link: Callable[[str], str]) -> Callable[[str], str]:
    """link, with a signed expiry added to a clip's path when the access key is set."""
    key = _key(settings)
    if not key:
        return link
    return lambda path: link(sign_path(key, path) if path.startswith(SIGNED) else path)


def _signature_ok(key: str, path: str, query: str) -> bool:
    if not path.startswith(SIGNED):
        return False
    q = parse_qs(query)
    exp, sig = q.get("exp", [""])[0], q.get("sig", [""])[0]
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return _same(sig, _mac(key, f"link|{path}|{exp}"))


def local_or_keyed(request: Request) -> None:
    """For a route that used to trust only the laptop: from outside, it is allowed only
    when the access key is set, because then the guard has already checked the key."""
    if request.app.state.settings.access_key is None and any(h in request.headers for h in _PROXY_HEADERS):
        raise HTTPException(403, "local only")


def _form(next_path: str, wrong: bool = False) -> str:
    note = '<p class="no">Galat key. Phir se try karein.</p>' if wrong else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Gawah</title>
<style>body{{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0 16px}}
form{{display:grid;gap:12px;width:100%;max-width:320px}}input,button{{font:inherit;padding:10px}}.no{{color:#b00}}</style>
</head><body><form method="post" action="{FORM_PATH}"><h1>Gawah</h1>{note}
<input type="password" name="key" placeholder="Access key" autofocus required autocomplete="current-password">
<input type="hidden" name="next" value="{escape(next_path)}"><button>Kholiye</button></form></body></html>"""


def _safe_next(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") and "\\" not in path else "/dashboard"


class AccessGuard:
    """Plain ASGI, so the dashboard's websocket is guarded as well as its pages."""

    def __init__(self, app, key: str) -> None:
        self.app, self.key = app, key
        self.cookie_value = _mac(key, "cookie")

    def allowed(self, scope) -> bool:
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if HEADER in headers and _same(headers[HEADER], self.key):
            return True
        jar = SimpleCookie()
        try:
            jar.load(headers.get("cookie", ""))
        except Exception:
            return False
        if COOKIE in jar and _same(jar[COOKIE].value, self.cookie_value):
            return True
        return _signature_ok(self.key, scope["path"], scope.get("query_string", b"").decode("latin-1"))

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket") or not guarded(scope["path"]) or self.allowed(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        accept = dict(scope.get("headers", [])).get(b"accept", b"").decode("latin-1")
        if scope["method"] == "GET" and "text/html" in accept:
            query = scope.get("query_string", b"").decode("latin-1")
            response = HTMLResponse(_form(scope["path"] + (f"?{query}" if query else "")), 401)
        else:
            response = JSONResponse({"detail": "access key needed"}, 401)
        await response(scope, receive, send)


def register(app: FastAPI) -> None:
    """With ACCESS_KEY set: the guard on every request, and the form that sets the cookie."""
    key = _key(app.state.settings)
    if not key:
        return
    cookie_value = _mac(key, "cookie")

    @app.get(FORM_PATH, response_class=HTMLResponse)
    async def form(next: str = "/dashboard") -> str:
        return _form(_safe_next(next))

    @app.post(FORM_PATH)
    async def check(request: Request) -> Response:
        fields = dict(parse_qsl((await request.body()).decode(errors="replace")))
        next_path = _safe_next(fields.get("next", "/dashboard"))
        if not _same(fields.get("key", ""), key):
            return HTMLResponse(_form(next_path, wrong=True), 401)
        response = RedirectResponse(next_path, 303)
        response.set_cookie(
            COOKIE, cookie_value, max_age=30 * 24 * 3600, httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response

    app.add_middleware(AccessGuard, key=key)
