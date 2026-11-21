"""Twilio's WhatsApp sandbox: send a message, download media it hosts, check a webhook
signature. The only file that talks to Twilio."""

import base64
import hashlib
import hmac
import logging
import re
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.whatsapp.outgoing import Outgoing

API = "https://api.twilio.com"
TIMEOUT = 15.0

# httpx logs every request URL at INFO, and Twilio's URLs contain the account id.
logging.getLogger("httpx").setLevel(logging.WARNING)


class TwilioError(Exception):
    """Twilio said no. Carries Twilio's error code and its message, with any phone
    number in the message cut to its last 4 digits."""

    def __init__(self, status: int, code: int | None, message: str = "") -> None:
        message = re.sub(r"\+?\d{7,}", lambda m: f"***{m.group()[-4:]}", message)
        super().__init__(f"twilio http {status} code {code}: {message}")
        self.status, self.code = status, code


def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """What Twilio puts in X-Twilio-Signature: HMAC-SHA1, keyed with the auth token, over
    the public URL followed by every form field, sorted by name, as name then value."""
    payload = url + "".join(k + v for k, v in sorted(params.items()))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


class Twilio:
    rich = False  # plain text and media only: no buttons, no reactions
    spacing_seconds = 3.0  # the sandbox allows one message every three seconds

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def signed_by_twilio(self, urls: list[str], params: dict[str, str], given: str | None) -> bool:
        if not given or not self._settings.twilio_auth_token:
            return False
        token = self._settings.require("twilio_auth_token")
        return any(hmac.compare_digest(signature(token, url, params), given) for url in urls)

    async def send(self, out: Outgoing) -> str:
        """Send one WhatsApp message from the sandbox number. Returns Twilio's message id."""
        to, text, media_url = out.to, out.text, out.media_url
        sender = self._settings.require("twilio_whatsapp_number").removeprefix("whatsapp:")
        data = {"From": f"whatsapp:{sender}", "To": f"whatsapp:{to}"}
        if text:
            data["Body"] = text
        if media_url:
            data["MediaUrl"] = media_url
        sid = self._settings.require("twilio_account_sid")
        response = await self._request("POST", f"{API}/2010-04-01/Accounts/{sid}/Messages.json", data=data)
        return response.json()["sid"]

    async def fetch_media(self, url: str) -> tuple[bytes, str | None]:
        """Download a file a person sent. Twilio's own links need the account keys; any
        other link (a local test image) is fetched without them."""
        response = await self._request("GET", url, auth=urlsplit(url).hostname == urlsplit(API).hostname)
        return response.content, response.headers.get("content-type")

    async def _request(self, method: str, url: str, auth: bool = True, **kwargs) -> httpx.Response:
        keys = None
        if auth:
            keys = (self._settings.require("twilio_account_sid"), self._settings.require("twilio_auth_token"))
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            for attempt in (1, 2):
                try:
                    response = await client.request(method, url, auth=keys, **kwargs)
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    continue
                if response.status_code < 500 or attempt == 2:
                    break
        if response.status_code >= 400:
            problem = {}
            if response.headers.get("content-type", "").startswith("application/json"):
                problem = response.json()
            raise TwilioError(response.status_code, problem.get("code"), problem.get("message", ""))
        return response
