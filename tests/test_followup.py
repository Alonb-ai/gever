"""פיצ'ר הפולו-אפ אחרי סגירה אמיתית: חישוב הזמנים (arrival 5-15 דק', feedback
~4 שעות עם גלגול-לבוקר), גארד חלון 24 השעות של WhatsApp, חימוש רק על commit
אמיתי, לולאת הרקע, קליטת המשוב ב-converse, הדרה/קידום בהמלצות, וניקוי בביטול.
הכל ממוקק — אפס רשת; _say נופל דטרמיניסטית למאגרים (conftest)."""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

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
    pipeline._resume.clear()
    pipeline._resolved.clear()
    pipeline._pending_pick.clear()
    pipeline._await_answer.clear()
    pipeline._recs.clear()
    pipeline._last_out.clear()


def _ts(*args) -> float:
    return datetime(*args, tzinfo=pipeline._IL_TZ).timestamp()


# ── חישוב הזמנים ─────────────────────────────────────────────────────────────
def test_followup_times_arrival_and_feedback_windows():
    """arrival בטווח 5-15 דק' אחרי שעת ההזמנה; feedback בדיוק +4 שעות כשזה ביום."""
    now = _ts(2026, 7, 20, 12, 0)
    start = _ts(2026, 7, 21, 17, 0)
    arrival, feedback = pipeline._followup_times("21.07", "17:00", now=now)
    assert start + 5 * 60 <= arrival <= start + 15 * 60
    assert feedback == start + 4 * 3600  # 21:00 — לפני קאטאוף הלילה


def _tod(ts: float) -> int:
    dt = datetime.fromtimestamp(ts, tz=pipeline._IL_TZ)
    return dt.hour * 3600 + dt.minute * 60


def test_followup_times_night_rolls_to_next_morning():
    """feedback שנופל אחרי 22:30 (הזמנה 19:00 → 23:00) → למחרת ב-10:30-12:00."""
    now = _ts(2026, 7, 20, 12, 0)
    _, feedback = pipeline._followup_times("21.7", "19:00", now=now)
    dt = datetime.fromtimestamp(feedback, tz=pipeline._IL_TZ)
    assert (dt.day, dt.month) == (22, 7)  # למחרת ההזמנה
    assert pipeline.MORNING_START_S <= _tod(feedback) <= pipeline.MORNING_END_S


def test_followup_times_after_midnight_rolls_to_morning():
    """feedback שנופל בלילה אחרי חצות (הזמנה 21:30 → 01:30) → בוקר אותו יום קלנדרי."""
    now = _ts(2026, 7, 20, 12, 0)
    _, feedback = pipeline._followup_times("21.7", "21:30", now=now)
    dt = datetime.fromtimestamp(feedback, tz=pipeline._IL_TZ)
    assert (dt.day, dt.month) == (22, 7)  # 01:30 של ה-22.7 → הבוקר של ה-22.7
    assert pipeline.MORNING_START_S <= _tod(feedback) <= pipeline.MORNING_END_S


def test_followup_times_unparseable_returns_none():
    """ "מחר"/"בערב" — בלי מועד מדויק אין פולו-אפ (שמרני)."""
    now = _ts(2026, 7, 20, 12, 0)
    assert pipeline._followup_times("מחר", "20:00", now=now) is None
    assert pipeline._followup_times("21.7", "בערב", now=now) is None
    assert pipeline._followup_times("", "", now=now) is None
    assert pipeline._followup_times("31.02", "20:00", now=now) is None  # תאריך לא קיים


def test_followup_times_year_rollover():
    """תאריך בלי שנה שכבר עבר מזמן (02.01 בסוף דצמבר) → השנה הבאה, לא העבר."""
    now = _ts(2026, 12, 30, 12, 0)
    arrival, _ = pipeline._followup_times("02.01", "20:00", now=now)
    assert datetime.fromtimestamp(arrival, tz=pipeline._IL_TZ).year == 2027


def test_booking_start_same_day_not_bumped():
    """הזמנה מוקדם יותר היום (פער < יום) לא נזרקת לשנה הבאה."""
    now_dt = datetime(2026, 7, 20, 21, 0, tzinfo=pipeline._IL_TZ)
    start = pipeline._booking_start("20.7", "19:00", now_dt)
    assert start.year == 2026 and start.day == 20


