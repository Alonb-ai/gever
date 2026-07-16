"""ורטיקל הביטוח (פספורטכארד): חוזה ה-resolve הקבוע, ה-task וחוקי הברזל שלו,
timeout/max_steps, זרימת הפרמיה (extra) עד ההודעות, הגארדים שלפני ריצה,
וכשלי הביטוח הייחודיים (עוגן: *9912)."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import browser_book  # noqa: E402
from app.automation.browser_book import (  # noqa: E402
    BU_INSURANCE_TIMEOUT_S,
    BU_TIMEOUT_S,
    _timeout_s,
    book_table_bu,
)
from app.automation.bu_runner import _build_task  # noqa: E402
from app.automation.resolve import INSURANCE_URL, resolve_insurance_url  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

_INS = {
    "destination": "יוון",
    "return_date": "17.08",
    "travelers": ["15.05.1990", "20.11.1992"],
    "health": "אין",
    "addons": "",
}
_JOB = {
    "task_type": "insurance",
    "url": INSURANCE_URL,
    "date": "03.08",
    "party_size": 2,
    "time": "",
    "name": "אלון",
    "email": "a@b.com",
    "phone": "0540000000",
    "insurance": _INS,
}


def test_resolve_insurance_is_fixed_single_provider():
    """ספק יחיד: תמיד 'one', אותו חוזה החזרה כמו resolve_reservation_url."""
    found = asyncio.run(resolve_insurance_url())
    assert found["status"] == "one"
    assert found["url"] == INSURANCE_URL
    assert found["platform"] == "passportcard"
    assert found["candidates"][0]["url"] == INSURANCE_URL
    assert found["fallback"] is None


def test_insurance_task_carries_trip_iron_rules_and_markers():
    task = _build_task({**_JOB, "dry_run": True})
    # פרטי הנסיעה מוזרקים
    assert INSURANCE_URL in task and "יוון" in task and "17.08" in task
    assert "15.05.1990" in task and "20.11.1992" in task
    # חוקי ברזל: לקוח חדש, לא ממציאים פרטים, הצהרת בריאות = רק מהלקוח
    assert "לקוח קיים" in task
    assert "אסור להמציא" in task
    assert "הצהרה משפטית" in task
    # פרוטוקול האיסוף המרוכז: FIELD/OPTIONS ממופתחים + MISSING בשורה אחת
    # (סבב 2: היעד הוא מדינה מחיפוש טקסט חופשי — לא אזור/יבשת; לקח ריצה חיה 1)
    assert "FIELD" in task and "OPTIONS destination:" in task
    assert "MISSING:destination" in task and "שדה החיפוש" in task
    assert "מופרדים ב-| בלי" in task
    # markers + כישלונות ייחודיים
    assert "SUMMARY_REACHED" in task and "CARD_REQUIRED" in task
    assert "FAILED:manual_underwriting" in task
    assert "FAILED:phone_only" in task and "FAILED:blocked" in task
    # AGREED — שום הצהרה לא נחתמת בשקט; PERK נשאר
    assert "AGREED:" in task and "PERK" in task
    # recon עוצר לפני הכפתור הסופי; הצעת המחיר היא מסך הסיכום
    assert "אל תלחץ" in task and "הצעת המחיר היא מסך הסיכום" in task
    # ברירות מחדל כשאין הרחבות/בריאות
    assert "שום הרחבה" in task
    # commit tail קיים במצב אמת
    assert "BOOKED" in _build_task({**_JOB, "dry_run": False})


def test_insurance_resume_lists_form_answers_explicitly():
    job = {
        **_JOB,
        "dry_run": True,
        "resume": {"recap": "עצרתי בדף פרטי הנוסעים"},
        "form_answers": {"id_number": "123456782", "pickup_point": 'נתב"ג טרמינל 3'},
    }
    task = _build_task(job)
    assert "id_number = 123456782" in task
    assert 'pickup_point = נתב"ג טרמינל 3' in task
    assert "עצרתי בדף פרטי הנוסעים" in task
    assert "אל תנווט לכתובת אחרת" in task


def test_insurance_timeout_and_max_steps():
    assert _timeout_s({"task_type": "insurance"}) == BU_INSURANCE_TIMEOUT_S == 1200
    assert _timeout_s({}) == BU_TIMEOUT_S  # מסעדות — ללא שינוי


def test_book_table_bu_passes_insurance_job_and_extra(monkeypatch):
    """ה-job נושא task_type/insurance/form_answers + max_steps=80, וה-extra (הפרמיה)
    חוזר עד details ביחד עם שדות הפרוטוקול המרובה."""
    jobs = []

    async def fake_run(job):
        jobs.append(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump(
                {
                    "success": True,
                    "summary_reached": True,
                    "card_required": False,
                    "missing": "",
                    "missing_fields": [],
                    "options_by_field": {},
                    "field_labels": {},
                    "extra": "פרמיה $127.40 לכל הנסיעה",
                    "message": "SUMMARY_REACHED | פרמיה $127.40 לכל הנסיעה",
                },
                f,
            )

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(settings, "bu_record_dir", "")
    monkeypatch.setattr(settings, "bu_browser", "local")

    res = asyncio.run(
        book_table_bu(
            restaurant="ביטוח נסיעות ליוון",
            page_url=INSURANCE_URL,
            date="03.08",
            time="",
            party_size=2,
            dry_run=True,
            task_type="insurance",
            insurance=_INS,
            form_answers={"id_number": "123456782"},
        )
    )
    job = jobs[0]
    assert job["task_type"] == "insurance"
    assert job["insurance"]["destination"] == "יוון"
    assert job["form_answers"] == {"id_number": "123456782"}
    assert job["max_steps"] == 80
    assert res.details["extra"] == "פרמיה $127.40 לכל הנסיעה"
    assert res.details["missing_fields"] == []


def test_restaurant_job_keeps_forty_steps(monkeypatch):
    jobs = []

    async def fake_run(job):
        jobs.append(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            json.dump({"success": False, "message": "FAILED:closed", "failed": "closed"}, f)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(settings, "bu_record_dir", "")
    monkeypatch.setattr(settings, "bu_browser", "local")
    asyncio.run(
        book_table_bu(
            restaurant="הדסון", page_url="http://x", date="1.1", time="20:00", party_size=2
        )
    )
    assert jobs[0]["max_steps"] == 40 and jobs[0]["task_type"] == "restaurant"


def test_failure_reply_insurance_reasons_anchor_9912():
    for reason in ("manual_underwriting", "phone_only", "blocked"):
        hit = pipeline._failure_reply(reason, "ביטוח נסיעות ליוון", task_type="insurance")
        assert hit is not None, reason
        info, msg = hit
        assert "*9912" in msg
        assert not character_leaks(msg)
        # הסיבות האלה לא קיימות למסעדות — שם נשארת ההודעה הגנרית
        assert pipeline._failure_reply(reason, "הדסון") is None
    # info של חיתום נכנס ל-truth_note כטקסט קבוע שלנו
    assert "חיתום" in pipeline._failure_reply("manual_underwriting", "x", task_type="insurance")[0]


def test_schema_and_extract_carry_insurance_fields():
    props = pipeline._SCHEMA["properties"]
    for key in (
        "destination",
        "return_date",
        "travelers_birth_dates",
        "health_issues",
        "addons",
        "answers",
    ):
        assert key in props, key
    assert "insurance" in pipeline._SCHEMA["properties"]["task_type"]["enum"]
    assert "answers" in pipeline._EXTRACT and "health_issues" in pipeline._EXTRACT


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()
    pipeline._preresolve.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    pipeline._turns.clear()


_FIELDS = {
    "task_type": "insurance",
    "destination": "יוון",
    "date": "03.08",
    "return_date": "17.08",
    "travelers_birth_dates": ["15.05.1990", "20.11.1992"],
    "health_issues": "אין",
    "addons": "",
}


def _wire_booking(monkeypatch, book_result=None):
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        if book_result is None:
            raise AssertionError("book_table_bu לא אמור להיקרא — הגארד היה צריך לעצור קודם")
        fake_book.calls.append(kwargs)
        return book_result

    fake_book.calls = []

    async def fake_get_profile(phone):
        return None

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    return sent, fake_book


def test_positive_health_stops_before_browser_run(monkeypatch):
    """הצהרת בריאות חיובית → עצירה לפני ריצת דפדפן (חיתום טלפוני), עם עוגן *9912."""
    _reset()
    sent, _ = _wire_booking(monkeypatch, book_result=None)
    fields = {**_FIELDS, "health_issues": "נוטל תרופות קבועות ללחץ דם"}
    asyncio.run(pipeline.run_booking("p1", fields))
    assert pipeline._booking["p1"]["state"] == "failed"
    assert "*9912" in sent[-1]
    assert not character_leaks(sent[-1])


def test_age_85_plus_stops_before_browser_run(monkeypatch):
    _reset()
    sent, _ = _wire_booking(monkeypatch, book_result=None)
    fields = {**_FIELDS, "travelers_birth_dates": ["15.05.1990", "01.01.1935"]}
    asyncio.run(pipeline.run_booking("p1", fields))
    assert pipeline._booking["p1"]["state"] == "failed"
    assert "*9912" in sent[-1]


def test_missing_destination_asks_instead_of_running(monkeypatch):
    _reset()
    sent, _ = _wire_booking(monkeypatch, book_result=None)
    asyncio.run(pipeline.run_booking("p1", {**_FIELDS, "destination": ""}))
    assert "p1" not in pipeline._booking  # כמו guard השם במסעדות
    assert "נסיעה" in sent[-1] or "יעד" in sent[-1]


def test_unparsable_birth_date_does_not_trip_guard(monkeypatch):
    """תאריך לא-פריק מדולג — הטופס יכריע; הריצה יוצאת לדרך."""
    _reset()
    res = ActionResult(success=False, summary="FAILED:blocked", details={"failed": "blocked"})
    sent, book = _wire_booking(monkeypatch, book_result=res)
    fields = {**_FIELDS, "travelers_birth_dates": ["מחר", "15.05.1990"]}
    asyncio.run(pipeline.run_booking("p1", fields))
    assert book.calls  # הגיע לריצה
    assert "*9912" in sent[-1]  # blocked ממופה להודעת ביטוח


def test_insurance_card_wall_message_carries_quote_and_link(monkeypatch):
    """recon שנגמר בקיר-כרטיס: ההודעה נושאת את הפרמיה (extra) + לינק + AGREED."""
    _reset()
    res = ActionResult(
        success=True,
        summary="SUMMARY_REACHED CARD_REQUIRED",
        details={
            "card_required": True,
            "extra": "פרמיה $127.40 לכל הנסיעה",
            "agreed": ["תקנון ותנאי פוליסה"],
            "page_now": "",
            "session_id": None,
        },
    )
    sent, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", dict(_FIELDS)))
    msg = sent[-1]
    assert "פרמיה $127.40 לכל הנסיעה" in msg
    assert INSURANCE_URL in msg  # resolve קבוע — בלי Brave
    assert "אישרתי בשמך" in msg or "סימנתי בשמך" in msg
    assert not character_leaks(msg)
    assert pipeline._booking["p1"]["state"] == "card"
    # book_table_bu קיבל את חבילת הביטוח, בלי שעה, ו-party לפי מספר הנוסעים
    call = book.calls[0]
    assert call["task_type"] == "insurance"
    assert call["insurance"]["destination"] == "יוון"
    assert call["time"] == "" and call["party_size"] == 2
    assert call["page_url"] == INSURANCE_URL


def test_insurance_quote_without_card_asks_to_proceed(monkeypatch):
    """recon שעצר על הצעת המחיר בלי כרטיס: state=pending, בלי alt_time, שאלת המשך."""
    _reset()
    res = ActionResult(
        success=True,
        summary="SUMMARY_REACHED",
        details={
            "card_required": False,
            "extra": "פרמיה $88 לכל הנסיעה",
            "perk": "ביטול נסיעה כלול",
            "session_id": None,
        },
    )
    sent, _ = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", dict(_FIELDS)))
    msg = sent[-1]
    assert "פרמיה $88 לכל הנסיעה" in msg
    assert "ביטול נסיעה כלול" in msg
    assert "תשלום" in msg or "סגירה" in msg  # שאלת ההמשך
    assert not character_leaks(msg)
    assert pipeline._booking["p1"]["state"] == "pending"
    assert "alt_time" not in pipeline._booking["p1"]
    gate = pipeline._pending_commit["p1"]
    assert gate["task_type"] == "insurance"
    assert gate["insurance"]["travelers"] == ["15.05.1990", "20.11.1992"]
    assert gate["party_size"] == 2


def test_run_commit_passes_insurance_through(monkeypatch):
    """'מאשר' על הצעת ביטוח: run_commit מעביר task_type/insurance/form_answers הלאה."""
    _reset()
    calls = []

    async def fake_book(**kwargs):
        calls.append(kwargs)
        return ActionResult(
            success=False,
            summary="CARD_REQUIRED",
            details={"card_required": True, "session_id": None, "page_now": ""},
        )

    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    pipeline._pending_commit["p1"] = {
        "restaurant": "ביטוח נסיעות ליוון",
        "page_url": INSURANCE_URL,
        "platform": "passportcard",
        "date": "03.08",
        "time": "",
        "party_size": 2,
        "name": "אלון",
        "email": "a@b.com",
        "task_type": "insurance",
        "insurance": dict(_INS),
        "form_answers": {"id_number": "123456782"},
        "session_id": None,
    }
    asyncio.run(pipeline.run_commit("p1"))
    call = calls[0]
    assert call["task_type"] == "insurance"
    assert call["insurance"]["destination"] == "יוון"
    assert call["form_answers"] == {"id_number": "123456782"}
    assert call["dry_run"] is False
    assert pipeline._booking["p1"]["state"] == "card"  # קיר-כרטיס → Live View/לינק


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
