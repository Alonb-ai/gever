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
    # סבב 3: "אין" מכסה ארבע קטגוריות כולל הריון — שאלת ההריון (עצירת סבב 2) נענית כדין
    assert "ארבע הקטגוריות" in task and "אף נוסעת אינה בהריון" in task
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


def test_insurance_task_dates_carry_full_year_and_cross_year():
    """QA ביטוח 18.7 (#6): הצינור מעביר "03.08" בלי שנה — ה-task מקבל תאריך מלא
    DD.MM.YYYY שהושלם מההקשר, ונסיעה חוצת-שנה מקבלת שנת חזרה נכונה."""
    import datetime
    import re

    from app.automation.bu_runner import _full_date

    task = _build_task({**_JOB, "dry_run": True})
    assert re.search(r"יציאה 03\.08\.20\d\d\b", task)
    assert re.search(r"חזרה 17\.08\.20\d\d\b", task)
    # דטרמיניסטי עם floor מפורש: תאריך עתידי השנה נשאר; תאריך שעבר → שנה הבאה
    floor = datetime.date(2026, 7, 19)
    assert _full_date("01.09", floor) == "01.09.2026"
    assert _full_date("01.03", floor) == "01.03.2027"
    # חוצת-שנה: חזרה 03.01 אחרי יציאה 28.12 גולשת לשנה הבאה
    dep = _full_date("28.12", floor)
    ret = _full_date("03.01", datetime.datetime.strptime(dep, "%d.%m.%Y").date())
    assert int(ret[-4:]) == int(dep[-4:]) + 1
    # עם שנה מפורשת / לא-פריק / ריק — לא נוגעים
    assert _full_date("17.08.2027") == "17.08.2027"
    assert _full_date("31.02", floor) == "31.02"
    assert _full_date("") == ""


def test_insurance_task_requires_traveler_tag_in_field_labels():
    """QA ביטוח 18.7 (#3): FIELD של שדה פר-נוסע חייב תיוג "(נוסע N)" בתווית —
    בלעדיו הלקוח לא יודע על מי מהנוסעים השאלה."""
    task = _build_task({**_JOB, "dry_run": True})
    flat = " ".join(task.split())
    assert 'תיוג "(נוסע N)"' in flat
    assert "FIELD p2_gender: מגדר (נוסע 2)" in flat


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


def test_insurance_task_traveler_rules_from_aig_recon():
    """Recon AIG 18.7: הריצה עצרה עם MISSING על תאריך לידה שנמסר, וההמשך הגיש
    SUMMARY_REACHED על נוסע אחד מתוך שניים — שני חוקי-הנוסעים חייבים להיות ב-task."""
    task = _build_task({**_JOB, "dry_run": True})
    assert 'לעולם אינו שדה "חסר"' in task
    assert "לכסות את כל 2 הנוסעים" in task
    assert "אל תדווח עליו SUMMARY_REACHED" in task
    # בלי רשימת נוסעים אין את החוקים — "כל 0 הנוסעים" היה הנחיה הפוכה
    bare = _build_task({**_JOB, "dry_run": True, "insurance": {**_INS, "travelers": []}})
    assert "כל 0 הנוסעים" not in bare
    assert 'לעולם אינו שדה "חסר"' not in bare


def test_insurance_resume_carries_travelers_birth_dates():
    """Recon AIG 18.7: ה-resume נשא רק recap+תשובות, וה-agent שלא ראה את תאריכי
    הלידה עצר עם MISSING:p1_birth_date על ערך שהלקוח כבר מסר — סבב שאלה מיותר.
    ה-resume חייב לשאת את רשימת הנוסעים מהבקשה המקורית."""
    job = {
        **_JOB,
        "dry_run": True,
        "resume": {"recap": 'עצרתי על ת"ז'},
        "form_answers": {"id_number": "389784208"},
    }
    task = _build_task(job)
    assert "הנוסעים מהבקשה המקורית" in task
    assert "15.05.1990" in task and "20.11.1992" in task


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


def test_restaurant_job_keeps_own_step_ceiling(monkeypatch):
    """עודכן במיזוג: מסעדה ירדה ל-25 צעדים (זירוז 17.7) — העוגן: לא 80 של הביטוח."""
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
    assert jobs[0]["max_steps"] == 25 and jobs[0]["task_type"] == "restaurant"


