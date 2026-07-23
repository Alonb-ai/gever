"""בדיקות pipeline לוורטיקל ההופעות: routing ל-resolve_event_url, העברת
task_type/artist/venue ל-book_table_bu, הודעת קיר-כרטיס עם הסכום לפני התשלום,
רשימות MISSING:date/price_category, _failure_reply הופעות, ושחזור ב-run_commit."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

_FIELDS = {
    "task_type": "events",
    "artist": "קובי פרץ",
    "venue": "היכל מנורה",
    "date": "11.08",
    "party_size": 2,
    "name": "אלון",
}

_EVENT_URL = "https://www.leaan.co.il/events/kobi-peretz/5514"


def _reset():
    pipeline._booking.clear()
    pipeline._pending_commit.clear()
    pipeline._reset_next.clear()
    pipeline._turns.clear()
    pipeline._last_seen.clear()
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()
    pipeline._preresolve.clear()
    pipeline._await_answer.clear()


def _wire(monkeypatch, *, book, resolve=None, sent=None, lists=None):
    """חיווט הפייקים המשותף: resolve הופעות (ברירת מחדל one→leaan), book, ושליחות."""
    sent = sent if sent is not None else []
    lists = lists if lists is not None else []

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_send_list(phone, body, options, button="בחירה"):
        lists.append((body, options))

    async def default_resolve(artist, venue=""):
        return {
            "status": "one",
            "url": _EVENT_URL,
            "platform": "leaan",
            "candidates": [],
            "fallback": None,
        }

    async def fail_restaurant_resolve(name):
        raise AssertionError("resolve_reservation_url לא אמור להיקרא בהופעות")

    async def fail_cinema_resolve(name):
        raise AssertionError("resolve_cinema_url לא אמור להיקרא בהופעות")

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        pass

    async def fake_get_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "resolve_event_url", resolve or default_resolve)
    monkeypatch.setattr(pipeline, "resolve_reservation_url", fail_restaurant_resolve)
    monkeypatch.setattr(pipeline, "resolve_cinema_url", fail_cinema_resolve)
    monkeypatch.setattr(pipeline, "book_table_bu", book)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    return sent, lists


def test_events_routes_to_event_resolver_and_passes_vertical_fields(monkeypatch):
    """task_type='events' → resolve_event_url(artist, venue), ו-book_table_bu מקבל
    task_type/artist/venue; name המשותף = שם האמן (נכנס ל-_booking.info)."""
    _reset()
    captured = {}
    resolved = []

    async def fake_resolve(artist, venue=""):
        resolved.append((artist, venue))
        return {
            "status": "one",
            "url": _EVENT_URL,
            "platform": "leaan",
            "candidates": [],
            "fallback": None,
        }

    async def fake_book(**kwargs):
        captured.update(kwargs)
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 21:00 | פרטר CARD_REQUIRED",
            details={"card_required": True, "time": "21:00", "seats": "פרטר"},
        )

    _wire(monkeypatch, book=fake_book, resolve=fake_resolve)
    asyncio.run(pipeline.run_booking("e1", dict(_FIELDS)))

    assert resolved == [("קובי פרץ", "היכל מנורה")]
    assert captured["task_type"] == "events"
    assert captured["artist"] == "קובי פרץ" and captured["venue"] == "היכל מנורה"
    assert captured["movie"] == ""  # לא סרט
    assert captured["restaurant"] == "קובי פרץ"  # name המשותף לכל מנגנוני הקיצור
    assert captured["dry_run"] is True
    assert captured["page_url"] == _EVENT_URL


def test_events_card_wall_price_before_payment_and_wrapped_link(monkeypatch):
    """העצירה-המוצלחת הסטנדרטית של הופעות: קיר-כרטיס → שם המופע, שעת המופע, מקטע
    ה-seats עם הסכום, לינק עטוף (לא browserbase גולמי), ו-return מוקדם."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary='SUMMARY_REACHED 21:00 | פרטר שורה 12 מושבים 7,8 — סה"כ 640 ש"ח CARD_REQUIRED',
            details={
                "card_required": True,
                "time": "21:00",
                "seats": 'פרטר שורה 12 מושבים 7,8 — סה"כ 640 ש"ח',
                "session_id": "sess-ev",
            },
        )

    async def fake_live_view(session_id):
        return "https://live.browserbase.com/sess-ev"

    sent, _ = _wire(monkeypatch, book=fake_book)
    monkeypatch.setattr(pipeline, "live_view_url", fake_live_view)
    asyncio.run(pipeline.run_booking("e2", dict(_FIELDS)))

    from app import live_link
    from app.config import settings

    assert pipeline._booking["e2"]["state"] == "card"
    final = sent[-1]
    assert "קובי פרץ" in final and "21:00" in final
    assert "640" in final  # ההודעה נוקבת בסכום לפני התשלום
    assert "התשלום" in final
    # לינק ממותג — לא browserbase גולמי
    assert "browserbase.com" not in final
    assert f"{settings.public_base_url}/b/" in final
    token = final.split("/b/")[1].split()[0].strip()
    assert live_link.resolve(token) == "https://live.browserbase.com/sess-ev"
    # return מוקדם — אין הודעת מסעדה ("כרטיס אשראי לסגירה") אחרי הודעת הקיר
    # (sent[0] הוא סימן-החיים של ה-heartbeat; הודעת הקיר היא האחרונה)
    assert not any("כרטיס אשראי" in m for m in sent)
    assert "e2" not in pipeline._pending_commit  # אין מה לאשר — הלקוח סוגר בעצמו