# ── גארד חלון 24 השעות ───────────────────────────────────────────────────────
def test_last_user_ts_prefers_hot_memory_and_falls_back_to_prefs():
    _reset()
    t0 = time.time() - 50
    pipeline._turns["p1"] = [
        {"role": "user", "text": "הי", "ts": t0},
        {"role": "model", "text": "אהלן", "ts": t0 + 1},
    ]
    assert pipeline._last_user_ts("p1", {}) == t0
    # זיכרון חם ריק (restart) → prefs._chat
    prefs = {"_chat": {"turns": [{"role": "user", "text": "הי", "ts": 123.0}]}}
    assert pipeline._last_user_ts("p2", prefs) == 123.0
    # אין עדות בכלל → 0 (מחוץ לחלון — לא שולחים)
    assert pipeline._last_user_ts("p3", {}) == 0.0


def test_send_followup_outside_window_skips_silently(monkeypatch):
    """הלקוח שתק >23 שעות → אין הודעה יזומה (מגבלת Meta) — דילוג שקט."""
    _reset()
    sent = []

    async def fake_send(phone, msg):
        sent.append(msg)

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    old = {"_chat": {"turns": [{"role": "user", "text": "הי", "ts": time.time() - 24 * 3600}]}}
    asyncio.run(pipeline._send_followup("p1", {"kind": "arrival", "place": "הדסון"}, old))
    assert sent == []


def test_send_followup_arrival_inside_window(monkeypatch):
    _reset()
    sent = []

    async def fake_send(phone, msg):
        sent.append(msg)

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    pipeline._turns["p1"] = [{"role": "user", "text": "הי", "ts": time.time() - 60}]
    asyncio.run(pipeline._send_followup("p1", {"kind": "arrival", "place": "הדסון"}, {}))
    assert len(sent) == 1 and "?" in sent[0]  # צ'ק-אין תמיד שואל


def test_send_followup_feedback_sets_awaiting_flag(monkeypatch):
    """פולו-אפ feedback: הדגל נכתב *לפני* ההודעה, וההודעה נוקבת במקום ושואלת."""
    _reset()
    sent, flags = [], []

    async def fake_send(phone, msg):
        sent.append(msg)

    async def fake_set_pref(phone, key, value):
        flags.append((key, value))

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    pipeline._turns["p1"] = [{"role": "user", "text": "הי", "ts": time.time() - 60}]
    asyncio.run(
        pipeline._send_followup("p1", {"kind": "feedback", "place": "הדסון", "date": "19.07"}, {})
    )
    assert flags == [("_awaiting_feedback", {"place": "הדסון", "date": "19.07"})]
    assert len(sent) == 1 and "הדסון" in sent[0] and "?" in sent[0]


# ── חימוש ולולאת הרקע ────────────────────────────────────────────────────────
def test_arm_followups_writes_both_kinds(monkeypatch):
    _reset()
    written = []

    async def fake_set_pref(phone, key, value):
        written.append((phone, key, value))

    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    tomorrow = (datetime.now(pipeline._IL_TZ) + timedelta(days=1)).strftime("%d.%m")
    asyncio.run(pipeline._arm_followups("p1", "הדסון", tomorrow, "20:00"))
    assert len(written) == 1
    phone, key, items = written[0]
    assert (phone, key) == ("p1", "_followups")
    assert [f["kind"] for f in items] == ["arrival", "feedback"]
    assert all(f["place"] == "הדסון" and f["due"] > time.time() for f in items)


def test_arm_followups_unparseable_date_noop(monkeypatch):
    _reset()
    written = []

    async def fake_set_pref(phone, key, value):
        written.append(value)

    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    asyncio.run(pipeline._arm_followups("p1", "הדסון", "מחר", "20:00"))
    assert written == []


def test_commit_success_arms_followups(monkeypatch):
    """סגירה אמיתית (run_commit success) → הפולו-אפים נחמשים; זה הטריגר היחיד."""
    _reset()
    sent, written = [], []

    async def fake_send(phone, msg):
        sent.append(msg)

    async def fake_book(**kwargs):
        return ActionResult(success=True, summary="בוצע", details={"confirmation": "AB1"})

    async def fake_log(*a, **k):
        pass

    async def fake_set_pref(phone, key, value):
        written.append((key, value))

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    tomorrow = (datetime.now(pipeline._IL_TZ) + timedelta(days=1)).strftime("%d.%m")
    pipeline._pending_commit["p1"] = {
        "restaurant": "הדסון",
        "page_url": "http://x",
        "date": tomorrow,
        "time": "20:00",
        "party_size": 4,
        "name": "אלון",
    }
    asyncio.run(pipeline.run_commit("p1"))
    followups = [v for k, v in written if k == "_followups"]
    assert followups and [f["kind"] for f in followups[0]] == ["arrival", "feedback"]