def test_failure_reply_insurance_reasons_anchor_9912():
    """עודכן במיזוג: _failure_reply נהיה async (קול חופשי דרך _say) — העוגנים בעינם."""
    for reason in ("manual_underwriting", "phone_only", "blocked"):
        hit = asyncio.run(
            pipeline._failure_reply(reason, "ביטוח נסיעות ליוון", task_type="insurance")
        )
        assert hit is not None, reason
        info, msg = hit
        assert "*9912" in msg
        assert not character_leaks(msg)
        # הסיבות האלה לא קיימות למסעדות — שם נשארת ההודעה הגנרית
        assert asyncio.run(pipeline._failure_reply(reason, "הדסון")) is None
    # info של חיתום נכנס ל-truth_note כטקסט קבוע שלנו
    info, _msg = asyncio.run(
        pipeline._failure_reply("manual_underwriting", "x", task_type="insurance")
    )
    assert "חיתום" in info


def test_persona_offers_travel_insurance_as_active_capability():
    """סבב 4 (חיווט pipeline): הפער שמנע הפעלה מוואטסאפ — הפרסונה הציבה 'ביטוח'
    ברשימת ה'עוד לא', אז מודל השיחה סירב ולעולם לא ירה ready=true למרות שכל
    המכניקה קיימת. ביטוח נסיעות חייב להיות ב'סוגר היום בפועל', עם קו ה-PCI
    (התשלום תמיד של הלקוח), ומחוץ לרשימת ה'עוד לא'."""
    from app.llm.intent import SYSTEM_PROMPT

    active = SYSTEM_PROMPT.split("מה שאתה כבר סוגר היום בפועל")[1].split("דברים אחרים")[0]
    assert "ביטוח נסיעות" in active
    assert "הצעת המחיר" in active and "תשלום" in active  # עד ההצעה; התשלום של הלקוח
    not_yet = SYSTEM_PROMPT.split("דברים אחרים")[1].split("לעולם לא לוקח")[0]
    assert "ביטוח" not in not_yet


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
    # סבב 3: השאלה המרוכזת בשיחה מכסה גם הריון (לקח ריצה חיה 2 — הטופס שואל כל נוסעת)
    assert "בהריון" in pipeline._EXTRACT
    # סבב 4 (לקח ריצה חיה דרך המסלול המחווט): בלי required ה-decoding המוגבל השמיט
    # בשיטתיות את שדות הביטוח (ready=true עם "0 נוסעים") — required מכריח פליטה.
    for key in (
        "task_type",
        "destination",
        "return_date",
        "travelers_birth_dates",
        "health_issues",
        "addons",
    ):
        assert key in pipeline._SCHEMA["required"], key


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
    pipeline._ins_draft.clear()


def test_insurance_draft_accumulates_across_turns():
    """סבב 4, ריצה חיה 1 דרך המסלול המחווט: ה-extract הפיל בתור ה-ready את
    travelers/return_date שנמסרו תור קודם — הריצה יצאה עם '0 נוסעים' ונעצרה על
    MISSING מיותר. הצבירה דטרמיניסטית: כל תור ביטוח מעדכן טיוטה per-phone,
    ו-ready יוצא ממוזג ממנה (הערך הטרי מנצח)."""
    _reset()
    pipeline._merge_insurance(
        "p1",
        {
            "task_type": "insurance",
            "ready": False,
            "destination": "יוון",
            "date": "03.08",
            "return_date": "17.08",
            "travelers_birth_dates": ["15.05.1990", "20.11.1992"],
        },
    )
    merged = pipeline._merge_insurance(
        "p1",
        {"task_type": "insurance", "ready": True, "destination": "יוון", "health_issues": "אין"},
    )
    assert merged["travelers_birth_dates"] == ["15.05.1990", "20.11.1992"]
    assert merged["return_date"] == "17.08" and merged["date"] == "03.08"
    assert merged["health_issues"] == "אין" and merged["ready"] is True


def test_insurance_draft_fresh_value_wins_and_stale_draft_expires():
    _reset()
    pipeline._merge_insurance(
        "p1",
        {
            "task_type": "insurance",
            "destination": "יוון",
            "travelers_birth_dates": ["15.05.1990"],
        },
    )
    merged = pipeline._merge_insurance("p1", {"task_type": "insurance", "destination": "ספרד"})
    assert merged["destination"] == "ספרד"  # הערך הטרי מנצח
    assert merged["travelers_birth_dates"] == ["15.05.1990"]  # השאר נשמר
    # טיוטה בת >3 שעות נזרקת — הצהרת בריאות/נוסעים ישנים לא זולגים לנסיעה חדשה
    pipeline._ins_draft["p1"]["ts"] -= pipeline.SESSION_GAP_S + 1
    merged = pipeline._merge_insurance("p1", {"task_type": "insurance", "destination": "קפריסין"})
    assert merged["destination"] == "קפריסין"
    assert "travelers_birth_dates" not in merged