def test_events_card_wall_vary_anchors_all_variants(monkeypatch):
    """עוגני _vary נושאיים בכל הווריאנטים: שם המופע, 'התשלום', ורמז הדחיפות
    ('שמורים... דקות') — בלי לנעול נוסח מדויק (הלקח מ-e5deca0). וגם: בלי 'שנייה'."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary="SUMMARY_REACHED 21:00 | פרטר CARD_REQUIRED",
            details={"card_required": True, "time": "21:00", "seats": "פרטר"},
        )

    for i in range(12):  # מגלגל את כל וריאנטי _vary
        sent, _ = _wire(monkeypatch, book=fake_book)
        asyncio.run(pipeline.run_booking(f"e3-{i}", dict(_FIELDS)))
        final = sent[-1]
        assert "קובי פרץ" in final and "התשלום" in final, final
        assert "שמורים" in final and "דקות" in final, final  # דחיפות בלי טיימר לא-מאומת
        assert "שנייה" not in final, final


def test_events_missing_price_category_sends_real_options_with_prices(monkeypatch):
    """MISSING:price_category עם OPTIONS מהדף → רשימת בחירה אמיתית עם המחירים
    כלשונם; גוף ההודעה נוקב ב'קטגוריית מחיר'; הסשן נשמר ל-resume."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:price_category",
            details={
                "missing": "price_category",
                "options": ['פרטר 320 ש"ח', 'יציע 180 ש"ח'],
                "session_id": "sess-e",
                "stage": "עצרתי על קטגוריה",
            },
        )

    sent, lists = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("e4", dict(_FIELDS)))

    assert pipeline._booking["e4"]["state"] == "missing"
    assert pipeline._booking["e4"]["info"] == "price_category"
    assert len(lists) == 1
    body, options = lists[0]
    assert options == ['פרטר 320 ש"ח', 'יציע 180 ש"ח']
    assert "קטגוריית מחיר" in body
    assert pipeline._resume["e4"]["session_id"] == "sess-e"  # pause-resume חי


