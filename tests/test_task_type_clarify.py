"""ממצא בטא #5 ("האודיסאה" סווג כמסעדה): סיווג מסעדה/סרט נעשה מההקשר של הבקשה,
וכשה-extract לא בטוח — לא מנחשים אלא שואלים שאלת הבהרה קצרה (הנחיית אלון, בלי
רשימות שמות סרטים). נועלים את הדטרמיניסטי: הסכמה (ערך unsure), הנחיית ההקשר
ב-_EXTRACT, ומסלול ההבהרה — unsure לא יוצא לריצה אלא שואל."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402


def test_schema_allows_unsure():
    """ה-decoding המוגבל חייב לאפשר למודל להגיד 'לא בטוח' — אחרת הוא נאלץ לנחש."""
    assert pipeline._SCHEMA["properties"]["task_type"]["enum"] == [
        "restaurant",
        "cinema",
        "events",
        "insurance",
        "recommend",
        "other",
        "unsure",
    ]


def test_extract_guides_context_classification():
    """הנחיית ההקשר בפרומפט: סיווג לפי סימני הבקשה, חשד-לסרט, ואי-ודאות = שאלה."""
    assert "unsure" in pipeline._EXTRACT
    assert "הקשר" in pipeline._EXTRACT
    assert "חשד לסרט" in pipeline._EXTRACT
    assert "אל תנחש" in pipeline._EXTRACT
    assert "ready=false" in pipeline._EXTRACT  # אי-ודאות לא יוצאת לריצה


def test_clarify_intent_card_anchors():
    """כרטיס הכוונה של ההבהרה קיים ונועל את העוגנים: מסעדה, סרט, וסימן שאלה."""
    card = pipeline.INTENTS["clarify_task_type"]
    assert set(card["must"]) == {r"מסעדה", r"סרט", r"\?"}


@pytest.fixture
def _patch_io(monkeypatch):
    """לוכד הודעות; resolve/book מכל הסוגים אסורים במסלול unsure."""
    sent: list[str] = []
    called = {"resolve": False, "book": False}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(*a, **k):
        called["resolve"] = True
        return {"status": "none", "url": "", "candidates": []}

    async def fake_book(**kwargs):
        called["book"] = True
        raise AssertionError("book_table לא אמור להיקרא במסלול unsure")

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "resolve_cinema_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    pipeline._booking.clear()
    pipeline._turns.clear()
    pipeline._last_out.clear()
    return sent, called


def test_unsure_asks_clarification_no_run(_patch_io):
    """task_type=unsure → בלי resolve/book: שאלת הבהרה עם השם, מסעדה/סרט/?."""
    sent, called = _patch_io
    asyncio.run(pipeline.run_booking("u1", {"task_type": "unsure", "restaurant": "האודיסאה"}))
    assert called["resolve"] is False and called["book"] is False
    assert sent and "מסעדה" in sent[0] and "סרט" in sent[0] and "?" in sent[0]
    assert "האודיסאה" in sent[0]
    assert "u1" not in pipeline._booking  # נוקה — בלי state מטעה שיבלע את התור הבא


def test_unsure_without_name_still_asks(_patch_io):
    """גם בלי שם בכלל — שואלים מה סוגרים, לא מתפוצצים ולא רצים."""
    sent, called = _patch_io
    asyncio.run(pipeline.run_booking("u2", {"task_type": "unsure"}))
    assert called["resolve"] is False and called["book"] is False
    assert sent and "מסעדה" in sent[0] and "סרט" in sent[0]


def test_unsure_ready_from_converse_gated(monkeypatch, _patch_io):
    """המסלול המלא: ה-extract החזיר ready=true עם unsure (למרות ההנחיה) —
    handle_inbound משגר את run_booking, וזה עוצר על שאלת הבהרה במקום ריצה."""
    sent, called = _patch_io

    async def fake_converse(phone, text):
        return {"reply": "רגע", "ready": True, "task_type": "unsure", "restaurant": "האודיסאה"}

    async def fake_typing(message_id):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    pipeline._last_seen["u3"] = 10**12  # לא מגע ראשון — האונבורדינג לא חלק מהטסט

    async def go():
        await pipeline.handle_inbound("u3", "תזמין לי את האודיסאה בכפר סבא")
        for _ in range(3):
            await asyncio.sleep(0)
            if pipeline._pending:
                await asyncio.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(go())
    assert called["resolve"] is False and called["book"] is False
    assert any("מסעדה" in m and "סרט" in m for m in sent)
    assert "u3" not in pipeline._booking
