"""שכבת השיחה — 7 באגים מהבדיקות החיות של 23.7 (~20:40), משוחזרים מהשיחות
האמיתיות (tests/fixtures/convo_a.json / convo_b.json — dump אנונימי של
prefs._chat+_flow). כולם בתפר בין תוצאת-הדפדפן לניסוח של מודל השיחה — מה
שה-QA הקיים לא כיסה:

1. המצאת אופציות: המודל פרפרז את רשימת השעות/התאריכים והמציא (20:00...23:30
   כשבפועל היו רק 21:30/21:45/22:00; 24.07-28.07 מול 25.07-29.07).
2. שעות שכבר עברו הוצעו (20:00 כשהשעה 20:45+).
3. ירי כפול: זרימת ההמלצות רצה פעמיים במקביל — שתי רשימות שונות על הודעה אחת.
4. "מרפסת - רשימת המתנה" נוסח כ"הכל מלא" במקום הצעת waitlist.
5. המלצה על מקום שכבר נפסל בשיחה (רק הכשל האחרון סונן).
6. המלצות לא-מאומתות ("Château Shuál") נשלחו בלי בדיקת קיום.
7. טקסט כפתור ("Book now") זלג לשם מועמד.

הכל ממוקק — אפס רשת ואפס LLM (Tier 2 ב-poc/convo_eval.py הוא ה-LLM-in-loop).
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# האופציות האמיתיות מהריצה החיה (שיחה A — הנסיך, MISSING:time)
REAL_TIME_OPTIONS = json.loads((FIXTURES / "convo_a.json").read_text(encoding="utf-8"))[0]["prefs"][
    "_flow"
]["await_answer"]["options"]

# התאריכים האמיתיים מהריצה החיה (שיחה B — ג'ניה, MISSING:date)
REAL_DATE_OPTIONS = ["25.07", "26.07", "27.07", "28.07", "29.07"]


@pytest.fixture(autouse=True)
def _clean_state():
    names = (
        "_booking",
        "_await_answer",
        "_resume",
        "_resolved",
        "_pending_pick",
        "_preresolve",
        "_recs",
        "_rejected",
        "_rec_inflight",
        "_turns",
        "_last_out",
        "_last_seen",
        "_pending_commit",
    )
    for name in names:
        d = getattr(pipeline, name, None)
        if d is not None:
            d.clear()
    yield


@pytest.fixture
def sent(monkeypatch):
    """לוכד כל מה שיוצא ללקוח; מנטרל התמדה ופרופיל."""
    out: list = []

    async def fake_send_text(phone, msg):
        out.append(("text", msg))

    async def fake_send_list(phone, body, labels):
        out.append(("list", body, tuple(labels)))

    async def fake_typing(mid):
        pass

    async def noop(phone):
        pass

    async def no_profile(phone):
        return None

    monkeypatch.setattr(pipeline, "send_text", fake_send_text)
    monkeypatch.setattr(pipeline, "send_list", fake_send_list)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    monkeypatch.setattr(pipeline, "_persist_chat", noop)
    monkeypatch.setattr(memory, "get_profile", no_profile)
    return out


def _all_text(sent) -> str:
    return "\n".join(m[1] for m in sent)


# ─── עזרי טוקנים (הגארד של באג 1+2) ─────────────────────────────────────────


def test_option_tokens_extracts_times_and_dates():
    toks = pipeline._option_tokens(["21:30 (סלון)", "25.07", "ב-23.7.2026 בשעה 09:15"])
    assert toks == {"21:30", "25.7", "23.7", "9:15"}


def test_foreign_option_tokens_subset_check():
    allowed = pipeline._option_tokens([*REAL_TIME_OPTIONS, "22:30"])
    # ההודעה שנשלחה בפועל בבדיקה החיה — כל השעות האלו מומצאות
    invented = "אבל יש כמה אופציות אחרות פנויות להיום\n20:00\n20:30\n21:00\n23:00\n23:30"
    foreign = pipeline._foreign_option_tokens(invented, allowed)
    assert set(foreign) == {"20:00", "20:30", "21:00", "23:00", "23:30"}
    # מה שכן מהרשימה — לא זר
    assert pipeline._foreign_option_tokens("יש 21:30 או 22:00", allowed) == []


def test_filter_invented_lines_keeps_real_content():
    allowed = pipeline._option_tokens([*REAL_TIME_OPTIONS, "22:30"])
    reply = "שומעים ב 22:30 הכל מלא שם\nיש 20:00\nיש 21:30\nמה סוגרים?"
    filtered = pipeline._filter_invented_lines(reply, allowed)
    assert "20:00" not in filtered
    assert "22:30" in filtered and "21:30" in filtered and "מה סוגרים?" in filtered


# ─── באג 1: אופציות בהודעה היוצאת ⊆ האופציות האמיתיות ──────────────────────


def _missing_result(field, options):
    async def fake_book(**kwargs):
        return ActionResult(
            success=False,
            summary=f"MISSING:{field}",
            details={"missing": field, "options": options, "session_id": "s-1", "stage": "x"},
        )

    return fake_book


def _run_booking_missing(monkeypatch, field, options, *, fields=None):
    monkeypatch.setattr(pipeline, "book_table_bu", _missing_result(field, options))
    pipeline._resolved["p1"] = {"name": "הנסיך", "url": "http://x", "platform": "ontopo"}
    asyncio.run(
        pipeline.run_booking(
            "p1",
            fields or {"restaurant": "הנסיך", "date": "23.07", "time": "22:30", "party_size": 4},
        )
    )


def test_alt_time_offer_model_invention_rejected(monkeypatch, sent):
    """שחזור הבאג החי: מודל הקול-החופשי מנסח כותרת עם שעות מומצאות (20:00...)
    — הוולידטור חייב לפסול וליפול לנוסח הבטוח; אף שעה זרה לא יוצאת ללקוח."""

    async def invent(intent, ctx):
        return (
            "שומעים ב 22:30 הכל מלא שם\nאבל יש כמה אופציות אחרות פנויות להיום\n"
            "20:00\n20:30\n21:00\n23:00\n23:30\nמה אומרים מה לסגור? 🎯"
        )

    monkeypatch.setattr(pipeline, "_say_model", invent)
    _run_booking_missing(monkeypatch, "time", REAL_TIME_OPTIONS)
    out = _all_text(sent)
    allowed = pipeline._option_tokens([*REAL_TIME_OPTIONS, "22:30"])
    assert pipeline._foreign_option_tokens(out, allowed) == [], out


def test_alt_date_offer_model_invention_rejected(monkeypatch, sent):
    """אותו באג עם תאריכים (שיחה B): המודל כתב 24.07-28.07 כשהרשימה 25.07-29.07."""

    async def invent(intent, ctx):
        return "אין מקום ב 23.07\nאבל יש 24.07\n25.07\n26.07\n27.07\n28.07\nמה סוגרים?"

    monkeypatch.setattr(pipeline, "_say_model", invent)
    _run_booking_missing(
        monkeypatch,
        "date",
        REAL_DATE_OPTIONS,
        fields={"restaurant": "הנסיך", "date": "23.07", "time": "22:00", "party_size": 3},
    )
    out = _all_text(sent)
    allowed = pipeline._option_tokens([*REAL_DATE_OPTIONS, "23.07"])
    assert pipeline._foreign_option_tokens(out, allowed) == [], out


def test_say_violations_flags_invented_tokens():
    ctx = {
        "requested": "22:30",
        "n_options": 6,
        "_allowed_tokens": pipeline._option_tokens([*REAL_TIME_OPTIONS, "22:30"]),
    }
    bad = "ה-22:30 תפוס, יש 20:00 או 21:00 — לסגור אחת?"
    assert any(
        p.startswith("invented") for p in pipeline._say_violations("alt_time_offer", ctx, bad)
    )
    good = "ה-22:30 תפוס 😮‍💨 אלו השעות שכן פנויות — לסגור אחת?"
    assert pipeline._say_violations("alt_time_offer", ctx, good) == []


def test_say_prompt_hides_internal_ctx_keys():
    """מפתחות _פנימיים (כמו _allowed_tokens) לא מגיעים לפרומפט של המודל."""
    _, user = pipeline._say_prompt(
        "alt_time_offer", {"requested": "22:30", "_allowed_tokens": {"x"}}
    )
    assert "_allowed_tokens" not in user


def test_converse_reply_guard_strips_invented_options(monkeypatch, sent):
    """פולו-אפ חופשי בזמן עצירת MISSING עם אופציות: שורות עם שעות מומצאות
    בתשובת הפרסונה מסוננות — האופציות בהודעה היוצאת ⊆ האמיתיות."""
    pipeline._booking["p1"] = {"state": "missing", "info": "time"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הנסיך", "date": "23.07", "time": "22:30"},
        "field": "time",
        "options": REAL_TIME_OPTIONS,
    }
    pipeline._last_seen["p1"] = time.time()

    async def fake_converse(phone, text):
        return {
            "reply": "יש עוד אופציות פנויות\n20:00\n20:30\nיש גם 21:30\nמה בא לך?",
            "ready": False,
            "task_type": "restaurant",
        }

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    asyncio.run(pipeline.handle_inbound("p1", "מה השעות שכן יש?"))
    out = _all_text(sent)
    allowed = pipeline._option_tokens([*REAL_TIME_OPTIONS, "22:30"])
    assert pipeline._foreign_option_tokens(out, allowed) == [], out
    assert "21:30" in out  # התוכן האמיתי נשאר — מסננים שורות, לא זורקים תשובה


# ─── באג 8 (לייב 24.7): הרשימה האינטראקטיבית והטקסט — מקור-אמת-יחיד ────────


def test_send_list_boundary_filters_foreign_tokens(sent):
    """שער-הגבול עצמו: גוף עם שעות שלא בשורות הרשימה מסונן ברגע השליחה —
    שחזור הצילום: הטקסט טען 19:15/21:30, הרשימה הציגה 18:30/18:45."""
    asyncio.run(
        pipeline._send_list_and_record(
            "p1",
            "יש מקום פנוי רק בשעות האלה: 19:15, 21:30\nמה לוקחים?",
            ["18:30", "18:45"],
            allow_tokens=pipeline._option_tokens(["22:30"]),
        )
    )
    kind, body, labels = sent[-1]
    assert kind == "list" and labels == ("18:30", "18:45")
    assert "19:15" not in body and "21:30" not in body
    assert "מה לוקחים?" in body  # מסננים שורות, לא זורקים את הגוף


def test_send_list_boundary_allows_requested_and_rows(sent):
    """השעה שהלקוח ביקש (allow_tokens) ושעות מהשורות עצמן — לגיטימיות בגוף."""
    asyncio.run(
        pipeline._send_list_and_record(
            "p1",
            "ה-22:30 תפוס, יש 18:30 — או אחת מאלה:",
            ["18:30", "18:45"],
            allow_tokens=pipeline._option_tokens(["22:30"]),
        )
    )
    _, body, _ = sent[-1]
    assert "22:30" in body and "18:30" in body


def test_list_message_body_subset_of_rows(monkeypatch, sent):
    """שחזור מלא דרך הפייפליין: גם כשמודל הקול-החופשי ממציא שעות בכותרת,
    ההודעה היוצאת (גוף+שורות) נבנית מאותו אובייקט options של אותה ריצה."""

    async def invent(intent, ctx):
        return "יש מקום פנוי רק בשעות האלה: 19:15, 21:30 — לסגור אחת?"

    monkeypatch.setattr(pipeline, "_say_model", invent)
    _run_booking_missing(monkeypatch, "time", ["18:30", "18:45"])
    kind, body, labels = next(m for m in sent if m[0] == "list")
    body_toks = pipeline._option_tokens([body])
    assert body_toks <= pipeline._option_tokens([*labels, "22:30"]), (body, labels)


# ─── באג 2: שעות שכבר עברו — השעה הנוכחית מוזרקת להקשר ─────────────────────


def test_today_line_includes_current_time():
    """בלי השעה הנוכחית בזרע המודל לא יכול לדעת ש-20:00 כבר עבר."""
    line = pipeline._today_line()
    assert "השעה" in line
    assert pipeline._option_tokens([line])  # יש טוקן שעה אמיתי בשורה


# ─── באג 3: ירי כפול של זרימת ההמלצות ──────────────────────────────────────


def test_recommend_no_double_fire(monkeypatch, sent):
    """שני טריגרים של המלצות בזמן שהראשון עוד רץ (שחזור 'בסגנון הגזאטה' —
    6 הודעות ack ושתי רשימות שונות): רק רשימה אחת יוצאת ללקוח."""
    calls = []

    async def slow_places(category, area="", constraints="", exclude=None):
        calls.append(category)
        await asyncio.sleep(0.05)
        return [
            {
                "name": "P0",
                "rating": 4.5,
                "reviews": 900,
                "open_now": True,
                "uri": "",
                "place_id": "",
            }
        ]

    async def fake_converse(phone, text):
        return {
            "reply": "בודק לך",
            "ready": True,
            "task_type": "recommend",
            "category": "bar",
            "city": "Tel Aviv",
        }

    monkeypatch.setattr(pipeline, "recommend_places", slow_places)
    monkeypatch.setattr(pipeline, "converse", fake_converse)
    pipeline._last_seen["p3"] = time.time()

    async def go():
        await pipeline.handle_inbound("p3", "מה יש באיזור כיכר רבין")
        await pipeline.handle_inbound("p3", "בסגנון הגזאטה")
        for _ in range(10):
            await asyncio.sleep(0.02)
            if not pipeline._pending:
                break
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(go())
    rec_lists = [m for m in sent if m[0] == "text" and "P0" in m[1]]
    assert len(rec_lists) == 1, [m[1] for m in rec_lists]


# ─── באג 4: רשימת המתנה היא הצעה, לא "הכל מלא" ─────────────────────────────


def test_waitlist_options_offered_not_framed_full(monkeypatch, sent):
    """אופציות 'מרפסת - רשימת המתנה' → ההודעה מציפה את ה-waitlist כהצעה אמיתית
    ('להכניס אותך לרשימה'), במקום לתת למודל לנסח 'הכל מלא'."""
    _run_booking_missing(monkeypatch, "time", REAL_TIME_OPTIONS)
    out = _all_text(sent)
    assert "רשימת ההמתנה" in out or "רשימת המתנה" in out
    assert "מכניס" in out  # ההצעה להצטרף


def test_truth_note_explains_waitlist():
    """ה-truth_note של עצירת missing עם אופציות waitlist מנחה: זו הצעה, לא 'מלא'."""
    pipeline._booking["w1"] = {"state": "missing", "info": "time"}
    pipeline._await_answer["w1"] = {"fields": {}, "field": "time", "options": REAL_TIME_OPTIONS}
    note = pipeline._truth_note("w1")
    assert "רשימת ההמתנה" in note
    assert "להכניס" in note  # ההנחיה: להציג כהצעה ("להכניס אותך?"), לא כ"הכל מלא"


def test_waitlist_pick_continues_flow(monkeypatch, sent):
    """בחירת אופציית waitlist ממשיכה את הזרימה הקיימת (ירי דטרמיניסטי רגיל)."""
    pipeline._booking["p1"] = {"state": "missing", "info": "time"}
    pipeline._await_answer["p1"] = {
        "fields": {"restaurant": "הנסיך", "date": "23.07", "party_size": 4},
        "field": "time",
        "options": REAL_TIME_OPTIONS,
    }
    fired = {}

    async def fake_run(phone, fields):
        fired.update(fields)

    monkeypatch.setattr(pipeline, "run_booking", fake_run)

    async def go():
        await pipeline.handle_inbound("p1", "21:30 (מרפסת - רשימת המתנה)")
        if pipeline._pending:
            await asyncio.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(go())
    assert fired.get("time") == "21:30 (מרפסת - רשימת המתנה)"


def test_say_violations_forbid_ctx():
    """איסור per-קריאה (_forbid): waitlist קיים → 'הכל מלא' נפסל דטרמיניסטית."""
    ctx = {"_forbid": (r"הכל מלא",)}
    assert any(
        p.startswith("forbid_ctx")
        for p in pipeline._say_violations("heartbeat", ctx, "הכל מלא שם, עוד רגע איתך")
    )
    assert pipeline._say_violations("heartbeat", ctx, "עוד עובד על זה, לא נעלמתי") == []


# ─── באג 5: זיכרון "נפסלו כבר" מסנן המלצות ─────────────────────────────────


def test_rec_batch_blocks_mentioning_avoided(monkeypatch, sent):
    """eval 24.7: המודל פתח ב'עזוב אותך מהגזטה' למרות הנחיית avoid — אזכור של
    מקום שנפסל פוסל את הפלט והמאגר הבטוח נשלח במקומו."""

    async def mention(intent, ctx):
        return "עזוב אותך מהגזטה, שחרר\nTirza wine bar — אש\nCÔTE — סטייל\nלסגור לך אחת?"

    monkeypatch.setattr(pipeline, "_say_model", mention)
    batch = [
        {
            "name": "Tirza wine bar",
            "rating": 4.6,
            "reviews": 900,
            "open_now": True,
            "uri": "",
            "place_id": "",
        },
        {
            "name": "CÔTE",
            "rating": 4.5,
            "reviews": 700,
            "open_now": True,
            "uri": "",
            "place_id": "",
        },
    ]
    asyncio.run(pipeline._send_rec_batch("p10", "wine bar", batch, "הגזטה", False))
    msg = sent[-1][1]
    assert "הגזטה" not in msg and "Tirza wine bar" in msg, msg


def _fail_booking(monkeypatch, name, reason="no_online_booking"):
    async def fake_book(**kwargs):
        return ActionResult(success=False, summary=f"FAILED:{reason}", details={"failed": reason})

    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    pipeline._resolved["p5"] = {"name": name, "url": "http://x", "platform": "ontopo"}
    asyncio.run(pipeline.run_booking("p5", {"restaurant": name, "date": "מחר", "time": "20:00"}))


def test_all_rejected_places_excluded_from_recs(monkeypatch, sent):
    """שחזור החי: הגזטה נפסלה, אחריה הנסיך — ההמלצות חייבות לסנן את *שניהם*,
    לא רק את הכשל האחרון (הבאג: גבר המליץ על הגזטה אחרי שכבר נפסלה)."""
    _fail_booking(monkeypatch, "הגזטה")
    _fail_booking(monkeypatch, "הנסיך")

    async def fake_places(category, area="", constraints="", exclude=None):
        return [
            {
                "name": "Gazzetta",
                "rating": 4.6,
                "reviews": 2000,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
            {
                "name": "HaNasich",
                "rating": 4.5,
                "reviews": 1000,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
            {
                "name": "Hudson",
                "rating": 4.4,
                "reviews": 9000,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
        ]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("p5", {"task_type": "recommend", "category": "bar"}))
    rec_msg = sent[-1][1]
    assert "Gazzetta" not in rec_msg and "Hudson" in rec_msg, rec_msg


def test_rejected_persisted_and_restored():
    """רשימת הנפסלים חיה ב-_flow — שורדת redeploy כמו שאר מצב השיחה."""
    pipeline._rejected["p6"] = ["הגזטה", "הנסיך"]
    flow = {"rejected": ["הגזטה", "הנסיך"], "ts": time.time()}
    pipeline._rejected.clear()
    pipeline._restore_flow("p6", flow)
    assert pipeline._rejected.get("p6") == ["הגזטה", "הנסיך"]


def test_save_flow_includes_rejected(monkeypatch):
    saved = {}

    async def fake_get(phone):
        return None

    async def fake_upsert(phone, **kw):
        saved.update(kw.get("prefs") or {})

    monkeypatch.setattr(memory, "get_profile", fake_get)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    pipeline._rejected["p7"] = ["הגזטה"]
    asyncio.run(pipeline._save_flow("p7"))
    assert saved["_flow"]["rejected"] == ["הגזטה"]


# ─── באג 6: המלצות עוברות אימות קיום לפני שליחה ────────────────────────────


def test_unverified_recommendations_filtered(monkeypatch, sent):
    """'Château Shuál' לא עובר resolve → לא נשלח; עדיף פחות המלצות מאומתות."""

    async def fake_places(category, area="", constraints="", exclude=None):
        return [
            {
                "name": "Château Shuál",
                "rating": 4.9,
                "reviews": 5,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
            {
                "name": "Hudson",
                "rating": 4.4,
                "reviews": 9000,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
        ]

    async def fake_exists(name, area):
        return name == "Hudson"

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    monkeypatch.setattr(pipeline, "_rec_exists", fake_exists, raising=False)
    asyncio.run(
        pipeline.run_recommend(
            "p8", {"task_type": "recommend", "category": "bar", "city": "Tel Aviv"}
        )
    )
    rec_msg = sent[-1][1]
    assert "Château Shuál" not in rec_msg and "Hudson" in rec_msg, rec_msg
    # הלא-מאומת גם לא נשאר בבאפר של "עוד" ולא בהערת האמת
    assert "Château Shuál" not in pipeline._recs_shown("p8")


def test_all_unverified_falls_to_honesty(monkeypatch, sent):
    """הכל נפסל באימות → הודעת הכנות הקיימת, בלי לשלוח שמות מפוקפקים."""

    async def fake_places(category, area="", constraints="", exclude=None):
        return [
            {
                "name": "Foster Bar",
                "rating": 4.9,
                "reviews": 3,
                "open_now": True,
                "uri": "",
                "place_id": "",
            },
        ]

    async def fake_exists(name, area):
        return False

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    monkeypatch.setattr(pipeline, "_rec_exists", fake_exists, raising=False)
    asyncio.run(pipeline.run_recommend("p9", {"task_type": "recommend", "category": "bar"}))
    assert "Foster Bar" not in _all_text(sent)
    assert "?" in sent[-1][1]  # כנות + הצעת המשך


def test_rec_exists_fails_open_without_brave():
    """אין מפתח Brave / כשל רשת → לא פוסלים (אימות הוא שיפור אמון, לא שער)."""
    assert asyncio.run(pipeline._rec_exists("Hudson", "Tel Aviv")) is True


# ─── באג 7: סניטציה של שמות מועמדים (טקסט כפתור) ───────────────────────────


def test_candidate_label_strips_button_text():
    """שחזור החי: 'הכוונה ל-Book now הכוֹסית-ורמוטריה מקומית Tel Aviv-Yafo?'."""
    label = pipeline._safe_label("Book now הכוֹסית-ורמוטריה מקומית Tel Aviv-Yafo")
    assert "Book now" not in label
    assert "הכוֹסית-ורמוטריה מקומית" in label


def test_candidate_label_strips_more_button_variants():
    assert "Order online" not in pipeline._safe_label("Order online מסעדת האחים תל אביב")
    assert pipeline._safe_label("הזמינו עכשיו — נונה חיפה").strip() == "נונה חיפה"
    # שם לגיטימי שמכיל את המילה book לא נמחק
    assert pipeline._safe_label("The Book Bar Tel Aviv") == "The Book Bar Tel Aviv"