def test_events_missing_date_sends_real_dates_list(monkeypatch):
    """MISSING:date עם מועדים מהדף (כולל עיר/היכל) → רשימת טאפ של המועדים האמיתיים."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="MISSING:date",
            details={
                "missing": "date",
                "options": ['11/08 היכל מנורה ת"א', "15/08 היכל הפיס חיפה"],
            },
        )

    sent, lists = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("e5", {**_FIELDS, "date": ""}))

    assert len(lists) == 1
    body, options = lists[0]
    assert options == ['11/08 היכל מנורה ת"א', "15/08 היכל הפיס חיפה"]
    assert "תאריך" in body


def test_failure_reply_events_wordings_and_restaurant_unchanged():
    """sold_out (סיבה חדשה) ו-no_event_in_city תחת events; מסעדות לא מכירות אותן.
    (עודכן במיזוג: _failure_reply נהיה async — קול חופשי דרך _say; העוגנים בעינם.)"""
    info, msg = asyncio.run(pipeline._failure_reply("sold_out", "קובי פרץ", task_type="events"))
    assert "אזלו" in info and "קובי פרץ" in msg
    assert "אזלו" in msg or "sold out" in msg  # עוגן נושאי בכל וריאנט

    info, msg = asyncio.run(
        pipeline._failure_reply(
            "no_event_in_city", "קובי פרץ", task_type="events", city="היכל מנורה"
        )
    )
    assert "היכל מנורה" in info and "היכל מנורה" in msg and "קובי פרץ" in msg

    # מסעדות: הסיבות החדשות לא קיימות שם
    assert asyncio.run(pipeline._failure_reply("sold_out", "גרקו")) is None
    assert asyncio.run(pipeline._failure_reply("no_event_in_city", "גרקו")) is None
    # ומסעדה רגילה לא זזה
    info, msg = asyncio.run(pipeline._failure_reply("no_availability", "גרקו"))
    assert "אין מקום פנוי" in info


def test_failure_reply_no_upcoming_dates_is_honest_not_sold_out():
    """QA חי הופעות #3: דף בלי מועדים → 'אין כרגע מועדים מוכרזים' (לא 'אזלו');
    הסיבה קיימת רק בהופעות."""
    info, msg = asyncio.run(
        pipeline._failure_reply("no_upcoming_dates", "עומר אדם", task_type="events")
    )
    assert "מועדים מוכרזים" in info
    assert "עומר אדם" in msg
    assert "אזלו" not in info  # לא sold_out כוזב
    assert asyncio.run(pipeline._failure_reply("no_upcoming_dates", "גרקו")) is None


def test_events_failed_sold_out_message_uses_venue_as_location(monkeypatch):
    """FAILED:no_event_in_city בהופעה → ההודעה נוקבת ב-venue (לא ב-city של קולנוע)."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary="FAILED:no_event_in_city",
            details={"failed": "no_event_in_city"},
        )

    sent, _ = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("e6", dict(_FIELDS)))

    assert pipeline._booking["e6"]["state"] == "failed"
    assert "היכל מנורה" in sent[-1]


def test_events_pending_skips_alt_time_and_carries_commit_fields(monkeypatch):
    """סיכום בלי קיר (כמעט תיאורטי): אין alt_time (השעה נגזרת מהמופע), ההודעה נוקבת
    בשעת המופע + שורת המחיר ושואלת 'לסגור?'; _pending_commit נושא artist/venue."""
    _reset()

    async def fake_book(**kwargs):
        return ActionResult(
            success=True,
            summary='SUMMARY_REACHED 21:00 | יציע — סה"כ 360 ש"ח',
            details={"time": "21:00", "seats": 'יציע — סה"כ 360 ש"ח'},
        )

    sent, _ = _wire(monkeypatch, book=fake_book)
    asyncio.run(pipeline.run_booking("e7", dict(_FIELDS)))

    assert pipeline._booking["e7"]["state"] == "pending"
    assert "alt_time" not in pipeline._booking["e7"]
    final = sent[-1]
    assert "21:00" in final and "360" in final
    assert "סגור" in final and final.endswith("?")
    job = pipeline._pending_commit["e7"]
    assert job["task_type"] == "events"
    assert job["artist"] == "קובי פרץ" and job["venue"] == "היכל מנורה"
    assert job["movie"] == ""


def test_events_none_and_empty_artist_messages(monkeypatch):
    """resolve=none → 'לא מצאתי איפה קונים כרטיסים... המופע'; artist ריק → שאלה
    ניטרלית-מגדר, בלי resolve ובלי 'שנייה'."""
    _reset()
    resolves = []

    async def fake_resolve(artist, venue=""):
        resolves.append(artist)
        return {"status": "none", "url": None, "platform": None, "candidates": []}

    async def fake_book(**kwargs):
        raise AssertionError("אין book כש-resolve=none")

    sent, _ = _wire(monkeypatch, book=fake_book, resolve=fake_resolve)
    asyncio.run(pipeline.run_booking("e8", dict(_FIELDS)))
    # עוגנים ולא ניסוח: שם המופע + "לא" (לא נמצא)
    assert "קובי פרץ" in sent[-1] and "לא" in sent[-1]
    assert pipeline._booking["e8"]["state"] == "none"

    for i in range(6):  # מגלגל את וריאנטי _vary של הגנת השם הריק
        asyncio.run(pipeline.run_booking(f"e9-{i}", {**_FIELDS, "artist": ""}))
        assert "הופעה" in sent[-1] or "מופע" in sent[-1] or "אמן" in sent[-1]
        assert "שנייה" not in sent[-1]
    assert resolves == ["קובי פרץ"]  # ה-resolve לא נקרא על שם ריק
    assert "e9-0" not in pipeline._booking


