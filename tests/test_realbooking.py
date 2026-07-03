"""בדיקות ל-confirm→commit (realbooking): run_commit סוגר באמת רק עם שם, run_booking
מאכלס את ה-gate, וניתוב handle_inbound מכבד את dry_run ('מאשר' לא סוגר כשהדגל דלוק)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._reset_next.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()


def test_run_commit_books_for_real_and_logs(monkeypatch):
    """job עם שם → book_table(dry_run=False), state=done עם מספר אישור, log_booking, gate נופ."""
    _reset()
    sent, book_calls, log_calls = [], [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        return ActionResult(
            success=True,
            summary="ההזמנה בוצעה.",
            details={
                "confirmation": "ABC123",
                "restaurant": "הדסון",
                "date": "מחר",
                "time": "20:00",
            },
        )

    async def fake_log(phone, restaurant, date, time, party_size, status):
        log_calls.append({"status": status, "restaurant": restaurant, "party_size": party_size})

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["p1"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("p1"))

    assert book_calls and book_calls[0]["dry_run"] is False
    assert book_calls[0]["phone"] == "p1" and book_calls[0]["name"] == "אלון"
    assert pipeline._booking["p1"]["state"] == "done"
    assert pipeline._booking["p1"]["info"] == "ABC123"
    assert log_calls and log_calls[0]["status"] == "confirmed"
    assert "p1" not in pipeline._pending_commit  # ה-gate נוקה
    assert "p1" in pipeline._reset_next  # דף חדש בהודעה הבאה
    assert any("סגור ✅" in m for m in sent)  # הלקוח קיבל אישור סגירה
    assert any("ABC123" in m for m in sent)  # כולל מספר האישור


def test_run_commit_card_wall_hands_link(monkeypatch):
    """קיר כרטיס בסגירה: success=False + card_required → לא log_booking, מוסרים לינק (זרוע C)."""
    _reset()
    sent, log_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(success=False, summary="CARD_REQUIRED", details={"card_required": True})

    async def fake_log(*a, **k):
        log_calls.append(1)

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    pipeline._pending_commit["pc"] = {
        "restaurant": "הדסון",
        "page_url": "http://ontopo/hudson",
        "date": "מחר",
        "time": "20:00",
        "party_size": 2,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("pc"))

    assert not log_calls  # לא נרשמה הזמנה
    assert pipeline._booking["pc"]["state"] == "card"
    assert sent and "כרטיס אשראי" in sent[-1]
    assert "http://ontopo/hudson" in sent[-1]  # זרוע C: הלינק נמסר
    assert not any("סגור ✅" in m for m in sent)  # לא מזייפים סגירה


def test_run_commit_without_name_asks_no_book(monkeypatch):
    """job בלי שם → לא קוראים ל-book_table, שואלים על איזה שם, וה-gate נשאר לתשובה."""
    _reset()
    sent, book_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        book_calls.append(kwargs)
        raise AssertionError("book_table לא אמור להיקרא בלי שם")

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)

    pipeline._pending_commit["p2"] = {"restaurant": "הדסון", "page_url": "http://x", "name": ""}
    asyncio.run(pipeline.run_commit("p2"))

    assert not book_calls
    assert sent and "שם" in sent[0]
    assert "p2" in pipeline._pending_commit  # נשאר ממתין לשם


def test_run_booking_populates_gate(monkeypatch):
    """שער dry-run מצליח → state=pending ו-_pending_commit מאוכלס בפרמטרי ההזמנה."""
    _reset()

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {"status": "one", "url": "http://hudson", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="הגעתי למסך האישור (DRY_RUN).",
            details={"time": "20:00", "restaurant": "הדסון", "date": "מחר"},
        )

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {
        "task_type": "restaurant",
        "restaurant": "הדסון",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("p3", fields))

    assert pipeline._booking["p3"]["state"] == "pending"
    job = pipeline._pending_commit["p3"]
    assert job["restaurant"] == "הדסון" and job["page_url"] == "http://hudson"
    assert job["party_size"] == 4 and job["name"] == "אלון"


def _route(monkeypatch, *, dry_run, result, pending=False):
    """מריץ handle_inbound עם converse מזויף ו-_spawn שלוכד בלי להריץ. מחזיר רשימת השמות שנוטחו."""
    _reset()
    spawned = []

    async def fake_converse(phone, text):
        return result

    async def fake_send_text(phone, msg):
        pass

    async def fake_send_typing(mid):
        pass

    def fake_spawn(coro):
        spawned.append(coro.__qualname__)
        coro.close()  # לא מריצים את ההזמנה האמיתית בטסט

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    monkeypatch.setattr(pipeline, "_spawn", fake_spawn)
    monkeypatch.setattr(pipeline.settings, "dry_run", dry_run)
    if pending:
        pipeline._pending_commit["pX"] = {
            "restaurant": "הדסון",
            "page_url": "http://x",
            "name": "אלון",
        }
    asyncio.run(pipeline.handle_inbound("pX", "מאשר"))
    return spawned


def test_handle_inbound_suppresses_character_leak(monkeypatch):
    """שכבת המגן האחרונה: reply שמסגיר AI לא יוצא לוואטסאפ — הודעת גישור בדמות במקומו."""
    _reset()
    sent = []

    async def fake_converse(phone, text):
        return {"reply": "כמודל שפה אני לא יכול להזמין שולחן", "ready": False}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_typing(mid):
        pass

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    asyncio.run(pipeline.handle_inbound("pL", "תזמין לי שולחן"))

    assert sent and "כמודל" not in sent[-1]  # הדליפה לא הגיעה ללקוח
    assert "רגע" in sent[-1]  # הודעת גישור בדמות


def test_book_table_empty_record_dir_disables_recording(monkeypatch, tmp_path):
    """BU_RECORD_DIR ריק (פרודקשן) → אין הקלטה בכלל (record_dir=""), אבל קובץ
    התוצאה עדיין נכתב ונקרא. הבאג הישן: fallback ל-/tmp הדליק וידאו+GIF שתקעו
    את ה-runner אחרי שהדפדפן סיים — והלקוח לא קיבל תשובה."""
    import json as _json

    from app.automation import browser_book

    captured = {}

    async def fake_run(job):
        captured.update(job)
        with open(job["result_path"], "w", encoding="utf-8") as f:
            _json.dump({"success": True, "message": "SUMMARY_REACHED"}, f)

    monkeypatch.setattr(browser_book, "_run_subprocess", fake_run)
    monkeypatch.setattr(browser_book.settings, "bu_record_dir", "")
    monkeypatch.setattr(browser_book.settings, "bu_browser", "local")
    monkeypatch.setattr(browser_book.settings, "bu_chrome_path", "")

    res = asyncio.run(
        browser_book.book_table_bu(
            restaurant="רוסטיקו",
            page_url="http://x",
            date="4.7",
            time="16:00",
            party_size=2,
        )
    )
    assert captured["record_dir"] == ""  # אין הקלטה — bu_runner לא ידליק וידאו/GIF
    assert captured["result_path"].startswith("/tmp/")  # התוצאה עדיין נכתבת
    assert res.success is True


def test_seed_contains_today_line_with_concrete_date():
    """בלי שורת 'היום' המודל לא יכול לחשב 'מחר' לתאריך — וזה נשלח לדפדפן."""
    import re

    line = pipeline._today_line()
    assert re.search(r"היום: יום \S+, \d{1,2}\.\d{1,2}\.\d{4}", line)
    assert "היום: יום" in pipeline._seed_from(None, [])


def test_seed_gender_from_profile_activates_addressing():
    """profile.gender (נאסף בשיחה) מפעיל את הטיית הפנייה — היה ענף מת."""
    seed = pipeline._seed_from({"prefs": {"gender": "male"}}, [])
    assert "זכר" in seed
    assert "לא ידוע" in pipeline._seed_from(None, [])  # בלי פרופיל — ניטרלי


def test_pending_commit_carries_email_and_notes(monkeypatch):
    """C6: הסגירה האמיתית מקבלת את המייל וה-notes שנאספו — בלי זה MISSING:email מיותר."""
    _reset()
    captured = {}

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        captured.update(kwargs)
        return ActionResult(success=True, summary="SUMMARY_REACHED", details={})

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {
        "task_type": "restaurant",
        "restaurant": "גרקו",
        "date": "6.7",
        "time": "16:00",
        "party_size": 2,
        "name": "אלון",
        "email": "a@b.com",
        "notes": "ישיבה בחוץ",
    }
    asyncio.run(pipeline.run_booking("pC", fields))

    assert captured["notes"] == "ישיבה בחוץ"  # recon מקבל את ההעדפות
    job = pipeline._pending_commit["pC"]
    assert job["email"] == "a@b.com" and job["notes"] == "ישיבה בחוץ"


def test_handle_inbound_splits_reply_lines_into_separate_messages(monkeypatch):
    """וואטסאפ אנושי = הודעות קצרות: כל שורה נשלחת כהודעה נפרדת, עם typing+השהיה בין הודעות."""
    _reset()
    sent, paces, typing = [], [], []

    async def fake_converse(phone, text):
        return {"reply": "סגור אחי\nבודק לך את זה\nשניה איתי", "ready": False}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_typing(mid):
        typing.append(mid)

    async def fake_pace(seconds):
        paces.append(seconds)

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    monkeypatch.setattr(pipeline, "_pace", fake_pace)
    asyncio.run(pipeline.handle_inbound("pS", "תסגור לי משהו", message_id="wamid.X"))

    assert sent == ["סגור אחי", "בודק לך את זה", "שניה איתי"]
    assert len(paces) == 2 and all(0.8 <= p <= 2.5 for p in paces)  # השהיה בין הודעות בלבד
    assert typing == ["wamid.X", "wamid.X", "wamid.X"]  # פתיחה + לפני כל הודעת המשך


def test_route_confirm_blocked_when_dry_run(monkeypatch):
    """dry_run=True: 'מאשר' (confirm) על הזמנה ממתינה לא מפעיל סגירה אמיתית."""
    spawned = _route(
        monkeypatch, dry_run=True, result={"reply": "מוכן", "confirm": True}, pending=True
    )
    assert spawned == []  # שום סגירה


def test_route_confirm_commits_when_live(monkeypatch):
    """dry_run=False: 'מאשר' על הזמנה ממתינה → run_commit."""
    spawned = _route(
        monkeypatch, dry_run=False, result={"reply": "סוגר", "confirm": True}, pending=True
    )
    assert spawned == ["run_commit"]


def test_route_ready_starts_booking_and_drops_gate(monkeypatch):
    """ready=True (הזמנה חדשה/שונה) → run_booking, וה-gate הישן ננטש."""
    spawned = _route(
        monkeypatch, dry_run=False, result={"reply": "יאללה", "ready": True}, pending=True
    )
    assert spawned == ["run_booking"]
    assert "pX" not in pipeline._pending_commit


def test_route_double_fire_guard_blocks_second_booking(monkeypatch):
    """באג 4: הזמנה כבר רצה (state=working) — ready=true שני (למשל '?' של הלקוח) לא יורה שוב."""
    _reset()
    spawned = []

    async def fake_converse(phone, text):
        return {"reply": "על זה", "ready": True}

    async def fake_send_text(phone, msg):
        pass

    async def fake_send_typing(mid):
        pass

    def fake_spawn(coro):
        spawned.append(coro.__qualname__)
        coro.close()

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_typing", fake_send_typing)
    monkeypatch.setattr(pipeline, "_spawn", fake_spawn)
    monkeypatch.setattr(pipeline.settings, "dry_run", False)

    pipeline._booking["pY"] = {"state": "working", "info": ""}
    asyncio.run(pipeline.handle_inbound("pY", "?"))
    assert spawned == []  # הזמנה כבר בתהליך — לא יורים שנייה


def test_run_booking_missing_field_asks_no_book(monkeypatch):
    """באג 3: recon מחזיר MISSING:email → גבר מבקש מהלקוח, state=missing, אין סגירה/log."""
    _reset()
    sent, log_calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://hudson", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="חסר מייל",
            details={"missing": "email"},
        )

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    async def fake_log(*a, **k):
        log_calls.append(1)

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    fields = {
        "task_type": "restaurant",
        "restaurant": "הדסון",
        "date": "מחר",
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("p4", fields))

    assert pipeline._booking["p4"]["state"] == "missing"
    assert pipeline._booking["p4"]["info"] == "email"
    assert "p4" not in pipeline._pending_commit  # לא נפתח gate — אין הזמנה ממתינה
    assert not log_calls  # לא נרשמה הזמנה
    assert sent and "מייל" in sent[-1]  # גבר ביקש את הפרט החסר


def test_run_booking_alt_time_is_offered_not_silently_booked(monkeypatch):
    """הלקוח ביקש 20:30, נמצא רק 21:00 → גבר מציע את החלופה במפורש לפני סגירה:
    alt_time נשמר, ה-truth_note מנחה להגיד את זה, וה-commit ייסגר על 21:00 שאושרה."""
    _reset()

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=True, summary="SUMMARY_REACHED 21:00", details={"time": "21:00"}
        )

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {
        "task_type": "restaurant",
        "restaurant": "טאיזו",
        "time": "20:30",
        "name": "אלון",
    }
    asyncio.run(pipeline.run_booking("p8", fields))

    assert pipeline._booking["p8"]["state"] == "pending"
    assert pipeline._booking["p8"]["alt_time"] == {"requested": "20:30", "actual": "21:00"}
    note = pipeline._truth_note("p8")
    assert "21:00" in note and "20:30" in note  # הפרסונה מקבלת הוראה להציע את החלופה
    assert pipeline._pending_commit["p8"]["time"] == "21:00"  # הסגירה על השעה שתאושר


def test_run_booking_card_wall_sends_link_immediately(monkeypatch):
    """קיר כרטיס שהתגלה כבר ב-recon → לא 'לסגור?' חסר-משמעות אלא לינק מיידי
    לסגירה עצמית, state='card', ואין הזמנה ממתינה לאישור."""
    _reset()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://rustico", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED CARD_REQUIRED",
            details={"card_required": True, "summary_reached": True},
        )

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "רוסטיקו", "time": "16:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("p9", fields))

    assert pipeline._booking["p9"]["state"] == "card"
    assert "http://rustico" in sent[-1]  # הלינק נשלח מיד
    assert "כרטיס" in sent[-1]
    assert "p9" not in pipeline._pending_commit  # אין gate לאישור — אין מה לאשר


def test_run_booking_falls_back_to_next_platform(monkeypatch):
    """A3 (תרחיש גרקו): הניסיון הראשון נכשל בפועל (דף Ontopo מת) ויש fallback מ-Tabit →
    ניסיון שני אחד, וה-pending_commit נשמר עם הנתיב שהצליח."""
    _reset()
    sent, calls = [], []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {
            "status": "one",
            "url": "http://ontopo-dead",
            "platform": "ontopo",
            "candidates": [],
            "fallback": {"url": "http://tabit-live", "platform": "tabit"},
        }

    async def fake_book(**kwargs):
        calls.append((kwargs["page_url"], kwargs["platform"]))
        if kwargs["page_url"] == "http://ontopo-dead":
            return ActionResult(success=False, summary="FAILED:no_availability", details={})
        return ActionResult(success=True, summary="SUMMARY_REACHED", details={})

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "20:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("p6", fields))

    assert calls == [("http://ontopo-dead", "ontopo"), ("http://tabit-live", "tabit")]
    assert pipeline._booking["p6"]["state"] == "pending"
    job = pipeline._pending_commit["p6"]
    assert job["page_url"] == "http://tabit-live" and job["platform"] == "tabit"


def test_run_booking_missing_field_does_not_fallback(monkeypatch):
    """MISSING = חסר נתון מהלקוח — יחסר גם בפלטפורמה השנייה; לא שורפים ניסיון שני."""
    _reset()
    calls = []

    async def fake_send_text(phone, msg):
        pass

    async def fake_resolve(name):
        return {
            "status": "one",
            "url": "http://a",
            "platform": "ontopo",
            "candidates": [],
            "fallback": {"url": "http://b", "platform": "tabit"},
        }

    async def fake_book(**kwargs):
        calls.append(kwargs["page_url"])
        return ActionResult(success=False, summary="MISSING:email", details={"missing": "email"})

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "20:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("p7", fields))

    assert calls == ["http://a"]  # ניסיון אחד בלבד
    assert pipeline._booking["p7"]["state"] == "missing"


def test_run_booking_no_availability_gets_specific_honest_message(monkeypatch):
    """FAILED:no_availability (מסעדה סגורה/מלאה) → אמת ספציפית ללקוח, לא כישלון גנרי."""
    _reset()
    sent = []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "platform": "ontopo", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(
            success=False, summary="FAILED:no_availability", details={"failed": "no_availability"}
        )

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "16:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("pA", fields))

    assert "אין זמינות" in sent[-1]  # אמת ספציפית
    assert pipeline._booking["pA"]["info"] == "אין זמינות במועד שביקש"  # truth_note מיושר


def test_run_booking_failure_does_not_leak_raw_agent_text(monkeypatch):
    """כישלון גנרי: res.summary הוא טקסט גולמי באנגלית של browser-use — אסור שיגיע ללקוח
    (קו-ברזל: לא חושפים אוטומציה) *ולא* ל-info (מוזרק ל-truth_note — אתר זדוני היה יכול
    להשחיל טקסט לבלוק האמת של המודל). נשמר רק ב-debug."""
    _reset()
    sent = []
    raw = "I was unable to complete the reservation. No active booking widget. CAPTCHA blocked."

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_resolve(name):
        return {"status": "one", "url": "http://x", "candidates": []}

    async def fake_book(**kwargs):
        return ActionResult(success=False, summary=raw, details={})

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fake_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)

    fields = {"task_type": "restaurant", "restaurant": "גרקו", "time": "20:00", "name": "אלון"}
    asyncio.run(pipeline.run_booking("p5", fields))

    assert pipeline._booking["p5"]["state"] == "failed"
    assert pipeline._booking["p5"]["info"] == ""  # הגולמי לא נכנס ל-truth_note
    assert pipeline._booking["p5"]["debug"] == raw  # נשמר לדיבוג בלבד
    assert raw not in pipeline._truth_note("p5")  # בלוק האמת נקי מטקסט צד-שלישי
    assert sent  # נשלחה הודעה
    assert raw not in sent[-1]  # אבל לא הטקסט הגולמי
    assert "I was unable" not in sent[-1] and "CAPTCHA" not in sent[-1]
    assert "גרקו" in sent[-1]  # הודעת דמות בעברית שנוקבת בשם המסעדה


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