def test_commit_insurance_no_followups(monkeypatch):
    """ביטוח: אין לאן "להגיע" — לא מחמשים פולו-אפ."""
    _reset()
    written = []

    async def fake_send(phone, msg):
        pass

    async def fake_book(**kwargs):
        return ActionResult(success=True, summary="בוצע", details={})

    async def fake_log(*a, **k):
        pass

    async def fake_set_pref(phone, key, value):
        written.append(key)

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(pipeline, "book_table_bu", fake_book)
    monkeypatch.setattr(memory, "log_booking", fake_log)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    pipeline._pending_commit["p1"] = {
        "restaurant": "ביטוח נסיעות ליוון",
        "page_url": "http://x",
        "date": "21.07",
        "time": "20:00",
        "party_size": 1,
        "name": "אלון",
        "task_type": "insurance",
    }
    asyncio.run(pipeline.run_commit("p1"))
    assert "_followups" not in written


def test_followup_tick_sends_due_and_persists_rest(monkeypatch):
    """רק מה שהגיע זמנו נשלח; היתרה נכתבת חזרה ל-DB *לפני* השליחה."""
    _reset()
    sent, written = [], []
    now = time.time()

    async def fake_list():
        return [
            {
                "phone": "p1",
                "prefs": {
                    "_followups": [
                        {"due": now - 5, "kind": "arrival", "place": "הדסון", "date": "20.07"},
                        {"due": now + 9999, "kind": "feedback", "place": "הדסון", "date": "20.07"},
                    ]
                },
            }
        ]

    async def fake_set_pref(phone, key, value):
        written.append((key, value))

    async def fake_send(phone, msg):
        sent.append(msg)

    monkeypatch.setattr(memory, "list_followups", fake_list)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    monkeypatch.setattr(pipeline, "send_text", fake_send)
    pipeline._turns["p1"] = [{"role": "user", "text": "הי", "ts": now - 60}]
    asyncio.run(pipeline._followup_tick())
    assert len(sent) == 1  # רק ה-arrival שבשל
    assert written and written[0][0] == "_followups"
    assert [f["kind"] for f in written[0][1]] == ["feedback"]  # העתידי נשאר


def test_followup_tick_nothing_due_no_write(monkeypatch):
    _reset()
    written = []

    async def fake_list():
        return [
            {
                "phone": "p1",
                "prefs": {"_followups": [{"due": time.time() + 999, "kind": "arrival"}]},
            }
        ]

    async def fake_set_pref(phone, key, value):
        written.append(key)

    monkeypatch.setattr(memory, "list_followups", fake_list)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    asyncio.run(pipeline._followup_tick())
    assert written == []


def test_followup_tick_last_item_clears_key(monkeypatch):
    """הפריט האחרון נשלח → המפתח נמחק (None), לא נשארת רשימה ריקה ב-DB."""
    _reset()
    written = []
    now = time.time()

    async def fake_list():
        return [
            {
                "phone": "p1",
                "prefs": {
                    "_followups": [
                        {"due": now - 5, "kind": "arrival", "place": "הדסון", "date": "20.07"}
                    ]
                },
            }
        ]

    async def fake_set_pref(phone, key, value):
        written.append((key, value))

    async def fake_send(phone, msg):
        pass

    monkeypatch.setattr(memory, "list_followups", fake_list)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    monkeypatch.setattr(pipeline, "send_text", fake_send)
    pipeline._turns["p1"] = [{"role": "user", "text": "הי", "ts": now - 60}]
    asyncio.run(pipeline._followup_tick())
    assert ("_followups", None) in written


# ── קליטת המשוב ב-converse ───────────────────────────────────────────────────
def _fake_chat(result: dict):
    return SimpleNamespace(send_message=lambda text: SimpleNamespace(text=json.dumps(result)))


