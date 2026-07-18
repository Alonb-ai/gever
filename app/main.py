"""
גבר — FastAPI server.

Webhook נכנס מ-Meta WhatsApp Cloud API:
  GET  /webhook  — אימות (hub.challenge) מול verify_token.
  POST /webhook  — הודעות נכנסות (JSON) → app.pipeline → תשובה ב-WhatsApp.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from app import live_link
from app.automation.browser_book import sweep_orphan_sessions
from app.config import settings
from app.db import memory
from app.pipeline import _spawn, _vary, handle_inbound, handle_voice
from app.whatsapp.client import send_text

log = logging.getLogger("gever")

KEEPALIVE_INTERVAL_S = 24 * 60 * 60


async def _supabase_keepalive() -> None:
    """שאילתה יומית קלה ל-Supabase — פרויקט חינמי מושהה אחרי ~שבוע בלי תעבורה
    (קרה 14.7: NXDOMAIN, כל הזיכרון כבוי בשקט). רץ כל עוד השרת חי (פרוד = 24/7).
    recent_bookings בולע כשלים בעצמו, אז הלולאה לא מתה על תקלת רשת."""
    while True:
        await memory.recent_bookings("_keepalive")
        await asyncio.sleep(KEEPALIVE_INTERVAL_S)


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
    # התאוששות יתומים: redeploy באמצע הזמנה הרג אותה בדממה (נצפה חי 3 פעמים) —
    # הלקוח חיכה לכלום. עכשיו גבר מתנצל ומבקש לשלוח שוב.
    try:
        orphans = await memory.list_inflight()
    except Exception:  # noqa: BLE001
        orphans = []
        log.warning("orphan booking recovery failed", exc_info=True)
    for o in orphans:
        try:  # פר-יתום: כשל אחד (שליחה/ניקוי) לא מאבד את שאר היתומים
            await memory.clear_inflight(o["phone"])
            what = f" של {o['restaurant']}" if o.get("restaurant") else ""
            await send_text(
                o["phone"],
                _vary(
                    f"סורי נפלתי באמצע ההזמנה{what} 😮‍💨\nעוד הודעה אחת ממך ואני סוגר את זה",
                    f"נפלתי באמצע ההזמנה{what}, סליחה על זה 🫠\nרק לכתוב לי שוב מה רצית ואני עליה",
                    f"אוף, נפלתי באמצע ההזמנה{what} 😮‍💨\nאם זה עדיין רלוונטי — הודעה ואני סוגר",
                ),
            )
            log.info("orphan booking recovered for %s (%s)", o["phone"], o.get("restaurant"))
        except Exception:  # noqa: BLE001
            log.warning("orphan recovery failed for %s", o.get("phone"), exc_info=True)
    keepalive = asyncio.create_task(_supabase_keepalive())
    yield
    keepalive.cancel()
    with suppress(asyncio.CancelledError):
        await keepalive


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


@app.get("/b/{token}")
async def gever_browser(token: str) -> HTMLResponse:
    """דפדפן גבר — עמוד עטיפה ממותג ל-Live View של סשן חי (קיר-כרטיס).
    הלקוח מקבל https://geverai.duckdns.org/b/xxx בוואטסאפ; browserbase לא נחשף."""
    html = live_link.page_for(token)
    if not html:
        return HTMLResponse(live_link.EXPIRED_HTML, status_code=404)
    return HTMLResponse(html)


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


# dedupe להודעות נכנסות: Meta שולחת את אותו webhook שוב אם לא ענינו 200 מהר,
# ולפעמים סתם פעמיים — בלי זה הלקוח קיבל שתי תשובות פרידה מלאות ושונות על
# אותה הודעת סיום (נצפה חי 15.7).
_seen_msg_ids: OrderedDict = OrderedDict()  # msg_id -> None, מוגבל ל-500 אחרונים


def _already_handled(msg_id: str | None) -> bool:
    """True אם ההודעה הזאת כבר טופלה (retry/כפילות של Meta). בלי id — מטפלים."""
    if not msg_id:
        return False
    if msg_id in _seen_msg_ids:
        return True
    _seen_msg_ids[msg_id] = None
    while len(_seen_msg_ids) > 500:
        _seen_msg_ids.popitem(last=False)
    return False


STALE_MSG_S = 600  # הודעה נכנסת ישנה מ-10 דק' = שידור חוזר של Meta אחרי השבתה


def _is_stale(msg: dict) -> bool:
    """ה-dedupe חי בזיכרון התהליך ומת בכל deploy — אחרי השבתה Meta משדרת מחדש
    הודעות ישנות שלא אושרו, וגבר עיבד בקשת קלארו בת שעה כאילו נשלחה עכשיו
    (נצפה חי 17.7 אחרי תקלת ה-env). ה-timestamp של Meta הוא עוגן אמין שלא
    תלוי בזיכרון שלנו."""
    ts = msg.get("timestamp")
    if not ts:
        return False  # timestamp חסר — עדיף לטפל מאשר להשתיק
    try:
        return time.time() - int(ts) > STALE_MSG_S
    except (TypeError, ValueError):
        return False


async def _process_webhook(data: dict) -> None:
    """העיבוד עצמו — רץ ברקע אחרי שה-200 כבר נשלח למטא (סדרתי בתוך ה-payload,
    כדי ששתי הודעות של אותו לקוח לא ירוצו במקביל זו על זו)."""
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if _already_handled(msg.get("id")):
                        log.info("duplicate webhook message skipped: %s", msg.get("id"))
                        continue
                    if _is_stale(msg):
                        log.info("stale webhook message skipped: %s", msg.get("id"))
                        continue
                    if msg.get("type") == "text":
                        await handle_inbound(msg["from"], msg["text"]["body"], msg.get("id"))
                    elif msg.get("type") == "audio":
                        # הודעה קולית (voice=true) או קובץ אודיו — תמלול ואז אותו
                        # מסלול כמו טקסט. audio.id = media_id להורדה מה-Media API.
                        media_id = (msg.get("audio") or {}).get("id")
                        if media_id:
                            await handle_voice(msg["from"], media_id, msg.get("id"))
                    elif msg.get("type") == "interactive":
                        # בחירה מרשימה/כפתור → נכנסת לשיחה כטקסט רגיל (השם המלא
                        # ב-description כשהכותרת נחתכה ל-24 תווים).
                        i = msg.get("interactive") or {}
                        r = i.get("list_reply") or i.get("button_reply") or {}
                        choice = r.get("description") or r.get("title")
                        if choice:
                            await handle_inbound(msg["from"], choice, msg.get("id"))
    except Exception:
        log.exception("webhook handling failed")


@app.post("/webhook")
async def receive(request: Request) -> Response:
    """הודעות נכנסות מ-Meta. 200 *מיידי* — העיבוד (Gemini+שליחות, שניות ארוכות)
    רץ ברקע. לחכות איתו לפני ה-200 גרם ל-retry של מטא ותשובות כפולות (15.7)."""
    body = await request.body()
    if not _valid_signature(body, request.headers.get("X-Hub-Signature-256")):
        log.warning("rejected webhook: bad X-Hub-Signature-256")
        return Response(status_code=403)
    try:
        # בתוך ה-try: גוף לא-JSON החזיר 500 ומטא עשה retry בלולאה — עכשיו 200 ולוג
        data = json.loads(body or b"{}")
    except Exception:
        log.exception("webhook body parse failed")
        return Response(status_code=200)
    _spawn(_process_webhook(data))
    return Response(status_code=200)
