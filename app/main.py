"""
גבר — FastAPI server.

Webhook נכנס מ-Meta WhatsApp Cloud API:
  GET  /webhook  — אימות (hub.challenge) מול verify_token.
  POST /webhook  — הודעות נכנסות (JSON) → app.pipeline → תשובה ב-WhatsApp.
"""

import hashlib
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.automation.browser_book import sweep_orphan_sessions
from app.config import settings
from app.pipeline import handle_inbound

log = logging.getLogger("gever")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # סשני keepAlive של ריצה שמתה (redeploy באמצע הזמנה) מחויבים באידל עד 30 דק' —
    # מנקים בעלייה. best-effort: כשל בניקוי לא מפיל את השרת.
    if settings.bu_browser == "browserbase" and settings.browserbase_api_key:
        try:
            n = await sweep_orphan_sessions()
            if n:
                log.info("released %d orphan browserbase session(s) on startup", n)
        except Exception:  # noqa: BLE001
            log.warning("orphan session sweep failed", exc_info=True)
    yield


app = FastAPI(title="גבר / Gever", version="0.1.0", lifespan=lifespan)


def _valid_signature(body: bytes, header: str | None) -> bool:
    """אימות X-Hub-Signature-256 מול app secret. בלי secret מוגדר → מדלג (dev)."""
    secret = settings.whatsapp_app_secret
    if not secret:
        return True  # gated: אין secret → לא מאמתים (test/dev). חובה להגדיר לפני קהל.
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "gever"}


@app.get("/webhook")
async def verify(request: Request) -> Response:
    """אימות ה-webhook מול Meta — מחזירים את hub.challenge אם ה-token תואם."""
    p = request.query_params
    if (
        p.get("hub.mode") == "subscribe"
        and p.get("hub.verify_token") == settings.whatsapp_verify_token
    ):
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request) -> Response:
    """הודעות נכנסות מ-Meta. עונים 200 מהר; השיחה/ההזמנה מטופלות ב-pipeline."""
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("rejected webhook: bad X-Hub-Signature-256")
        return Response(status_code=403)
    data = json.loads(body or b"{}")
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "text":
                        await handle_inbound(msg["from"], msg["text"]["body"], msg.get("id"))
                    elif msg.get("type") == "interactive":
                        # בחירה מרשימה/כפתור → נכנסת לשיחה כטקסט רגיל (השם המלא
                        # ב-description כשהכותרת נחתכה ל-24 תווים).
                        r = (
                            (msg.get("interactive") or {}).get("list_reply")
                            or (msg.get("interactive") or {}).get("button_reply")
                            or {}
                        )
                        choice = r.get("description") or r.get("title")
                        if choice:
                            await handle_inbound(msg["from"], choice, msg.get("id"))
    except Exception:
        log.exception("webhook handling failed")
    return Response(status_code=200)
