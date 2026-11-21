"""Stream: whatsapp. Owns the bot webhook, deals, links, the no-reply timer."""

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from app.bus import Bus
from app.config import Settings
from app.contracts import (
    MEMORY_STATE,
    NO_DEAL,
    WHATSAPP_WEBHOOK_PATH,
    CallEnded,
    CallOpened,
    ContractReady,
    MemoryQueries,
    RecordConfirmed,
    ReplyTimeout,
)
from app.log import deal_log
from app.records.intake import Intake
from app.records.reader import Reader
from app.records.reminders import Reminders
from app.records.sentinel import Sentinel, wall_clock
from app.store import S3, Store
from app.whatsapp.bot import Bot, link_for, parse_inbound
from app.whatsapp.clock import Clock
from app.whatsapp.meta import Meta
from app.whatsapp.meta_inbound import parse_meta, report_failures
from app.whatsapp.outbox import Outbox, Provider
from app.whatsapp.settings import whatsapp_settings
from app.whatsapp.twilio import Twilio

# The same test app/dev.py uses: the tunnel adds these headers, a local request has neither.
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


def wire(
    settings: Settings, bus: Bus, store: Store, provider: Provider | None = None,
    reader: Reader | None = None, clock: Clock | None = None, memory: MemoryQueries | None = None,
    wall: Callable[[], datetime] = wall_clock,
) -> Bot:
    """Build the bot and subscribe it. Tests pass a fake provider, reader, clock, and memory.
    With no memory there is no Sentinel: records are logged and confirmed as before.
    The provider is Twilio unless WHATSAPP_PROVIDER=meta."""
    settings = whatsapp_settings(settings)
    if provider is None:
        provider = Meta(settings) if settings.whatsapp_provider == "meta" else Twilio(settings)
    clock = clock or Clock()
    outbox = Outbox(bus, provider, clock, settings.verified_number_list)
    sentinel = None
    if memory is not None:
        saved = Path(settings.database_path).with_suffix(".sentinel.json")
        sentinel = Sentinel(
            bus, outbox, store, memory, link_for(settings),
            reminders=lambda s: Reminders(saved, clock, wall, s.remind), wall=wall,
        )
        sentinel.subscribe()
    intake = Intake(bus, outbox, reader or Reader(settings), clock, settings.reply_timeout_seconds, sentinel)
    bot = Bot(settings, bus, store, provider, outbox, intake, sign=S3(settings).signed_url, sentinel=sentinel)
    bus.subscribe(CallOpened, bot.on_call_opened)
    bus.subscribe(CallEnded, bot.on_call_ended)
    bus.subscribe(ContractReady, bot.on_contract_ready)
    bus.subscribe(ReplyTimeout, bot.on_reply_timeout)
    bus.subscribe(RecordConfirmed, intake.on_confirmed)
    return bot


def register(app: FastAPI, bus: Bus) -> None:
    settings = whatsapp_settings(app.state.settings)
    memory = getattr(app.state, MEMORY_STATE, None)  # memory registers before whatsapp
    bot = app.state.whatsapp = wire(settings, bus, app.state.store, memory=memory)
    app.state.on_startup.append(bot.start)
    app.state.on_shutdown.append(bot.stop)
    # Both shapes are taken whichever provider sends: Meta posts JSON, Twilio and the
    # dashboard's second phone post a form.
    twilio = Twilio(settings)
    meta = bot.provider if hasattr(bot.provider, "signed_by_meta") else Meta(settings)

    @app.get(WHATSAPP_WEBHOOK_PATH)
    async def verify(request: Request) -> Response:
        """Meta's handshake when the callback URL is saved: echo the challenge."""
        query = request.query_params
        challenge = meta.verify(query.get("hub.mode"), query.get("hub.verify_token"), query.get("hub.challenge"))
        if challenge is None:
            raise HTTPException(403, "wrong verify token")
        return PlainTextResponse(challenge)

    @app.post(WHATSAPP_WEBHOOK_PATH)
    async def webhook(request: Request) -> Response:
        body = await request.body()
        from_tunnel = any(h in request.headers for h in _PROXY_HEADERS)
        if request.headers.get("content-type", "").startswith("application/json"):
            if from_tunnel and not meta.signed_by_meta(body, request.headers.get("x-hub-signature-256")):
                raise HTTPException(403, "bad signature")
            try:
                payload = json.loads(body)
            except ValueError as error:
                raise HTTPException(422, "not JSON") from error
            messages, statuses, skipped = parse_meta(payload, meta.media_url)
            for message in messages:
                bot.receive(message)
            report_failures(statuses, bot.outbox.deal_of)
            if skipped:
                deal_log("gawah.whatsapp", NO_DEAL).warning("%d message(s) from a person with no phone number skipped", skipped)
            return Response(status_code=200)
        form = dict(parse_qsl(body.decode(), keep_blank_values=True))
        if from_tunnel:
            # Twilio signs the public address it posted to, which is not the one we see here.
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            urls = [f"https://{request.headers.get('host', '')}{path}"]
            if settings.public_base_url:
                urls.append(settings.public_base_url.rstrip("/") + path)
            if not twilio.signed_by_twilio(urls, form, request.headers.get("x-twilio-signature")):
                raise HTTPException(403, "bad signature")
        if "MessageStatus" in form:  # a delivery report, not a message
            return Response("<Response/>", media_type="application/xml")
        message = parse_inbound(form)
        if message is None:
            raise HTTPException(422, "no From")
        bot.receive(message)
        return Response("<Response/>", media_type="application/xml")
