"""פרוטוקול MISSING מרובה-שדות: פרסור הדיווח (FIELD / OPTIONS ממופתח / שורת MISSING
עם |), תאימות לאחור מלאה למסלול השדה-הבודד, הודעת האיסוף המרוכז (_multi_ask),
מיזוג answers דטרמיניסטי ב-handle_inbound, והישרדות _save_flow/_restore_flow."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation.bu_runner import _parse_result  # noqa: E402
from app.db import memory  # noqa: E402
from app.llm.intent import character_leaks  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

# שורת הרגרסיה: דיווח העצירה המלא מהדוגמה שבמסמך העיצוב (סעיף 1.1).
REPORT = """מילאתי: יעד אירופה, יציאה 03.08, חזרה 17.08, 2 נוסעים, הצהרת בריאות שלילית.
בדף פרטי הנוסעים יש שדות חובה שאין לי — עצרתי בלי למלא:
FIELD id_number: מספר תעודת זהות של הנוסע הראשי
FIELD passenger2_first_name: שם פרטי של הנוסע השני
FIELD pickup_point: נקודת איסוף הכרטיס
OPTIONS pickup_point: נתב"ג טרמינל 3 | נתב"ג טרמינל 1 | צומת ספרים
MISSING:id_number|passenger2_first_name|pickup_point"""


def test_multi_missing_report_parses_fields_labels_and_options():
    r = _parse_result(REPORT, commit=False)
    assert r["success"] is False
    assert r["missing"] == "id_number"  # צרכני שדה-בודד רואים את הראשון
    assert r["missing_fields"] == ["id_number", "passenger2_first_name", "pickup_point"]
    assert r["options_by_field"]["pickup_point"] == [
        'נתב"ג טרמינל 3',
        'נתב"ג טרמינל 1',
        "צומת ספרים",
    ]
    assert r["field_labels"]["id_number"] == "מספר תעודת זהות של הנוסע הראשי"
    assert r["field_labels"]["passenger2_first_name"] == "שם פרטי של הנוסע השני"
    assert r["field_labels"]["pickup_point"] == "נקודת איסוף הכרטיס"
    assert r["options"] == []  # אין שורת OPTIONS ישנה — המסלול הישן לא מופעל


def test_single_missing_behaves_exactly_like_today():
    """תאימות לאחור: MISSING בודד + OPTIONS ישן (בלי מפתח) — בית-בבית כמו היום."""
    r = _parse_result("שדה המייל חובה וריק. MISSING:email", commit=False)
    assert r["missing"] == "email"
    assert r["missing_fields"] == ["email"]
    assert r["options"] == [] and r["options_by_field"] == {}
    legacy = "האתר דורש אזור ישיבה.\nOPTIONS: בפנים | בר גבוה | מרפסת מעשנים\nMISSING:seating_area"
    r = _parse_result(legacy, commit=False)
    assert r["missing"] == "seating_area"
    assert r["options"] == ["בפנים", "בר גבוה", "מרפסת מעשנים"]


def test_field_and_options_glued_on_one_line_are_split():
    """נצפה חי (ביטוח, ריצה חיה 2): ה-agent הדביק FIELD ו-OPTIONS באותה שורה עם '·' —
    בלי ההפרדה options_by_field חזר ריק והתווית נשאבה עם כל טקסט האופציות."""
    final = "FIELD p1_gender: מגדר (נוסע 1) · OPTIONS p1_gender: זכר|נקבה\nMISSING:p1_gender"
    r = _parse_result(final, commit=False)
    assert r["field_labels"]["p1_gender"] == "מגדר (נוסע 1)"
    assert r["options_by_field"]["p1_gender"] == ["זכר", "נקבה"]


def test_options_cap_keeps_all_eleven_live_destinations():
    """דף היעד החי הציג 11 מדינות ו-cap 10 חתך את גרמניה (ריצה חיה 1) — cap 15 שומר את כולן."""
    opts = " | ".join(f"מדינה{i}" for i in range(1, 12))
    r = _parse_result(f"OPTIONS destination: {opts}\nMISSING:destination", commit=False)
    assert len(r["options_by_field"]["destination"]) == 11
    assert r["options_by_field"]["destination"][-1] == "מדינה11"


def test_keyed_options_on_single_field_bridge_to_legacy_options():
    """agent שהשתמש בצורה הממופתחת על שדה בודד — המסלול הישן (רשימת טאפ) עדיין עובד."""
    final = "OPTIONS seating_area: בפנים | בחוץ\nMISSING:seating_area"
    r = _parse_result(final, commit=False)
    assert r["missing_fields"] == ["seating_area"]
    assert r["options"] == ["בפנים", "בחוץ"]


def test_summary_extra_payload_and_marker_mix_is_cut():
    """הפרמיה אחרי | נתפסת ב-extra; markers שהודבקו אחרי ה-payload נחתכים."""
    ok = "מולא הכל.\nSUMMARY_REACHED | פרמיה $127.40 לכל הנסיעה · אירופה 03.08-17.08 · 2 נוסעים"
    r = _parse_result(ok, commit=False)
    assert r["success"] is True
    assert r["extra"] == "פרמיה $127.40 לכל הנסיעה · אירופה 03.08-17.08 · 2 נוסעים"
    assert r["time"] == ""  # אין נקודתיים בפרמיה — רגקס השעה לא נדלק
    mixed = _parse_result("SUMMARY_REACHED | פרמיה $127 MISSING:x", commit=False)
    assert mixed["extra"] == "פרמיה $127"
    assert mixed["missing"] == "x" and mixed["success"] is False
    # שורת MISSING מרובה מכילה | משלה — לא הופכת ל-extra
    assert _parse_result(REPORT, commit=False)["extra"] == ""


def test_multi_ask_carries_all_labels_and_options_in_character():
    labels = {
        "id_number": "מספר תעודת זהות",
        "pickup_point": "נקודת איסוף הכרטיס",
    }
    opts = {"pickup_point": ['נתב"ג טרמינל 3', "צומת ספרים"]}
    msg = asyncio.run(pipeline._multi_ask(labels, opts))
    assert "מספר תעודת זהות" in msg
    assert "נקודת איסוף הכרטיס" in msg
    assert 'נתב"ג טרמינל 3' in msg and "צומת ספרים" in msg
    assert not character_leaks(msg)
    assert "שנייה" not in msg


def test_multi_ask_free_voice_keeps_items_verbatim(monkeypatch):
    """QA ביטוח 18.7 (#5): _multi_ask עבר לקול החופשי — פלט מודל תקין עם הרשימה
    מילה-במילה מתקבל; פלט שמשכתב את הרשימה נפסל (must_ctx) ונופל לנוסח הקיים."""
    labels = {"id_number": "מספר תעודת זהות", "pickup_point": "נקודת איסוף הכרטיס"}
    opts = {"pickup_point": ["צומת ספרים"]}
    items = "· מספר תעודת זהות\n· נקודת איסוף הכרטיס — צומת ספרים"

    async def good_model(intent, ctx):
        assert intent == "multi_ask" and ctx["items"] == items
        return f"עצרתי רגע על הטופס — צריך ממך:\n{items}\nהכל בהודעה אחת ואני ממשיך"

    monkeypatch.setattr(pipeline, "_say_model", good_model)
    msg = asyncio.run(pipeline._multi_ask(labels, opts))
    assert items in msg and msg.startswith("עצרתי רגע על הטופס")

    async def bad_model(intent, ctx):
        return 'חסרים לי ת"ז ונקודת איסוף, שלח בבקשה'  # שכתב את הרשימה — נפסל

    monkeypatch.setattr(pipeline, "_say_model", bad_model)
    msg = asyncio.run(pipeline._multi_ask(labels, opts))
    assert items in msg  # ה-fallback הדטרמיניסטי מחזיק את הרשימה כלשונה


def test_human_field_prefers_known_then_page_label_then_key():
    assert pipeline._human_field("id_number", {}) == "מספר תעודת זהות"
    assert pipeline._human_field("visa_type", {"visa_type": "סוג ויזה"}) == "סוג ויזה"
    assert pipeline._human_field("mystery_key", {}) == "mystery_key"


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
    "destination": "אירופה",
    "date": "03.08",
    "return_date": "17.08",
    "travelers_birth_dates": ["15.05.1990", "20.11.1992"],
    "health_issues": "אין",
}


def _pend(missing=("id_number", "pickup_point")):
    labels = {k: pipeline._human_field(k, {}) for k in missing}
    return {
        "fields": dict(_FIELDS),
        "missing_fields": list(missing),
        "answered": {},
        "labels": labels,
        "options": [],
    }


def _wire(monkeypatch):
    sent, booked = [], []

    async def fake_converse(phone, text):
        return fake_converse.result

    async def fake_run_booking(phone, fields):
        booked.append(fields)

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_typing(message_id):
        pass

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "run_booking", fake_run_booking)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    return fake_converse, sent, booked


async def _drain():
    for _ in range(3):
        await asyncio.sleep(0)
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)


def test_partial_answers_update_remaining_without_firing(monkeypatch):
    """ענה רק על חלק → remaining מתעדכן (ה-truth_note הבא יבקש רק את החסר), לא יורים."""
    _reset()
    conv, sent, booked = _wire(monkeypatch)
    pipeline._booking["p1"] = {
        "state": "missing",
        "info": "x",
        "remaining": ["id_number", "pickup_point"],
        "labels": _pend()["labels"],
    }
    pipeline._await_answer["p1"] = _pend()
    conv.result = {
        "reply": "קיבלתי, ומה עם נקודת האיסוף?",
        "ready": False,
        "answers": ["id_number: 123456782"],
    }

    asyncio.run(pipeline.handle_inbound("p1", 'הת"ז שלי 123456782'))

    assert not booked  # לא נורה — עוד חסר pickup_point
    assert pipeline._booking["p1"]["remaining"] == ["pickup_point"]
    assert pipeline._await_answer["p1"]["answered"] == {"id_number": "123456782"}
    assert sent  # ה-reply של הפרסונה כן נשלח


def test_full_answers_fire_run_booking_with_form_answers(monkeypatch):
    """כל המפתחות נענו (גם על פני שני תורים) → ירי דטרמיניסטי עם form_answers."""
    _reset()
    conv, sent, booked = _wire(monkeypatch)
    pend = _pend()
    pend["answered"] = {"id_number": "123456782"}  # התור הקודם כבר ענה על אחד
    pipeline._booking["p1"] = {
        "state": "missing",
        "info": "x",
        "remaining": ["pickup_point"],
        "labels": pend["labels"],
    }
    pipeline._await_answer["p1"] = pend
    conv.result = {"reply": "מעולה", "ready": False, "answers": ['pickup_point: נתב"ג טרמינל 3']}

    async def go():
        await pipeline.handle_inbound("p1", "טרמינל 3")
        await _drain()

    asyncio.run(go())
    assert booked and booked[0]["form_answers"] == {
        "id_number": "123456782",
        "pickup_point": 'נתב"ג טרמינל 3',
    }
    assert booked[0]["destination"] == "אירופה"
    assert "p1" not in pipeline._await_answer
    assert pipeline._booking["p1"]["state"] == "working"
    # ה-ack המכני נשלח (מחליף את ה-reply של הפרסונה) ובדמות
    assert sent and not character_leaks(sent[-1])


def test_unknown_or_empty_answers_are_ignored(monkeypatch):
    """המודל לא ממציא מפתחות: מפתח שלא ברשימה או ערך ריק לא נכנסים ל-answered."""
    _reset()
    conv, sent, booked = _wire(monkeypatch)
    pipeline._booking["p1"] = {
        "state": "missing",
        "info": "x",
        "remaining": ["id_number", "pickup_point"],
        "labels": _pend()["labels"],
    }
    pipeline._await_answer["p1"] = _pend()
    conv.result = {
        "reply": "רגע",
        "ready": False,
        "answers": ["made_up_key: ערך", "id_number:", "בלי מפתח בכלל"],
    }
    asyncio.run(pipeline.handle_inbound("p1", "בלה"))
    assert not booked
    assert pipeline._await_answer["p1"]["answered"] == {}


def test_multi_await_answer_survives_save_and_restore(monkeypatch):
    """המבנה המרובה (מילונים/רשימות) עובר JSON ב-_save_flow וחוזר ב-_restore_flow."""
    _reset()
    saved = []

    async def fake_get_profile(phone):
        return None

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        saved.append(prefs)

    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    pend = _pend()
    pend["answered"] = {"id_number": "123456782"}
    pipeline._booking["p1"] = {
        "state": "missing",
        "info": "x",
        "remaining": ["pickup_point"],
        "labels": pend["labels"],
    }
    pipeline._await_answer["p1"] = pend

    asyncio.run(pipeline._save_flow("p1"))
    flow = json.loads(json.dumps(saved[0]["_flow"]))  # round-trip כמו Supabase
    assert flow["ts"] > 0

    _reset()
    pipeline._restore_flow("p1", flow)
    restored = pipeline._await_answer["p1"]
    assert restored["missing_fields"] == ["id_number", "pickup_point"]
    assert restored["answered"] == {"id_number": "123456782"}
    assert pipeline._booking["p1"]["remaining"] == ["pickup_point"]


def test_run_booking_multi_missing_sends_one_message_with_all_items(monkeypatch):
    """עצירת MISSING מרובה מה-agent → הודעה מרוכזת אחת + הקשר answers, בלי רשימת-טאפ."""
    _reset()
    sent, listed = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, labels):
        listed.append(labels)

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING",
            details={
                "missing": "id_number",
                "missing_fields": ["id_number", "pickup_point"],
                "field_labels": {"pickup_point": "נקודת איסוף הכרטיס"},
                "options_by_field": {"pickup_point": ['נתב"ג טרמינל 3', "צומת ספרים"]},
                "options": [],
                "session_id": "s77",
                "stage": "עצרתי בדף הנוסעים",
            },
        )

    async def fake_get_profile(phone):
        return None

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    asyncio.run(pipeline.run_booking("p1", dict(_FIELDS)))

    assert not listed  # בלי רשימת-טאפ — הודעה אחת עם כל הפריטים
    msg = sent[-1]
    assert "מספר תעודת זהות" in msg and "נקודת איסוף הכרטיס" in msg
    assert 'נתב"ג טרמינל 3' in msg
    assert not character_leaks(msg)
    pend = pipeline._await_answer["p1"]
    assert pend["missing_fields"] == ["id_number", "pickup_point"]
    assert pend["options"] == []  # המסלול הדטרמיניסטי הישן מדלג
    assert pipeline._booking["p1"]["remaining"] == ["id_number", "pickup_point"]
    assert pipeline._resume["p1"]["session_id"] == "s77"  # pause-resume נשמר


def test_single_missing_via_run_booking_unchanged(monkeypatch):
    """שדה בודד (מסעדות) — המסלול הקיים בדיוק: options נשמרות, שאלה יחידה."""
    _reset()
    sent, listed = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, labels):
        listed.append(labels)

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING",
            details={
                "missing": "seating_area",
                "missing_fields": ["seating_area"],
                "options": ["בפנים", "מרפסת מעשנים"],
            },
        )

    async def fake_get_profile(phone):
        return None

    async def fake_noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(pipeline, "_persist_chat", fake_noop)
    monkeypatch.setattr(pipeline, "_save_flow", fake_noop)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    pipeline._resolved["p1"] = {"name": "הדסון", "url": "http://x", "platform": "ontopo"}

    fields = {"restaurant": "הדסון", "date": "מחר", "time": "20:00", "party_size": 2}
    asyncio.run(pipeline.run_booking("p1", fields))

    assert listed == [["בפנים", "מרפסת מעשנים"]]  # רשימת הטאפ הישנה
    pend = pipeline._await_answer["p1"]
    assert pend["field"] == "seating_area" and pend["options"] == ["בפנים", "מרפסת מעשנים"]
    assert "remaining" not in pipeline._booking["p1"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
