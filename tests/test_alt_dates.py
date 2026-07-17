"""זמינות-תחילה (ממצאי בטא #1+#7): במועד המבוקש אין כלום → הסוכן אוסף מהדף את
הימים שכן זמינים (MISSING:date + OPTIONS), גבר מדווח מה כן יש ומציע לסגור שם,
והחלופות נשמרות ב-_await_answer כך שגם פולו-אפ ("אז מתי כן?") נענה בלי ריצה חדשה."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import bu_runner  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def test_restaurant_task_offers_dates_instead_of_failing():
    """שני נוסחי חוק-השעה (רגיל וגמיש) מנחים: אין כלום ביום → MISSING:date + OPTIONS."""
    for extra in ({}, {"time_flex": True}):
        task = bu_runner._build_task(
            {"url": "http://x", "date": "מחר", "time": "20:00", "party_size": 2, **extra}
        )
        assert "MISSING:date" in task
        assert "FAILED:no_availability" in task  # נשאר רק כשגם בימים סמוכים אין


def test_cinema_task_offers_dates_and_times_instead_of_failing():
    """ה-builder הקולנועי: אין הקרנה בתאריך → MISSING:date עם התאריכים שכן קיימים;
    אין בטווח השעה → MISSING:time עם שעות אותו היום; כישלון יבש רק כשאין כלום."""
    task = bu_runner._build_cinema_task(
        {
            "url": "http://x",
            "movie": "האודיסאה",
            "city": "תל אביב",
            "date": "18.07",
            "time": "20:00",
            "party_size": 2,
        }
    )
    assert "MISSING:date" in task
    assert task.count("OPTIONS:") >= 3  # תאריכים, שעות, ובחירות כפויות (פורמט)
    assert "FAILED:no_availability" in task


def test_parse_missing_date_with_options():
    """החוזה עם ה-runner: MISSING:date + שורת OPTIONS של תאריכים מפורסרים כרגיל."""
    r = bu_runner._parse_result(
        "אין הקרנות בתאריך המבוקש\nOPTIONS: 21.07 | 22.07 | 28.07\nMISSING:date",
        commit=False,
    )
    assert r["missing"] == "date"
    assert r["options"] == ["21.07", "22.07", "28.07"]
    assert not r["success"]


def _run_missing_date(monkeypatch, options, fields=None):
    pipeline._booking.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._preresolve.clear()
    pipeline._await_answer.clear()
    pipeline._last_out.clear()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(("text", msg))

    async def fake_send_list(phone, body, labels):
        sent.append(("list", body, tuple(labels)))

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:date",
            details={"missing": "date", "options": options, "session_id": "s-d", "stage": "x"},
        )

    async def fake_get_profile(phone):
        return None

    async def fake_persist(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_persist)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    # notes עם רמז ישיבה: לא חומשת שאלת-ביניים מקבילה שמתחרה על סדר ההודעות בטסט
    fields = fields or {"restaurant": "הדסון", "date": "18.07", "time": "20:00", "notes": "בפנים"}
    name = fields.get("movie") or fields["restaurant"]
    pipeline._resolved["p1"] = {"name": name, "url": "http://x", "platform": ""}
    asyncio.run(pipeline.run_booking("p1", fields))
    return sent


def test_two_free_dates_become_tap_list(monkeypatch):
    """כמה ימים זמינים → רשימת טאפ; הכותרת נושאת את התאריך שנפל והצעת סגירה."""
    sent = _run_missing_date(monkeypatch, ["21.07", "28.07"])
    kind, body, labels = sent[-1]
    assert kind == "list" and labels == ("21.07", "28.07")
    assert "18.07" in body and ("סגור" in body or "סוגר" in body)
    # הסשן חי וממתין + החלופות שמורות לפולו-אפ — בלי ריצה חדשה
    assert pipeline._resume["p1"]["session_id"] == "s-d"
    assert pipeline._booking["p1"]["state"] == "missing"
    assert pipeline._await_answer["p1"]["options"] == ["21.07", "28.07"]


def test_single_free_date_offers_to_close(monkeypatch):
    """יום זמין אחד → שאלת סגירה ישירה עם המבוקש והחלופה מילה-במילה."""
    sent = _run_missing_date(monkeypatch, ["28.07"])
    kind, msg = sent[-1]
    assert kind == "text"
    assert "18.07" in msg and "28.07" in msg and ("סגור" in msg or "סוגר" in msg)


def test_cinema_missing_date_offers_list(monkeypatch):
    """אותו נתיב בקולנוע (ממצא בטא #1): הסוכן ראה 'עד 21.07 ואז 28.07' — גבר מציע."""
    sent = _run_missing_date(
        monkeypatch,
        ["21.07", "28.07"],
        fields={
            "task_type": "cinema",
            "movie": "האודיסאה",
            "city": "כפר סבא",
            "date": "23.07",
            "time": "20:00",
            "party_size": 2,
        },
    )
    kind, body, labels = sent[-1]
    assert kind == "list" and labels == ("21.07", "28.07")
    assert "23.07" in body


def test_matching_date_answer_relaunches_with_date(monkeypatch):
    """בחירת תאריך חלופי (טאפ/הקלדה) → ירייה דטרמיניסטית: התאריך נכנס לשדה עצמו."""
    pipeline._booking.clear()
    pipeline._await_answer.clear()
    pipeline._turns.clear()
    pipeline._last_out.clear()
    booked = []

    async def fake_converse(phone, text):
        raise AssertionError("converse לא אמור להיקרא בהתאמה דטרמיניסטית")

    async def fake_run_booking(phone, fields):
        booked.append(fields)

    async def fake_send_text(phone, msg):
        pass

    async def fake_typing(message_id):
        pass

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "run_booking", fake_run_booking)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    pipeline._booking["p1"] = {"state": "missing", "info": "date"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הדסון", "date": "18.07", "time": "20:00", "party_size": 2},
        "field": "date",
        "options": ["21.07", "28.07"],
    }

    async def go():
        await pipeline.handle_inbound("p1", "28.07")
        for _ in range(3):
            await asyncio.sleep(0)
            if pipeline._pending:
                await asyncio.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(go())
    assert booked[0]["date"] == "28.07"
    assert "p1" not in pipeline._await_answer


def test_truth_note_carries_alternatives():
    """פולו-אפ חופשי ("אז מתי כן?"): החלופות מוזרקות ל-truth_note — למודל יש את
    הרשימה האמיתית מהדף, בלי ריצה חדשה ובלי להמציא."""
    pipeline._booking["p9"] = {"state": "missing", "info": "date"}
    pipeline._await_answer["p9"] = {"fields": {}, "field": "date", "options": ["21.07", "28.07"]}
    note = pipeline._truth_note("p9")
    assert "21.07" in note and "28.07" in note
    assert "אל תמציא" in note
    pipeline._booking.pop("p9", None)
    pipeline._await_answer.pop("p9", None)


def test_truth_note_without_alternatives_unchanged():
    """עצירת MISSING בלי אופציות (מייל/שם) — הנוסח הקיים, בלי בלוק חלופות."""
    pipeline._booking["p9"] = {"state": "missing", "info": "email"}
    pipeline._await_answer.pop("p9", None)
    note = pipeline._truth_note("p9")
    assert "email" in note and "החלופות" not in note
    pipeline._booking.pop("p9", None)