def test_converse_folds_feedback_into_prefs(monkeypatch):
    """מחכים למשוב + המודל סימן liked → prefs.feedback נכתב והדגל יורד, upsert אחד."""
    _reset()
    upserts = []
    prefs_in = {"_awaiting_feedback": {"place": "הדסון", "date": "19.07"}, "gender": "male"}
    result = {"reply": "יפה", "feedback_sentiment": "liked", "feedback_note": "היה מעולה"}

    async def fake_chat_for(phone):
        return _fake_chat(result), [], prefs_in

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(pipeline, "_chat_for", fake_chat_for)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    asyncio.run(pipeline.converse("p1", "היה מעולה"))
    (prefs_out,) = upserts
    assert prefs_out["feedback"]["הדסון"] == {"score": 1, "note": "היה מעולה", "date": "19.07"}
    assert "_awaiting_feedback" not in prefs_out
    assert prefs_out["gender"] == "male"  # שאר ה-prefs לא נדרסים


def test_converse_disliked_negative_score(monkeypatch):
    _reset()
    upserts = []
    prefs_in = {"_awaiting_feedback": {"place": "הדסון", "date": "19.07"}}
    result = {"reply": "חבל", "feedback_sentiment": "disliked", "feedback_note": "אכזבה"}

    async def fake_chat_for(phone):
        return _fake_chat(result), [], prefs_in

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(pipeline, "_chat_for", fake_chat_for)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    asyncio.run(pipeline.converse("p1", "היה גרוע"))
    assert upserts[0]["feedback"]["הדסון"]["score"] == -1


def test_converse_no_sentiment_keeps_flag(monkeypatch):
    """הלקוח ענה על משהו אחר (אין סנטימנט) → הדגל נשאר, אין feedback."""
    _reset()
    upserts = []
    prefs_in = {"_awaiting_feedback": {"place": "הדסון", "date": "19.07"}}

    async def fake_chat_for(phone):
        return _fake_chat({"reply": "בטח"}), [], prefs_in

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(pipeline, "_chat_for", fake_chat_for)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    asyncio.run(pipeline.converse("p1", "תזמין לי סושי מחר"))
    assert "feedback" not in upserts[0]
    assert upserts[0]["_awaiting_feedback"]["place"] == "הדסון"


def test_feedback_note_only_when_awaiting():
    note = pipeline._feedback_note({"_awaiting_feedback": {"place": "הדסון"}})
    assert "הדסון" in note and "feedback_sentiment" in note and "[אמת-למערכת" in note
    assert pipeline._feedback_note({}) == ""
    assert pipeline._feedback_note({"_awaiting_feedback": {}}) == ""


def test_schema_has_feedback_fields():
    props = pipeline._SCHEMA["properties"]
    assert props["feedback_sentiment"]["enum"] == ["liked", "disliked", "neutral"]
    assert "feedback_note" in props
    # לא ב-required — המודל נוגע בהם רק כש-_feedback_note מנחה
    assert "feedback_sentiment" not in pipeline._SCHEMA["required"]


# ── השפעה על המלצות ──────────────────────────────────────────────────────────
def _rec_setup(monkeypatch, feedback: dict, names: list[str]):
    _reset()
    sent = []

    async def fake_send(phone, msg):
        sent.append(msg)

    async def fake_get_profile(phone):
        return {"phone": phone, "prefs": {"feedback": feedback}}

    async def fake_places(category, area, constraints, exclude=None):
        return [{"name": n, "rating": 4.5, "reviews": 100, "open_now": True} for n in names]

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    return sent


def test_recommend_excludes_disliked(monkeypatch):
    sent = _rec_setup(
        monkeypatch,
        {"בורגר שוק": {"score": -1, "note": "", "date": ""}},
        ["בורגר שוק", "מיזנון", "הדסון", "פורט סעיד"],
    )
    asyncio.run(pipeline.run_recommend("p1", {"category": "restaurant", "city": "tlv"}))
    names = [p["name"] for p in pipeline._recs["p1"]["items"]]
    assert "בורגר שוק" not in names
    assert sent and "בורגר שוק" not in sent[0]


def test_recommend_promotes_liked_first(monkeypatch):
    sent = _rec_setup(
        monkeypatch,
        {"הדסון": {"score": 1, "note": "מעולה", "date": ""}},
        ["מיזנון", "פורט סעיד", "הדסון"],
    )
    asyncio.run(pipeline.run_recommend("p1", {"category": "restaurant", "city": "tlv"}))
    names = [p["name"] for p in pipeline._recs["p1"]["items"]]
    assert names[0] == "הדסון"  # האהוב עולה לראש
    assert names[1:] == ["מיזנון", "פורט סעיד"]  # sort יציב — השאר בסדרם
    assert sent and "הדסון" in sent[0]