def test_insurance_draft_cleared_on_other_task_kept_without_task_type():
    _reset()
    pipeline._merge_insurance("p1", {"task_type": "insurance", "destination": "יוון"})
    # תור בלי task_type (למשל תשובת answers באמצע missing) — לא נוגעים בטיוטה
    out = pipeline._merge_insurance("p1", {"reply": "רגע", "answers": ["id_number: 1"]})
    assert out == {"reply": "רגע", "answers": ["id_number: 1"]}
    assert "p1" in pipeline._ins_draft
    # מעבר מפורש לנושא אחר — הטיוטה נמחקת (לא תזלוג לבקשת ביטוח עתידית)
    pipeline._merge_insurance("p1", {"task_type": "restaurant", "restaurant": "הדסון"})
    assert "p1" not in pipeline._ins_draft


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


def test_addons_none_normalized_to_empty(monkeypatch):
    """סבב 4: 'בלי הרחבות' חוזר מה-extract כ'אין' (required מכריח פליטה) — ה-payload
    מנרמל לריק כדי שה-task יקבל 'שום הרחבה', לא הרחבה בשם 'אין'."""
    _reset()
    res = ActionResult(success=False, summary="FAILED:blocked", details={"failed": "blocked"})
    _, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", {**_FIELDS, "addons": "אין"}))
    assert book.calls[0]["insurance"]["addons"] == ""
    # הרחבה אמיתית עוברת כמו שהיא
    _reset()
    _, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", {**_FIELDS, "addons": "סקי"}))
    assert book.calls[0]["insurance"]["addons"] == "סקי"


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


# --- קבוצת המבטחים הסגורה (insurance-multi): 5 מבטחים, פספורטכארד = ברירת המחדל ---


def test_insurance_companies_closed_group_contract():
    """עקרון ה-resolver: קבוצה סגורה כמו רשתות הקולנוע. פספורטכארד ראשונה
    (ברירת המחדל ההיסטורית); bu_runner מחזיק עותק שמות מקומי (איסור ייבוא
    resolve משם) — חוזה: זהה אחד-לאחד למפה."""
    from app.automation.bu_runner import _INSURER_HE
    from app.automation.resolve import INSURANCE_COMPANIES

    keys = list(INSURANCE_COMPANIES)
    assert keys[0] == "passportcard" and len(keys) == 5
    assert {"harel", "phoenix", "aig", "migdal"} <= set(keys)
    urls = [u for _he, u in INSURANCE_COMPANIES.values()]
    assert len(set(urls)) == 5 and all(u.startswith("https://") for u in urls)
    assert _INSURER_HE == {k: he for k, (he, _u) in INSURANCE_COMPANIES.items()}


def test_resolve_insurance_company_steering():
    from app.automation.resolve import INSURANCE_COMPANIES

    found = asyncio.run(resolve_insurance_url("harel"))
    assert found["status"] == "one" and found["platform"] == "harel"
    assert found["url"] == INSURANCE_COMPANIES["harel"][1]
    # לא נקב (None/ריק) → פספורטכארד — בדיוק ההתנהגות שלפני ההרחבה
    for c in (None, "", "  "):
        f = asyncio.run(resolve_insurance_url(c))
        assert f["platform"] == "passportcard" and f["url"] == INSURANCE_URL
    # מפתח לא מוכר → many עם כל הקבוצה — לעולם לא בוחרים מבטח אחר בשקט
    f = asyncio.run(resolve_insurance_url("clal"))
    assert f["status"] == "many" and len(f["candidates"]) == 5 and f["url"] is None


def test_insurance_task_carries_company_name_and_generic_dest_rule():
    from app.automation.resolve import INSURANCE_COMPANIES

    harel_url = INSURANCE_COMPANIES["harel"][1]
    task = _build_task({**_JOB, "url": harel_url, "platform": "harel", "dry_run": True})
    assert "הראל" in task and harel_url in task
    assert "פספורטכארד" not in task
    # חוק היעד הפספורטכארד-ספציפי (חיפוש מדינות) לא זולג; עצירת היעד נשארת
    assert "שדה החיפוש" not in task
    assert "MISSING:destination" in task and "OPTIONS destination:" in task
    # ופספורטכארד (job בלי platform = ברירת מחדל) — הנוסח המוכח-חי בעינו
    task_pc = _build_task({**_JOB, "dry_run": True})
    assert "פספורטכארד" in task_pc and "שדה החיפוש" in task_pc


