"""
גבר — FastAPI server (שלב 1).

נקודת הכניסה. כרגע: webhook נכנס מ-Twilio WhatsApp (POST form-encoded).
הלוגיקה האמיתית (intent → clarify → execute) תיכנס בשלבים 1-2.
"""

from fastapi import FastAPI, Form, Request

app = FastAPI(title="גבר / Gever", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "gever"}


@app.post("/webhook/twilio")
async def receive_message(request: Request, From: str = Form(""), Body: str = Form("")) -> dict:
    """
    הודעה נכנסת מ-Twilio. Twilio שולח form-encoded (From, Body, ...).
    TODO(stage1): אימות חתימה (X-Twilio-Signature) עם twilio_auth_token.
    TODO(stage1): From/Body -> app.llm.intent -> app.automation -> תשובה (whatsapp.client).
    """
    return {"received": True, "from": From}