def test_recommend_neutral_score_untouched(monkeypatch):
    _rec_setup(
        monkeypatch,
        {"מיזנון": {"score": 0, "note": "", "date": ""}},
        ["מיזנון", "הדסון"],
    )
    asyncio.run(pipeline.run_recommend("p1", {"category": "restaurant", "city": "tlv"}))
    names = [p["name"] for p in pipeline._recs["p1"]["items"]]
    assert names == ["מיזנון", "הדסון"]  # neutral לא מדיר ולא מקדם


# ── ביטול ────────────────────────────────────────────────────────────────────
def test_cancel_message_clears_followups(monkeypatch):
    """ "תבטל את ההזמנה" → prefs._followups נמחק; השיחה ממשיכה כרגיל."""
    _reset()
    cleared, sent = [], []

    async def fake_converse(phone, text):
        return {"reply": "בוטל"}

    async def fake_send(phone, msg):
        sent.append(msg)

    async def fake_set_pref(phone, key, value):
        cleared.append((phone, key, value))

    spawned = []

    def fake_spawn(coro):
        spawned.append(coro)  # מריצים בתוך אותו event loop בסוף התור

    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(pipeline, "_spawn", fake_spawn)
    monkeypatch.setattr(memory, "set_pref", fake_set_pref)
    pipeline._last_seen["p1"] = time.time()  # לא מגע ראשון

    async def run():
        await pipeline._handle_inbound_inner("p1", "תבטל את ההזמנה שלי")
        for coro in spawned:
            await coro

    asyncio.run(run())
    assert ("p1", "_followups", None) in cleared


def test_cancel_regex_scope():
    assert not pipeline._CANCEL_RE.search("תזמין לי שולחן להערב")
    assert pipeline._CANCEL_RE.search("ההזמנה התבטלה לצערי")
    assert pipeline._CANCEL_RE.search("ביטלתי את ההזמנה")


# ── memory.set_pref / list_followups ─────────────────────────────────────────
def test_set_pref_gated_noop():
    """בלי מפתחות Supabase — no-op שקט (conftest מאפס את המפתחות)."""
    asyncio.run(memory.set_pref("p1", "_followups", [{"due": 1}]))  # לא זורק


def test_set_pref_merges_and_deletes(monkeypatch):
    upserts = []

    def fake_enabled():
        return True

    async def fake_get_profile(phone):
        return {"phone": phone, "prefs": {"a": 1, "_followups": [{"due": 1}]}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(memory, "_enabled", fake_enabled)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    asyncio.run(memory.set_pref("p1", "b", 2))
    assert upserts[-1] == {"a": 1, "_followups": [{"due": 1}], "b": 2}
    asyncio.run(memory.set_pref("p1", "_followups", None))
    assert upserts[-1] == {"a": 1}  # המפתח נמחק, השאר נשמר


def test_set_pref_delete_absent_key_skips_write(monkeypatch):
    upserts = []

    def fake_enabled():
        return True

    async def fake_get_profile(phone):
        return {"phone": phone, "prefs": {"a": 1}}

    async def fake_upsert(phone, name=None, email=None, prefs=None):
        upserts.append(prefs)

    monkeypatch.setattr(memory, "_enabled", fake_enabled)
    monkeypatch.setattr(memory, "get_profile", fake_get_profile)
    monkeypatch.setattr(memory, "upsert_profile", fake_upsert)
    asyncio.run(memory.set_pref("p1", "_followups", None))
    assert upserts == []


def test_list_followups_gated_empty():
    assert asyncio.run(memory.list_followups()) == []


# ── כרטיסי הכוונות ───────────────────────────────────────────────────────────
def test_followup_intents_registered():
    for intent in ("arrival_check", "visit_feedback"):
        card = pipeline.INTENTS[intent]
        assert r"\?" in card["must"]  # פולו-אפ תמיד שואל
        assert card["fallback"] is None  # המאגרים inline באתר הקריאה
    assert "place" in pipeline.INTENTS["visit_feedback"]["must_ctx"]
