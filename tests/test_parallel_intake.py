"""אינטייק מקבילי (רעיון אלון): בזמן שריצת דפדפן רצה גבר שואל מראש את מה שצפוי
לעצור אותה (העדפת ישיבה + גמישות שעה). התשובה נקלטת דטרמיניסטית ל-_prefetched
(בזיכרון בלבד) ונצרכת בקיר MISSING — resume מיידי בלי שאלה שנייה. אין תשובה →
הזרימה של היום בדיוק; הריצה נגמרה בלי קיר → התשובה נזרקת ולא מתפוצצת."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

PHONE = "pINTAKE"
FIELDS = {
    "task_type": "restaurant",
    "restaurant": "הדסון",
    "date": "6.7",
    "time": "20:00",
    "party_size": 2,
    "name": "אלון",
}


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
        pipeline._prefetched,
        pipeline._turns,
        pipeline._last_out,
        pipeline._nudge,
    ):
        d.clear()


def _harness(monkeypatch, book_results: list):
    """resolve מדולג (_resolved חם); book מזויף *עם השהיה* — כדי שה-task המקביל
    של האינטייק יקבל תור לרוץ, כמו בריצה אמיתית שנמשכת דקות."""
    _reset()
    sent, calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, labels):
        sent.append(body)

    async def fake_book(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0.03)  # ריצה "ארוכה" — האינטייק נשלח בזמן הזה
        return book_results.pop(0)

    async def fake_release(session_id):
        pass

    async def fake_get_profile(phone):
        return {"prefs": {}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "release_session", fake_release)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(pipeline, "NUDGE_DELAY_S", 60)
    pipeline._resolved[PHONE] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}
    return sent, calls


def _fail() -> ActionResult:
    return ActionResult(success=False, summary="fail", details={"failed": "no_availability"})


def _missing(field: str, **details) -> ActionResult:
    d = {"missing": field, "session_id": "sess-1", "stage": f"עצרתי על {field}"}
    d.update(details)
    return ActionResult(success=False, summary=f"MISSING:{field}", details=d)


def _ok() -> ActionResult:
    return ActionResult(success=True, summary="SUMMARY_REACHED", details={})


# ─── זיהוי התשובה (יחידה) ────────────────────────────────────────────────────


def test_intake_answer_detection():
    a = pipeline._intake_answer
    assert a("בפנים") == {"seating_area": "בפנים"}
    assert a("עדיף בחוץ") == {"seating_area": "בחוץ"}
    assert a("על הבר") == {"seating_area": "בר"}
    assert a("אפשר בבר") == {"seating_area": "בר"}
    assert a("ברור שכן") == {}  # "בר" בתוך מילה — לא העדפה
    assert a("גמיש לגמרי") == {"time_flexible": True}
    assert a("לא גמיש בשעה") == {}  # שלילה — לא הסכמה
    assert a("בפנים ובשעה גמיש") == {"seating_area": "בפנים", "time_flexible": True}
    assert a("או בפנים או בחוץ") == {}  # דו-משמעי — לא מחליטים בשבילו
    assert a("מה השעה שסגרת?") == {}  # שאלה — ממשיכה ל-converse


# ─── השאלה נורית רק כשחסר מידע ───────────────────────────────────────────────


def test_question_fired_when_seating_unknown(monkeypatch):
    sent, calls = _harness(monkeypatch, [_fail()])
    asyncio.run(pipeline.run_booking(PHONE, dict(FIELDS)))
    assert any("בפנים" in m and "?" in m for m in sent)  # שאלת-הביניים נשלחה
    assert PHONE in pipeline._prefetched  # מסומן: השאלה נשאלה, תשובות ייקלטו


def test_question_skipped_when_seating_in_notes(monkeypatch):
    sent, calls = _harness(monkeypatch, [_fail()])
    asyncio.run(pipeline.run_booking(PHONE, {**FIELDS, "notes": "בחוץ — מעשנים"}))
    assert not any("בפנים" in m for m in sent)  # יש רמז ישיבה — אין שאלה
    assert PHONE not in pipeline._prefetched


# ─── תשובה בזמן ריצה נצרכת בקיר — resume בלי שאלה שנייה ──────────────────────


def test_mid_run_answer_consumed_at_seating_wall(monkeypatch):
    sent, calls = _harness(monkeypatch, [_missing("seating_area"), _ok()])

    async def main():
        run = asyncio.create_task(pipeline.run_booking(PHONE, dict(FIELDS)))
        await asyncio.sleep(0.01)  # השאלה המקבילית כבר נשלחה
        await pipeline._handle_inbound_inner(PHONE, "בפנים")
        await run
        await asyncio.gather(*list(pipeline._pending))  # ה-relaunch שנורה בקיר
        pipeline._cancel_nudge(PHONE)

    asyncio.run(main())
    assert len(calls) == 2  # ריצה + resume מיידי, בלי המתנת-אדם
    assert "seating_area: בפנים" in calls[1]["notes"]  # התשובה הגיעה ל-agent
    assert calls[1]["resume"]["session_id"] == "sess-1"  # אותו סשן, אותו מסך
    assert not any("העדפת ישיבה" in m for m in sent)  # לא נשאלה שאלה שנייה
    assert PHONE not in pipeline._await_answer
    assert PHONE not in pipeline._prefetched  # נצרך ונמחק
    assert any("קיבלתי" in m or "קלטתי" in m or "רשמתי" in m for m in sent)  # ack לתשובה
    turns = [t["text"] for t in pipeline._turns[PHONE]]
    assert "בפנים" in turns  # התור נכנס לזיכרון השיחה


def test_mid_run_flexibility_consumed_at_time_wall(monkeypatch):
    sent, calls = _harness(monkeypatch, [_missing("time", options=["19:30", "21:00"]), _ok()])

    async def main():
        run = asyncio.create_task(pipeline.run_booking(PHONE, dict(FIELDS)))
        await asyncio.sleep(0.01)
        await pipeline._handle_inbound_inner(PHONE, "השעה גמישה לגמרי")
        await run
        await asyncio.gather(*list(pipeline._pending))
        pipeline._cancel_nudge(PHONE)

    asyncio.run(main())
    assert len(calls) == 2
    assert calls[1]["time_flex"] is True  # ה-agent החוזר רשאי לסגור שעה קרובה
    assert calls[1]["resume"]["session_id"] == "sess-1"
    assert PHONE not in pipeline._await_answer  # לא נפתחה שאלת חלופות ללקוח


# ─── אין תשובה → העצירה הרגילה של היום (אפס רגרסיה) ──────────────────────────


def test_no_answer_falls_to_regular_stop(monkeypatch):
    sent, calls = _harness(monkeypatch, [_missing("seating_area", options=["בפנים", "בחוץ"])])
    asyncio.run(pipeline.run_booking(PHONE, dict(FIELDS)))
    assert len(calls) == 1  # אין relaunch — מחכים ללקוח כרגיל
    assert pipeline._await_answer[PHONE]["field"] == "seating_area"
    assert pipeline._booking[PHONE]["state"] == "missing"


# ─── תשובה אחרי שהריצה נגמרה — לא מתפוצצת, converse רגיל ─────────────────────


def test_late_answer_after_run_ended_goes_to_converse(monkeypatch):
    sent, calls = _harness(monkeypatch, [_fail()])
    convs = []

    async def fake_converse(phone, text):
        convs.append(text)
        return {"reply": "סבבה", "ready": False}

    async def main():
        await pipeline.run_booking(PHONE, dict(FIELDS))  # נגמרה (failed), השאלה נשאלה
        monkeypatch.setattr(pipeline, "converse", fake_converse)
        await pipeline._handle_inbound_inner(PHONE, "בפנים")

    asyncio.run(main())
    assert convs == ["בפנים"]  # state≠working — התשובה המאוחרת זורמת לשיחה
