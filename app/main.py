"""
גבר — FastAPI server.

Webhook נכנס מ-Meta WhatsApp Cloud API:
  GET  /webhook  — אימות (hub.challenge) מול verify_token.
  POST /webhook  — הודעות נכנסות (JSON) → app.pipeline → תשובה ב-WhatsApp.
"""

import logging

from fastapi import FastAPI, Request, Response

from app.config import settings
from app.pipeline import handle_inbound

log = logging.getLogger("gever")
app = FastAPI(title="גבר / Gever", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "gever"}


@app.get("/webhook")
async def verify(request: Request) -> Response:
    """אימות ה-webhook מול Meta — מחזירים את hub.challenge אם ה-token תואם."""
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == settings.whatsapp_verify_token:
        return Response(content=p.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive(request: Request) -> Response:
    """הודעות נכנסות מ-Meta. עונים 200 מהר; השיחה/ההזמנה מטופלות ב-pipeline."""
    data = await request.json()
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "text":
                        await handle_inbound(msg["from"], msg["text"]["body"])
    except Exception:
        log.exception("webhook handling failed")
    return Response(status_code=200)
