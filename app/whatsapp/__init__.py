"""Stream: whatsapp. Owns the bot webhook, deals, links, the no-reply timer."""

from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request, Response

from app.bus import Bus
from app.config import Settings
from app.contracts import WHATSAPP_WEBHOOK_PATH, CallEnded, ContractReady, ReplyTimeout
from app.records.intake import Intake
from app.records.reader import Reader
from app.store import S3, Store
from app.whatsapp.bot import Bot, parse_inbound
from app.whatsapp.clock import Clock
from app.whatsapp.outbox import Outbox
from app.whatsapp.twilio import Twilio

# The same test app/dev.py uses: the tunnel adds these headers, a local request has neither.
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


def wire(
    settings: Settings, bus: Bus, store: Store, twilio: Twilio | None = None,
    reader: Reader | None = None, clock: Clock | None = None,
) -> Bot:
    """Build the bot and subscribe it. Tests pass a fake Twilio, reader, and clock."""
    twilio, clock = twilio or Twilio(settings), clock or Clock()
    outbox = Outbox(bus, twilio, clock, settings.verified_number_list)
    intake = Intake(bus, outbox, reader or Reader(settings), clock, settings.reply_timeout_seconds)
    bot = Bot(settings, bus, store, twilio, outbox, intake, sign=S3(settings).signed_url)
    bus.subscribe(CallEnded, bot.on_call_ended)
    bus.subscribe(ContractReady, bot.on_contract_ready)
    bus.subscribe(ReplyTimeout, bot.on_reply_timeout)
    return bot


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    bot = app.state.whatsapp = wire(settings, bus, app.state.store)
    app.state.on_startup.append(bot.start)
    app.state.on_shutdown.append(bot.stop)

    @app.post(WHATSAPP_WEBHOOK_PATH)
    async def webhook(request: Request) -> Response:
        form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
        if any(h in request.headers for h in _PROXY_HEADERS):
            # Twilio signs the public address it posted to, which is not the one we see here.
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            urls = [f"https://{request.headers.get('host', '')}{path}"]
            if settings.public_base_url:
                urls.append(settings.public_base_url.rstrip("/") + path)
            if not bot.twilio.signed_by_twilio(urls, form, request.headers.get("x-twilio-signature")):
                raise HTTPException(403, "bad signature")
        if "MessageStatus" in form:  # a delivery report, not a message
            return Response("<Response/>", media_type="application/xml")
        message = parse_inbound(form)
        if message is None:
            raise HTTPException(422, "no From")
        bot.receive(message)
        return Response("<Response/>", media_type="application/xml")
