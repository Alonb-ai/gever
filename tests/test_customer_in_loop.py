"""לקוח-בלולאה (ליבה): אתר דורש קוד SMS / ת"ז באמצע ריצה → גבר שואל בוואטסאפ
(דחוף-אך-רגוע), התשובה מנותבת דטרמיניסטית ל-resume באותו סשן, והקלט הרגיש
לא נשמר בשום מקום קבוע — לא בפרופיל, לא ב-prefs, לא ב-_flow."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import bu_runner  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

CODE = "123456"
PHONE = "pOTP"


def _reset():
    for d in (
        pipeline._booking,
        pipeline._pending_commit,
        pipeline._resume,
        pipeline._resolved,
        pipeline._pending_pick,
        pipeline._preresolve,
        pipeline._await_answer,
        pipeline._sensitive,
        pipeline._turns,
        pipeline._last_out,
        pipeline._nudge,
    ):
        d.clear()


def _harness(monkeypatch, book_results: list, upserts: list):
    """resolve/book/שליחה/זיכרון מזויפים; converse אסור (הקוד לא עובר דרך המודל)."""
    _reset()
    sent, calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, labels):
        sent.append(body)

    async def fake_resolve(name):
        calls.append("resolve")
        return {"status": "one", "url": "http://fresh", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        calls.append(("book", kwargs))
        return book_results.pop(0)

    async def fake_release(session_id):
        pass

    async def fake_get_profile(phone):
        return {"prefs": {}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    async def no_converse(phone, text):
        raise AssertionError("converse must not see sensitive input")

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "release_session", fake_release)
    monkeypatch.setattr(pipeline, "converse", no_converse)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    return sent, calls


FIELDS = {
    "task_type": "restaurant",
    "restaurant": "הדסון",
    "date": "6.7",
    "time": "20:00",
    "party_size": 2,
    "name": "אלון",
}


def _missing(field: str, **details) -> ActionResult:
    d = {"missing": field, "session_id": "sess-9", "stage": f"עצרתי על {field}"}
    d.update(details)
    return ActionResult(success=False, summary=f"MISSING:{field}", details=d)


# ─── ה-task: לעולם לא ממציאים קוד/ת"ז (עוגן טקסט) ────────────────────────────


def test_task_forbids_inventing_code_and_id():
    job = {"url": "http://x", "party_size": 2, "date": "6.7", "time": "20:00", "dry_run": True}
    for variant in (job, {**job, "resume": {"recap": "עצרתי על קוד"}}):
        task = bu_runner._build_task(variant)
        assert "MISSING:sms_code" in task
        assert "MISSING:id_number" in task
        assert "אל תמציא ואל תנחש קוד" in task  # החוזה: עצירה, לא המצאה
        assert 'לעולם אל תמציא ת"ז' in task


# ─── הניסוחים: בדמות, עם העוגנים ─────────────────────────────────────────────


def test_sensitive_repertoire_in_character():
    anchors = {
        "sms_code": lambda m: "קוד" in m and ("פג" in m or "דקות" in m),
        "id_number": lambda m: "תעודת זהות" in m and ("לא נשמר" in m or "לא שומר" in m),
    }
    assert set(pipeline.SENSITIVE_MSGS) == set(pipeline.SENSITIVE_FIELDS) == set(anchors)
    assert set(pipeline._MASKED_TURN) == set(pipeline.SENSITIVE_FIELDS)
    for field, msgs in pipeline.SENSITIVE_MSGS.items():
        assert len(msgs) >= 2
        assert len(set(msgs)) == len(msgs)
        assert all(not character_leaks(m) for m in msgs)
        assert all(anchors[field](m) for m in msgs)


# ─── זיהוי הקלט בתשובת הלקוח ─────────────────────────────────────────────────


def test_sensitive_value_detection():
    v = pipeline._sensitive_value
    assert v("123456", "sms_code") == "123456"
    assert v("הקוד הוא 12-34 56", "sms_code") == "123456"  # רווחים/מקפים מנוקים
    assert v("מה זה הקוד?", "sms_code") == ""  # שאלה — לא קוד → converse
    assert v("0501234567", "sms_code") == ""  # מספר טלפון, לא OTP
    assert v("034567891", "id_number") == "034567891"
    assert v("1234", "id_number") == ""  # קצר מדי לת"ז


# ─── העצירה: שאלה נכונה + נדנוד מהיר ל-OTP ───────────────────────────────────


def test_sms_stop_asks_urgently_and_arms_fast_nudge(monkeypatch):
    upserts: list = []
    sent, calls = _harness(monkeypatch, [_missing("sms_code")], upserts)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 60)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_OTP_S", 0.01)

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))
        question = sent[-1]
        await asyncio.sleep(0.1)  # הנדנוד המהיר יורה בחלון הזה, הרגיל (60) לא
        return question

    question = asyncio.run(main())
    assert "קוד" in question and ("פג" in question or "דקות" in question)
    assert pipeline._await_answer[PHONE]["field"] == "sms_code"
    assert pipeline._resume[PHONE]["session_id"] == "sess-9"  # הסשן מחכה חי
    assert "תשובה" in sent[-1]  # נדנוד ה-question הגיע מהר — OTP פג תוך דקות


def test_id_stop_asks_in_character_with_normal_nudge(monkeypatch):
    upserts: list = []
    sent, calls = _harness(monkeypatch, [_missing("id_number")], upserts)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 0.01)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_OTP_S", 60)

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))
        question = sent[-1]
        await asyncio.sleep(0.1)  # ת"ז ממתינה בקצב הרגיל (NUDGE_DELAY_S)
        return question

    question = asyncio.run(main())
    assert "תעודת זהות" in question
    assert "תשובה" in sent[-1]  # הנדנוד הרגיל נדרך ויורה


# ─── התשובה: ניתוב ישיר ל-resume, בלי converse ובלי resolve מחדש ─────────────


def test_answer_routes_directly_to_resume(monkeypatch):
    upserts: list = []
    ok = ActionResult(success=True, summary="SUMMARY_REACHED", details={})
    sent, calls = _harness(monkeypatch, [_missing("sms_code"), ok], upserts)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 60)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_OTP_S", 60)

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))
        await pipeline._handle_inbound_inner(PHONE, f"הקוד: {CODE}")
        await asyncio.gather(*list(pipeline._pending))
        pipeline._cancel_nudge(PHONE)

    asyncio.run(main())
    books = [c for c in calls if isinstance(c, tuple)]
    assert calls.count("resolve") == 1  # רק הריצה הראשונה — התשובה לא עשתה resolve
    assert books[1][1]["resume"]["session_id"] == "sess-9"  # אותו סשן, אותו מסך
    assert f"sms_code: {CODE}" in books[1][1]["notes"]  # הקוד הגיע ל-agent דרך ה-notes
    assert pipeline._sensitive == {}  # נצרך ונמחק — לא נשאר בזיכרון
    assert PHONE not in pipeline._await_answer


def test_question_instead_of_code_falls_to_converse(monkeypatch):
    upserts: list = []
    sent, calls = _harness(monkeypatch, [_missing("sms_code")], upserts)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 60)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_OTP_S", 60)
    convs = []

    async def fake_converse(phone, text):
        convs.append(text)
        return {"reply": "זה קוד שקיבלת עכשיו ב-SMS, תעביר לי אותו", "ready": False}

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))
        monkeypatch.setattr(pipeline, "converse", fake_converse)
        await pipeline._handle_inbound_inner(PHONE, "רגע, איזה קוד?")
        pipeline._cancel_nudge(PHONE)

    asyncio.run(main())
    assert convs == ["רגע, איזה קוד?"]  # הבהרה — כן עוברת דרך השיחה
    assert pipeline._sensitive == {}
    assert len([c for c in calls if isinstance(c, tuple)]) == 1  # לא נורתה ריצה שנייה


# ─── אי-שמירה: הקוד לא מגיע לשום מקום קבוע ───────────────────────────────────


def test_sensitive_value_never_persisted(monkeypatch):
    """המסלול המלא, כולל agent שמהדהד את הקוד בדיווח שלו (stage/steps_tail/summary)
    ועוצר שוב על שדה אחר: שום upsert (פרופיל/prefs/_flow/_chat) ושום תור שיחה
    לא מכילים את הקוד. במקומו — עדות מסוככת בזיכרון השיחה."""
    upserts: list = []
    echo = ActionResult(
        success=False,
        summary=f"הקוד {CODE} הוזן. MISSING:seating_area",
        details={
            "missing": "seating_area",
            "session_id": "sess-9",
            "stage": f"הזנתי את הקוד {CODE} ועצרתי על ישיבה",
            "steps_tail": f"step: הקלדתי {CODE} בשדה האימות",
            "options": ["בפנים", "בחוץ"],
        },
    )
    sent, calls = _harness(monkeypatch, [_missing("sms_code"), echo], upserts)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 60)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_OTP_S", 60)

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))
        await pipeline._handle_inbound_inner(PHONE, CODE)
        await asyncio.gather(*list(pipeline._pending))
        pipeline._cancel_nudge(PHONE)

    asyncio.run(main())
    persisted = json.dumps([p for p in upserts if p], ensure_ascii=False)
    assert CODE not in persisted  # לא בפרופיל, לא ב-prefs, לא ב-_flow, לא ב-_chat
    turns = json.dumps(pipeline._turns.get(PHONE) or [], ensure_ascii=False)
    assert CODE not in turns
    assert any("קוד אימות נמסר" in t["text"] for t in pipeline._turns[PHONE])  # העדות המסוככת
    assert CODE not in (pipeline._resume[PHONE]["recap"] or "")  # ה-recap המותמד סוכך
    assert CODE not in pipeline._booking[PHONE].get("tail", "")  # וגם זנב יומן-הצעדים
    assert CODE not in json.dumps(pipeline._await_answer.get(PHONE) or {}, ensure_ascii=False)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