def test_events_do_not_pick_stale_restaurant_preresolve(monkeypatch):
    """pre-resolve הוא מסעדות בלבד — בקשת הופעות לא קוטפת תוצאה ישנה שלו, גם כשהשם
    זהה; ה-task הישן מבוטל."""
    _reset()

    async def run():
        # task ישן שתלוי באוויר (כאילו resolve מסעדות שרץ ברקע) — אסור לקטוף אותו
        t = asyncio.ensure_future(asyncio.sleep(100))
        pipeline._preresolve["e10"] = {"name": "קובי פרץ", "task": t}

        captured = {}

        async def fake_book(**kwargs):
            captured.update(kwargs)
            return ActionResult(
                success=True,
                summary="SUMMARY_REACHED 21:00 | פרטר CARD_REQUIRED",
                details={"card_required": True, "time": "21:00", "seats": "פרטר"},
            )

        _wire(monkeypatch, book=fake_book)
        await pipeline.run_booking("e10", dict(_FIELDS))
        await asyncio.sleep(0)  # נותן לביטול להיקלט בלולאה
        assert t.cancelled()  # ה-task הישן בוטל, לא נקטף
        assert captured["page_url"] == _EVENT_URL  # הגיע מ-resolve_event_url
        assert "e10" not in pipeline._preresolve  # נצרך (pop), לא נשאר

    asyncio.run(run())


def test_run_commit_restores_events_job_and_talks_email(monkeypatch):
    """_pending_commit שומר task_type/artist/venue ו-run_commit מעביר אותם; הודעת
    ההצלחה מדברת על כרטיסים במייל — בלי 'סועדים'/'שולחן'/'הקרנה'/SMS."""
    _reset()
    sent = []
    captured = {}

    async def fake_send_text(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        captured.update(kwargs)
        return ActionResult(success=True, summary="BOOKED 555", details={"confirmation": "555"})

    async def fake_log(*a, **k):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)

    job = {
        "restaurant": "קובי פרץ",
        "page_url": _EVENT_URL,
        "platform": "leaan",
        "date": "11.08",
        "time": "21:00",
        "party_size": 2,
        "name": "אלון",
        "task_type": "events",
        "movie": "",
        "city": "",
        "artist": "קובי פרץ",
        "venue": "היכל מנורה",
    }
    for i in range(12):  # מגלגל את כל וריאנטי _vary
        pipeline._pending_commit[f"e11-{i}"] = dict(job)
        asyncio.run(pipeline.run_commit(f"e11-{i}"))
        final = sent[-1]
        assert "קובי פרץ" in final and "כרטיסים" in final and "מייל" in final
        assert "555" in final  # מספר האישור מצורף
        for banned in ("סועדים", "שולחן", "מסעדה", "הקרנה", "SMS"):
            assert banned not in final, final
        assert pipeline._booking[f"e11-{i}"]["state"] == "done"

    assert captured["task_type"] == "events"
    assert captured["artist"] == "קובי פרץ" and captured["venue"] == "היכל מנורה"
    assert captured["dry_run"] is False


def test_events_schema_and_extract_know_events():
    """ה-_SCHEMA וה-_EXTRACT מכירים את הוורטיקל: enum, artist/venue, וכללי ready
    (בלי time; date לא עוצר את השיחה)."""
    assert "events" in pipeline._SCHEMA["properties"]["task_type"]["enum"]
    assert "artist" in pipeline._SCHEMA["properties"]
    assert "venue" in pipeline._SCHEMA["properties"]
    assert "task_type='events'" in pipeline._EXTRACT
    assert "time אינו שדה" in pipeline._EXTRACT
