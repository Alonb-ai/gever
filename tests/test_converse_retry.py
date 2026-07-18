"""קראש 18.7 ("עמוס אצלי" בלי פריצת מכסה): כשל חד-פעמי של קריאת המודל ב-converse —
5xx רגעי, תשובה בלי חלקי טקסט (resp.text=None) או JSON קטוע — נפל ישר לרשת
הביטחון של handle_inbound: הלקוח קיבל busy והודעתו אבדה מזיכרון השיחה (טביעת
האצבע מה-DB: הודעת busy בלי תור user לפניה). הדרישה: ניסיון שני שקוף עם chat
טרי; כשל עקבי (מכסה/רשת למטה) עדיין מטפס לרשת הביטחון — זה תפקידה."""

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock

import pytest
from google import genai

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402

PHONE = "+972500000099"
GOOD = {"reply": "סבבה אחי", "ready": False}


class _FakeChats:
    """מפעל chats עם תסריט כשלים משותף בין יצירות — retry יוצר chat טרי חדש."""

    def __init__(self, script):
        self.script = list(script)  # "api_error" | "none_text" | "bad_json" ואז ok
        self.creates = 0
        self.sends = 0
        self.last_history = None

    def create(self, *, model, config, history):
        self.creates += 1
        self.last_history = history
        factory = self

        class _Chat:
            def send_message(self, msg):
                factory.sends += 1
                step = factory.script.pop(0) if factory.script else "ok"
                if step == "api_error":
                    raise genai.errors.APIError(500, {"error": {"message": "Internal error"}})
                r = type("R", (), {})()
                if step == "none_text":
                    r.text = None  # תשובה בלי חלקי טקסט (חסימה/קיצוץ תקציב חשיבה)
                elif step == "bad_json":
                    r.text = '{"reply": "נחת'  # JSON קטוע באמצע
                else:
                    r.text = json.dumps(GOOD)
                return r

        return _Chat()


def _setup(monkeypatch, script):
    """מאפס מצב מודול, מזייף client עם תסריט הכשלים, ומנטרל את שכבת הזיכרון."""
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._reset_next.clear()
    pipeline._booking.clear()
    pipeline._await_answer.clear()
    pipeline._recs.clear()

    fake = _FakeChats(script)
    client = type("C", (), {"chats": fake})()
    monkeypatch.setattr(pipeline, "_client", client)
    monkeypatch.setattr(memory, "get_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(memory, "recent_bookings", AsyncMock(return_value=[]))
    monkeypatch.setattr(memory, "upsert_profile", AsyncMock())
    # שיחה חמה קיימת — כמו המשתמשת מה-18.7 (לא מגע ראשון, בלי דף חדש)
    pipeline._turns[PHONE] = [{"role": "user", "text": "היי", "ts": time.time() - 60}]
    pipeline._last_seen[PHONE] = time.time() - 60
    return fake


@pytest.mark.parametrize("failure", ["api_error", "none_text", "bad_json"])
def test_transient_model_failure_gets_second_attempt(monkeypatch, failure):
    """כשל חד-פעמי (בדיוק התרחיש מ-18.7) → ניסיון שני שקוף: תשובה רגילה,
    והודעת הלקוח נשמרת בזיכרון השיחה במקום להיעלם."""
    fake = _setup(monkeypatch, [failure])
    result = asyncio.run(pipeline.converse(PHONE, "יש לך עוד המלצות?"))
    assert result["reply"] == GOOD["reply"]
    assert fake.sends == 2  # ניסיון אחד נכשל + ניסיון שני הצליח
    texts = [t["text"] for t in pipeline._turns[PHONE]]
    assert "יש לך עוד המלצות?" in texts  # התור לא אבד — טביעת האצבע מה-DB נרפאה


def test_persistent_failure_still_climbs_to_safety_net(monkeypatch):
    """שני כשלים רצופים (מכסה/רשת באמת למטה) → החריגה מטפסת, ורשת הביטחון של
    handle_inbound עדיין שולחת ללקוח הודעת busy — לא דממה ולא לולאת retry."""
    fake = _setup(monkeypatch, ["api_error", "api_error"])
    sent = []

    async def fake_send(phone, text, *a, **k):
        sent.append(text)

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(pipeline, "send_typing", AsyncMock())
    asyncio.run(pipeline.handle_inbound(PHONE, "יש לך עוד המלצות?", None))
    assert fake.sends == 2  # בדיוק retry אחד — לא לולאה
    assert len(sent) == 1
    busy_pool = (
        "וואלה עמוס אצלי ברגעים אלו 🫠 כתוב לי שוב בעוד כמה דקות?",
        "משהו אצלי תקוע רגע — נסה שוב עוד כמה דקות 🔄",
        "יש עומס קטן בצד שלי, תכתוב לי שוב עוד מעט ואני איתך 🤝",
    )
    assert sent[0] in busy_pool


def test_retry_preserves_fresh_page_flag(monkeypatch):
    """_chat_for צורך את דגל הדף-החדש (_reset_next) בניסיון הראשון — ה-retry חייב
    לראות אותו שוב, אחרת שיחה שסומנה לאיפוס חוזרת עם ההיסטוריה הישנה."""
    fake = _setup(monkeypatch, ["api_error"])
    pipeline._reset_next.add(PHONE)
    result = asyncio.run(pipeline.converse(PHONE, "שלום"))
    assert result["reply"] == GOOD["reply"]
    assert fake.last_history == []  # גם הניסיון השני נבנה על דף חדש
