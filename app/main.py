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

from fastapi import FastAPI, Request, Response

from app.config import settings
from app.pipeline import handle_inbound

log = logging.getLogger("gever")
app = FastAPI(title="גבר / Gever", version="0.1.0")


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
    except Exception:
        log.exception("webhook handling failed")
    return Response(status_code=200)