def test_schema_company_enum_and_not_required():
    from app.automation.resolve import INSURANCE_COMPANIES

    props = pipeline._SCHEMA["properties"]
    assert props["company"]["enum"] == list(INSURANCE_COMPANIES)
    # לא-קריטי (יש ברירת מחדל) ⇒ לא ב-required; לקח ה-decoding של flash מחייב
    # גארד — הוא יושב ב-run_booking (ערך זר/חסר → פספורטכארד)
    assert "company" not in pipeline._SCHEMA["required"]
    assert "company" in pipeline._EXTRACT and "harel" in pipeline._EXTRACT


def test_insurance_draft_keeps_company_across_turns():
    _reset()
    pipeline._merge_insurance("p1", {"task_type": "insurance", "company": "harel"})
    merged = pipeline._merge_insurance("p1", {"task_type": "insurance", "destination": "יוון"})
    assert merged["company"] == "harel"


def test_run_booking_routes_named_company(monkeypatch):
    from app.automation.resolve import INSURANCE_COMPANIES

    _reset()
    res = ActionResult(success=False, summary="FAILED:blocked", details={"failed": "blocked"})
    sent, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", {**_FIELDS, "company": "harel"}))
    assert book.calls[0]["page_url"] == INSURANCE_COMPANIES["harel"][1]
    assert book.calls[0]["platform"] == "harel"
    # הודעת הכשל נושאת את המבטח הנכון, בלי מספר מוקד שלא שלו
    assert "הראל" in sent[-1] and "*9912" not in sent[-1]


def test_run_booking_default_and_foreign_company_fall_back(monkeypatch):
    _reset()
    res = ActionResult(success=False, summary="FAILED:blocked", details={"failed": "blocked"})
    _, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", dict(_FIELDS)))
    assert book.calls[0]["page_url"] == INSURANCE_URL
    assert book.calls[0]["platform"] == "passportcard"
    # ערך זר מהמודל מתאפס לברירת המחדל — אותה הגנה כמו chain בקולנוע
    _reset()
    _, book = _wire_booking(monkeypatch, book_result=res)
    asyncio.run(pipeline.run_booking("p1", {**_FIELDS, "company": "כלל"}))
    assert book.calls[0]["platform"] == "passportcard"


def test_health_guard_generic_for_non_passportcard(monkeypatch):
    _reset()
    sent, _ = _wire_booking(monkeypatch, book_result=None)
    fields = {**_FIELDS, "company": "harel", "health_issues": "נוטל תרופות קבועות"}
    asyncio.run(pipeline.run_booking("p1", fields))
    assert pipeline._booking["p1"]["state"] == "failed"
    # שם המבטח הנכון; *9912 הוא מוקד פספורטכארד — לא ממציאים אותו להראל
    assert "הראל" in sent[-1] and "*9912" not in sent[-1]
    assert not character_leaks(sent[-1])


def test_age_85_guard_only_for_passportcard(monkeypatch):
    """תקרת גיל 85 היא עובדה פספורטכארד-ספציפית — מבטח אחר לא נעצר מראש;
    האתר יכריע (עצירה כנה עם FAILED:manual_underwriting אם יש תקרה)."""
    _reset()
    res = ActionResult(success=False, summary="FAILED:blocked", details={"failed": "blocked"})
    _, book = _wire_booking(monkeypatch, book_result=res)
    fields = {**_FIELDS, "company": "aig", "travelers_birth_dates": ["15.05.1990", "01.01.1935"]}
    asyncio.run(pipeline.run_booking("p1", fields))
    assert book.calls  # הריצה יצאה לדרך — לא נעצרה בגארד


def test_failure_reply_carries_named_company_without_9912():
    for reason in ("manual_underwriting", "phone_only", "blocked"):
        hit = asyncio.run(
            pipeline._failure_reply(
                reason, "ביטוח נסיעות ליוון", task_type="insurance", company_he="מגדל"
            )
        )
        assert hit is not None, reason
        assert "*9912" not in hit[1], reason
        assert not character_leaks(hit[1])


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
