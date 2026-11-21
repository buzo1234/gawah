"""Meta's Graph API faked at the HTTP level: the real Meta client (app/whatsapp/meta.py)
builds and sends every request, and this answers it."""

import json

import httpx

TOKEN, PHONE_ID, VERIFY, SECRET = "meta-token", "1000000001", "verify-me", "app-secret"
API = "https://graph.facebook.com/v27.0"
LOOKASIDE = "https://lookaside.fbsbx.com/whatsapp_business/attachments/"


class FakeGraph:
    """Answers /messages with a new wamid, a media id with its short-lived address, and that
    address with the file. Every request needs the token except a plain link's download."""

    def __init__(self) -> None:
        self.posts: list[dict] = []  # every JSON body posted to /messages, in order
        self.gets: list[str] = []
        self.media = {"MEDIA-SHOT": (b"jpeg bytes", "image/jpeg")}
        self.fail: tuple[int, int] | None = None  # (http status, Graph error code) for the next sends

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def messages(self) -> list[dict]:
        return [p for p in self.posts if "status" not in p]

    @property
    def typing(self) -> list[dict]:
        return [p for p in self.posts if p.get("status") == "read"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        url, authed = str(request.url), request.headers.get("authorization") == f"Bearer {TOKEN}"
        if request.method == "POST" and url == f"{API}/{PHONE_ID}/messages":
            assert authed
            body = json.loads(request.content)
            self.posts.append(body)
            if self.fail:
                status, code = self.fail
                return httpx.Response(status, json={"error": {
                    "message": "(#%d) refused" % code, "code": code, "error_data": {"details": "to +919822200002"},
                }})
            if "status" in body:
                return httpx.Response(200, json={"success": True})
            return httpx.Response(200, json={
                "messaging_product": "whatsapp", "contacts": [{"input": body["to"], "wa_id": body["to"]}],
                "messages": [{"id": f"wamid.OUT{len(self.messages)}"}],
            })
        self.gets.append(url)
        if url.startswith(API + "/"):
            assert authed
            media_id = url.rsplit("/", 1)[1]
            data, mime = self.media[media_id]
            return httpx.Response(200, json={
                "messaging_product": "whatsapp", "url": f"{LOOKASIDE}?mid={media_id}", "mime_type": mime,
                "sha256": "x", "file_size": len(data), "id": media_id,
            })
        if url.startswith(LOOKASIDE):
            assert authed
            return httpx.Response(200, content=self.media[request.url.params["mid"]][0])
        return httpx.Response(200, content=b"png bytes", headers={"content-type": "image/png"})
