"""פיצ'ר ההמלצות (Maps/Search grounding): הפירסור, השקלול, הניתוב, עוגני האמת
(שמות בלבד — בלי מקור, בלי לינק, בלי דירוג מספרי בהודעה; פידבק אלון), וכשל→כנות.
הכל ממוקק — אפס רשת (הקריאה החיה נבדקת בנפרד)."""

import asyncio
import os
import re
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.llm import recommend  # noqa: E402


# ── סכמה והנחיית ה-extract ──────────────────────────────────────────────────
def test_schema_has_recommend():
    assert "recommend" in pipeline._SCHEMA["properties"]["task_type"]["enum"]
    assert "category" in pipeline._SCHEMA["properties"]


def test_extract_guides_recommend():
    """ההנחיה קיימת: recommend, שדות באנגלית (מגבלת maps grounding), בלי להמליץ לבד,
    והודעת הביניים לא מסגירה איפה בודקים (בלי גוגל/מפות)."""
    assert "recommend" in pipeline._EXTRACT
    assert "באנגלית" in pipeline._EXTRACT
    assert "בלי להמליץ בעצמך" in pipeline._EXTRACT
    assert "בלי להזכיר גוגל" in pipeline._EXTRACT


# ── פירסור grounding_chunks ─────────────────────────────────────────────────
def _chunk(title, text="", uri="https://maps.google.com/?cid=1", place_id="places/x"):
    return SimpleNamespace(maps=SimpleNamespace(title=title, text=text, uri=uri, place_id=place_id))


def test_parse_maps_chunks_fields_dedupe_and_nonmaps():
    text = "**Title:** Hudson\n* **Rating:** 4.5 stars (9,287 reviews)\n* Open Now"
    places = recommend.parse_maps_chunks(
        [_chunk("Hudson", text), SimpleNamespace(maps=None), _chunk("Hudson")]
    )
    assert places == [
        {
            "name": "Hudson",
            "rating": 4.5,
            "reviews": 9287,
            "open_now": True,
            "uri": "https://maps.google.com/?cid=1",
            "place_id": "places/x",
        }
    ]


def test_parse_maps_chunks_cleans_title_junk():
    """זבל-כותרת של Maps grounding (פסיק-נקודה זנב, תו-כיווניות מוביל — נצפו חי)
    מנוקה מהשם: הוא עוגן ההזמנה ומפתח הדדופ. פיסוק פנימי/לגיטימי נשמר."""
    places = recommend.parse_maps_chunks(
        [
            _chunk("claro;", "**Rating:** 4.5 (7,441 reviews)"),
            _chunk("‎Whiskey Bar & Museum | וויסקי"),  # תו LTR מוביל
            _chunk("Frug & Co."),  # נקודה לגיטימית — נשמרת
        ]
    )
    assert [p["name"] for p in places] == [
        "claro",
        "Whiskey Bar & Museum | וויסקי",
        "Frug & Co.",
    ]


def test_parse_maps_chunks_missing_rating():
    (p,) = recommend.parse_maps_chunks([_chunk("X", "**Title:** X")])
    assert p["rating"] is None and p["reviews"] == 0 and p["open_now"] is False


# ── שקלול כמות ביקורות ──────────────────────────────────────────────────────
def _place(name, rating, reviews):
    return {
        "name": name,
        "rating": rating,
        "reviews": reviews,
        "open_now": True,
        "uri": "",
        "place_id": "",
    }


def test_rank_weighs_review_counts():
    """5.0 על 141 ביקורות לא גובר על 4.5 על 9K (דרישת העיצוב)."""
    ranked = recommend.rank([_place("few", 5.0, 141), _place("many", 4.5, 9000)])
    assert ranked[0]["name"] == "many"


def test_rank_limit_and_unrated_last():
    ps = [_place(f"p{i}", 4.0 + i / 10, 1000) for i in range(4)]
    ps.insert(0, _place("no-rating", None, 0))
    ranked = recommend.rank(ps)
    assert len(ranked) == 3
    assert [p["name"] for p in ranked] == ["p3", "p2", "p1"]  # מדורגים קודם, בסדר יורד


# ── הקריאות עצמן (מודל ממוקק) ───────────────────────────────────────────────
def test_recommend_places_parses_response(monkeypatch):
    chunks = [
        _chunk("A", "**Rating:** 4.2 (500 reviews)"),
        _chunk("B", "**Rating:** 4.6 (2,000 reviews)"),
    ]
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=chunks))]
    )
    captured = {}

    async def fake_gen(prompt, config):
        captured["prompt"] = prompt
        return resp

    monkeypatch.setattr(recommend, "_generate", fake_gen)
    items = asyncio.run(
        recommend.recommend_places("restaurant", "Ramat Hahayal, Tel Aviv", "kosher")
    )
    assert [p["name"] for p in items] == ["B", "A"]  # ממוין לפי השקלול
    assert "Ramat Hahayal" in captured["prompt"] and "kosher" in captured["prompt"]


def test_recommend_places_returns_full_ranked_list_and_excludes(monkeypatch):
    """הרשימה המלאה חוזרת (לא נקצצת ל-3 — העודף הוא הבאפר ל"עוד"), ו-exclude
    נכנס לפרומפט כדי שהסבב הבא לא יחזור על מה שהוצג."""
    chunks = [_chunk(f"P{i}", f"**Rating:** 4.{i} ({i}00 reviews)") for i in range(5)]
    resp = SimpleNamespace(
        candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=chunks))]
    )
    captured = {}

    async def fake_gen(prompt, config):
        captured["prompt"] = prompt
        return resp

    monkeypatch.setattr(recommend, "_generate", fake_gen)
    items = asyncio.run(recommend.recommend_places("restaurant", exclude=["Old1", "Old2"]))
    assert len(items) == 5  # כל המדורגים, לא רק 3
    assert "Do not include: Old1, Old2." in captured["prompt"]
    # בלי exclude — הפרומפט נקי
    asyncio.run(recommend.recommend_places("restaurant"))
    assert "Do not include" not in captured["prompt"]


def test_recommend_movies_parses_lines(monkeypatch):
    resp = SimpleNamespace(text="1. דיונה 3 | ביקורות מצוינות\nהסרט השני | מותח\nשורת זבל")

    async def fake_gen(prompt, config):
        return resp

    monkeypatch.setattr(recommend, "_generate", fake_gen)
    items = asyncio.run(recommend.recommend_movies())
    assert [p["name"] for p in items] == ["דיונה 3", "הסרט השני"]
    assert items[0]["blurb"] == "ביקורות מצוינות"


# ── run_recommend: ההודעה ללקוח ─────────────────────────────────────────────
@pytest.fixture
def _io(monkeypatch):
    sent: list[str] = []

    async def fake_send(phone, msg):
        sent.append(msg)

    async def noop(phone):
        pass

    monkeypatch.setattr(pipeline, "send_text", fake_send)
    monkeypatch.setattr(pipeline, "_persist_chat", noop)
    pipeline._recs.clear()
    pipeline._turns.clear()
    pipeline._last_out.clear()
    return sent


# רגקסי "אפס הסגרה" — מה שאסור שיופיע בהודעת המלצות (פידבק אלון: בלי גוגל,
# בלי מקור, בלי לינק, בלי דירוג בפורמט מספרי).
_LEAKS = (r"[Gg]oogle", "גוגל", r"[Mm]aps", "מפס", "מקור", r"https?://", r"\d\.\d", r"\d+ ביקורות")


def test_run_recommend_success_names_only_no_source(monkeypatch, _io):
    async def fake_places(category, area="", constraints="", exclude=None):
        return [
            _place("Hudson Brasserie", 4.5, 9287) | {"uri": "https://maps.google.com/?cid=1"},
            _place("POMO", 4.4, 3879) | {"uri": "https://maps.google.com/?cid=2"},
        ]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(
        pipeline.run_recommend(
            "r1", {"task_type": "recommend", "category": "restaurant", "city": "Ramat Hahayal"}
        )
    )
    msg = _io[0]
    # השמות מילה-במילה — הגשר ל"תסגור את הראשון"
    assert "Hudson Brasserie" in msg and "POMO" in msg
    # אפס הסגרה: בלי גוגל/מקור/לינק/דירוג מספרי (פידבק אלון)
    for leak in _LEAKS:
        assert not re.search(leak, msg), leak
    # הצעת סגירה — הגשר לזרימת ההזמנה
    assert re.search(r"סגור|סוגר", msg) and "?" in msg
    # השמות נשמרו לזיכרון הזרימה בלבד ("תסגור את הראשון")
    assert pipeline._recs_shown("r1") == ["Hudson Brasserie", "POMO"]


def test_run_recommend_movies_path(monkeypatch, _io):
    called = {}

    async def fake_movies(constraints="", exclude=None):
        called["movies"] = True
        return [_place("דיונה 3", None, 0) | {"blurb": "ביקורות מעולות"}]

    monkeypatch.setattr(pipeline, "recommend_movies", fake_movies)
    asyncio.run(pipeline.run_recommend("r2", {"task_type": "recommend", "category": "movie"}))
    assert called.get("movies")
    msg = _io[0]
    assert "דיונה 3" in msg
    # גם במסלול הסרטים — אפס הסגרה (שם הופיע "מקור: Google")
    for leak in _LEAKS:
        assert not re.search(leak, msg), leak


def test_run_recommend_failure_honest(monkeypatch, _io):
    async def boom(*a, **k):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline, "recommend_places", boom)
    asyncio.run(pipeline.run_recommend("r3", {"task_type": "recommend", "category": "restaurant"}))
    msg = _io[0]
    assert "?" in msg  # כנות + הצעת המשך, בלי המלצות מומצאות
    assert not re.search(r"\d\.\d", msg)  # אין דירוגים מומצאים
    assert "r3" not in pipeline._recs


def test_run_recommend_timeout_honest(monkeypatch, _io):
    monkeypatch.setattr(pipeline, "REC_TIMEOUT_S", 0.01)

    async def slow(*a, **k):
        await asyncio.sleep(1)

    monkeypatch.setattr(pipeline, "recommend_places", slow)
    asyncio.run(pipeline.run_recommend("r4", {"task_type": "recommend", "category": "restaurant"}))
    assert _io and "?" in _io[0]
    assert "r4" not in pipeline._recs


# ── הדרת המקום שנכשל (נצפה חי: גרקו נכשל בהזמנה וחזר כהמלצה) ────────────────
def test_failed_place_from_conversation_state():
    """failed → השם מ-_resolved (ה-info הוא סיבת הכשל); none → ה-info הוא השם;
    done/אין state → אין הדרה."""
    pipeline._booking["fx"] = {"state": "failed", "info": "המקום לא מקבל הזמנות אונליין"}
    pipeline._resolved["fx"] = {"name": "גרקו הרצליה", "url": "u", "platform": "ontopo"}
    assert pipeline._failed_place("fx") == "גרקו הרצליה"
    pipeline._booking["fx"] = {"state": "none", "info": "מסעדת הפנינה"}
    assert pipeline._failed_place("fx") == "מסעדת הפנינה"
    pipeline._booking["fx"] = {"state": "done", "info": "אישור 123"}
    assert pipeline._failed_place("fx") == ""
    pipeline._booking.pop("fx")
    pipeline._resolved.pop("fx")
    assert pipeline._failed_place("fx") == ""


def test_rec_excluded_bridges_hebrew_latin():
    """גישור תעתיק דו-כיווני (Greco↔גרקו) דרך שלד-העיצורים של ה-resolver."""
    assert pipeline._rec_excluded("Greco", "גרקו הרצליה")
    assert pipeline._rec_excluded("Greco Herzliya", "גרקו הרצליה")
    assert pipeline._rec_excluded("גרקו", "Greco Herzliya")
    assert pipeline._rec_excluded("גרקו רמת החייל", "גרקו הרצליה")  # אותו מותג, סניף אחר
    assert not pipeline._rec_excluded("Hudson Brasserie", "גרקו הרצליה")
    assert not pipeline._rec_excluded("POMO", "גרקו הרצליה")


def test_run_recommend_excludes_failed_place(monkeypatch, _io):
    """הזמנה שנכשלה על גרקו → ההמלצות שחוזרות בלי Greco, וההודעה בלעדיו."""
    pipeline._booking["r7"] = {"state": "failed", "info": "המקום לא מקבל הזמנות אונליין"}
    pipeline._resolved["r7"] = {"name": "גרקו הרצליה", "url": "u", "platform": "ontopo"}

    async def fake_places(category, area="", constraints="", exclude=None):
        return [_place("Greco", 4.6, 2000), _place("Hudson Brasserie", 4.5, 9287)]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(
        pipeline.run_recommend(
            "r7", {"task_type": "recommend", "category": "restaurant", "city": "Herzliya"}
        )
    )
    msg = _io[0]
    assert "Greco" not in msg and "Hudson Brasserie" in msg
    # רשימה של אחד אחרי סינון — עדיין מציגים; הזיכרון לזרימה בלי המקום שנכשל
    assert pipeline._recs_shown("r7") == ["Hudson Brasserie"]
    pipeline._booking.pop("r7")
    pipeline._resolved.pop("r7")


def test_run_recommend_no_failure_no_filter(monkeypatch, _io):
    """בלי כשל בשיחה (ואפילו עם _resolved ישן) — שום דבר לא מסונן."""
    pipeline._booking["r8"] = {"state": "done", "info": "אישור 123"}
    pipeline._resolved["r8"] = {"name": "גרקו הרצליה", "url": "u", "platform": "ontopo"}

    async def fake_places(category, area="", constraints="", exclude=None):
        return [_place("Greco", 4.6, 2000), _place("Hudson Brasserie", 4.5, 9287)]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("r8", {"task_type": "recommend", "category": "restaurant"}))
    assert "Greco" in _io[0]
    assert pipeline._recs_shown("r8") == ["Greco", "Hudson Brasserie"]
    pipeline._booking.pop("r8")
    pipeline._resolved.pop("r8")


def test_run_recommend_all_filtered_falls_to_honesty(monkeypatch, _io):
    """הסינון רוקן את הרשימה → הודעת הכנות הקיימת (recommend_failed), בלי המלצות."""
    pipeline._booking["r9"] = {"state": "failed", "info": "המקום לא מקבל הזמנות אונליין"}
    pipeline._resolved["r9"] = {"name": "גרקו הרצליה", "url": "u", "platform": "ontopo"}

    async def fake_places(category, area="", constraints="", exclude=None):
        return [_place("Greco", 4.6, 2000), _place("Greco Herzliya", 4.4, 500)]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("r9", {"task_type": "recommend", "category": "restaurant"}))
    assert "Greco" not in _io[0] and "?" in _io[0]
    assert "r9" not in pipeline._recs
    pipeline._booking.pop("r9")
    pipeline._resolved.pop("r9")


def test_recommend_results_goal_forbids_failed_place():
    """כרטיס הכוונה מנחה את המנסח: avoid = מקום שלא הסתדר — אסור להציע אותו."""
    card = pipeline.INTENTS["recommend_results"]
    assert "avoid" in card["goal"] and "avoid" in card["ctx"]


# ── ניתוב ב-handle_inbound ──────────────────────────────────────────────────
def test_ready_recommend_routes_without_booking_state(monkeypatch, _io):
    fired = {}

    async def fake_rec(phone, fields):
        fired["fields"] = fields

    async def fake_converse(phone, text):
        return {
            "reply": "רגע בודק לך",
            "ready": True,
            "task_type": "recommend",
            "category": "restaurant",
            "city": "Givatayim",
        }

    async def fake_typing(mid):
        pass

    monkeypatch.setattr(pipeline, "run_recommend", fake_rec)
    monkeypatch.setattr(pipeline, "converse", fake_converse)
    monkeypatch.setattr(pipeline, "send_typing", fake_typing)
    pipeline._booking.pop("r5", None)
    pipeline._last_seen["r5"] = time.time()  # לא מגע ראשון — בלי אונבורדינג
    pipeline._pending_commit["r5"] = {"restaurant": "X"}  # gate פתוח — המלצה לא נוטשת אותו

    async def go():
        await pipeline.handle_inbound("r5", "תמליץ לי מסעדה טובה בגבעתיים")
        for _ in range(3):
            await asyncio.sleep(0)
            if pipeline._pending:
                await asyncio.gather(*list(pipeline._pending), return_exceptions=True)

    asyncio.run(go())
    assert fired["fields"]["category"] == "restaurant"
    assert "r5" in pipeline._pending_commit  # ההזמנה הממתינה שרדה את בקשת ההמלצה
    assert "r5" not in pipeline._booking  # המלצה לא נועלת state של הזמנה
    del pipeline._pending_commit["r5"]


# ── אמת-הקרקע להמשך השיחה ("תסגור את הראשון") ───────────────────────────────
def test_recs_note_lists_names_and_bridges_to_booking():
    pipeline._recs["r6"] = {
        "items": [_place("Hudson Brasserie", 4.5, 9287), _place("POMO", 4.4, 3879)],
        "shown": 2,
        "key": ("restaurant", "", ""),
    }
    note = pipeline._recs_note("r6")
    assert "Hudson Brasserie" in note and "POMO" in note
    assert "אל תמליץ" in note  # לא ממציאים מקומות מעבר לרשימה
    assert "restaurant" in note  # ההנחיה לגשר לבקשת הזמנה רגילה
    assert "עוד" in note and "recommend" in note  # "מה עוד יש?" → שוב recommend, לא "אין עוד"
    assert pipeline._recs_note("nobody") == ""
    pipeline._recs.clear()


def test_recs_note_lists_only_shown_names():
    """הבאפר מחזיק את כולם, אבל הלקוח ראה רק את המוצגים — רק הם ברי-בחירה בהערה."""
    pipeline._recs["r6"] = {
        "items": [_place("A", 4.6, 100), _place("B", 4.5, 100), _place("C", 4.4, 100)],
        "shown": 2,
        "key": ("restaurant", "", ""),
    }
    note = pipeline._recs_note("r6")
    assert "A" in note and "B" in note and "C" not in note
    pipeline._recs.clear()


# ── "מה עוד יש?" — הבאפר המלא והסבב הבא ─────────────────────────────────────
_FIELDS = {"task_type": "recommend", "category": "restaurant", "city": "Givatayim"}


def _five_places():
    return [_place(f"P{i}", 4.9 - i / 10, 1000) for i in range(5)]  # P0 הכי גבוה


def test_run_recommend_more_serves_buffer_without_new_call(monkeypatch, _io):
    """5 מהמדורגים → 3 מוצגים והשאר בבאפר; אותה בקשה שוב ("עוד") מגישה את הבאות
    בתור בלי קריאת grounding שנייה, וכל מה שהוצג אי-פעם נשאר בר-בחירה."""
    calls = []

    async def fake_places(category, area="", constraints="", exclude=None):
        calls.append(exclude)
        return _five_places()

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("m1", _FIELDS))
    assert "P0" in _io[0] and "P2" in _io[0] and "P3" not in _io[0]
    assert pipeline._recs_shown("m1") == ["P0", "P1", "P2"]

    asyncio.run(pipeline.run_recommend("m1", _FIELDS))  # "מה עוד יש?"
    assert len(calls) == 1  # בלי קריאה חדשה — מהבאפר
    assert "P3" in _io[1] and "P4" in _io[1] and "P0" not in _io[1]
    # הבחירה "תסגור את השני מהרשימה הקודמת" — כל המוצגים אי-פעם בהערת האמת
    assert pipeline._recs_shown("m1") == ["P0", "P1", "P2", "P3", "P4"]
    note = pipeline._recs_note("m1")
    assert "P1" in note and "P4" in note


def test_run_recommend_more_exhausted_calls_again_with_exclude(monkeypatch, _io):
    """הבאפר נגמר → קריאת grounding אחת עם exclude של מה שהוצג, וכפילויות שחזרו
    בכל זאת מסוננות דטרמיניסטית."""
    calls = []

    async def fake_places(category, area="", constraints="", exclude=None):
        calls.append(exclude)
        if exclude:  # הסבב השני — המודל החזיר גם כפילות אחת למרות הבקשה
            return [_place("P0", 4.9, 1000), _place("New1", 4.3, 800), _place("New2", 4.2, 700)]
        return [_place(f"P{i}", 4.9 - i / 10, 1000) for i in range(3)]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("m2", _FIELDS))
    asyncio.run(pipeline.run_recommend("m2", _FIELDS))  # באפר ריק → קריאה עם exclude
    assert calls == [None, ["P0", "P1", "P2"]]
    assert "New1" in _io[1] and "New2" in _io[1] and "P0" not in _io[1]
    assert pipeline._recs_shown("m2") == ["P0", "P1", "P2", "New1", "New2"]


def test_run_recommend_more_exhausted_and_empty_falls_to_honesty(monkeypatch, _io):
    """נגמר הבאפר וגם הקריאה עם exclude חזרה ריקה/כפולה בלבד → הודעת הכנות."""

    async def fake_places(category, area="", constraints="", exclude=None):
        return [_place("P0", 4.9, 1000)]  # תמיד אותו מקום

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("m3", _FIELDS))
    asyncio.run(pipeline.run_recommend("m3", _FIELDS))
    assert "?" in _io[1] and "P0" not in _io[1]  # כנות, בלי לחזור על מה שכבר הוצג
    assert pipeline._recs_shown("m3") == ["P0"]  # המוצג נשאר בר-בחירה


def test_run_recommend_new_request_resets_buffer(monkeypatch, _io):
    """בקשה שונה (קטגוריה/עיר אחרת) היא לא "עוד" — קריאה טרייה בלי exclude
    והבאפר מוחלף."""
    calls = []

    async def fake_places(category, area="", constraints="", exclude=None):
        calls.append((category, exclude))
        return [_place("Sushi1", 4.7, 500)] if category == "sushi" else _five_places()

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("m4", _FIELDS))
    asyncio.run(
        pipeline.run_recommend(
            "m4", {"task_type": "recommend", "category": "sushi", "city": "Givatayim"}
        )
    )
    assert calls == [("restaurant", None), ("sushi", None)]
    assert pipeline._recs_shown("m4") == ["Sushi1"]


def test_run_recommend_more_buffer_respects_failed_place(monkeypatch, _io):
    """מקום שנכשל בין הסבבים לא מוגש מהבאפר ב"עוד" (אותה הדרה כמו בסבב ראשון)."""

    async def fake_places(category, area="", constraints="", exclude=None):
        return _five_places() + [_place("Greco", 4.0, 100)]

    monkeypatch.setattr(pipeline, "recommend_places", fake_places)
    asyncio.run(pipeline.run_recommend("m5", _FIELDS))
    pipeline._booking["m5"] = {"state": "failed", "info": "המקום לא מקבל הזמנות אונליין"}
    pipeline._resolved["m5"] = {"name": "Greco", "url": "u", "platform": "ontopo"}
    asyncio.run(pipeline.run_recommend("m5", _FIELDS))  # "עוד" — Greco בבאפר אך מודר
    assert "Greco" not in _io[1] and "P3" in _io[1] and "P4" in _io[1]
    pipeline._booking.pop("m5")
    pipeline._resolved.pop("m5")


def test_recommend_results_goal_supports_more():
    """כרטיס ההכוונה: more בהקשר, ואסור לטעון שאין עוד כשיש באפר."""
    card = pipeline.INTENTS["recommend_results"]
    assert "more" in card["ctx"] and "more" in card["goal"]
    assert "אין עוד" in card["goal"]  # ההנחיה "אל תטען ש...אין עוד"


# ── הוולידטור: איסורים ועוגנים של הכוונה החדשה ──────────────────────────────
def test_recommend_results_validator():
    ctx = {"place1": "Hudson", "place2": "POMO", "info1": "מדורג 4.5 על סמך 9,287 ביקורות"}
    good = (
        "יש לי שניים ששווים\nHudson — מדורג חזק וכולם מדברים עליו\n"
        "POMO — איטלקי שרץ חזק באזור\nלסגור לך אחת מהם?"
    )
    assert pipeline._say_violations("recommend_results", ctx, good) == []
    # "הזמנתי" בשלב ההמלצה = הכרזת ביצוע שקרית
    bad = "הזמנתי לך ב-Hudson\nPOMO גם שווה\nלסגור?"
    assert any(
        p.startswith("forbid") for p in pipeline._say_violations("recommend_results", ctx, bad)
    )
    # שם מקום שהושמט — פסילה (עוגן האמת שמזרים את הבחירה להזמנה)
    no_name = "Hudson מדורג חזק ויש עוד אחד\nלסגור לך?"
    assert "missing_ctx:place2" in pipeline._say_violations("recommend_results", ctx, no_name)


def test_recommend_results_validator_blocks_source_and_numbers():
    """פידבק אלון: גוגל/מפס/מקור/לינק/דירוג מספרי — פסילה דטרמיניסטית."""
    ctx = {"place1": "Hudson", "place2": "POMO"}
    for leak in (
        "בדקתי לך בגוגל מפס — Hudson וגם POMO\nלסגור לך?",
        "עברתי על Google Maps\nHudson\nPOMO\nלסגור?",
        "Hudson — 4.5 (9,287 ביקורות)\nPOMO\nלסגור לך?",
        "Hudson עם 9,287 ביקורות\nPOMO\nלסגור לך?",
        "מקור: Google Maps\nHudson\nPOMO\nלסגור?",
        "Hudson\nPOMO\nhttps://maps.google.com/?cid=1\nלסגור לך?",
    ):
        probs = pipeline._say_violations("recommend_results", ctx, leak)
        assert any(p.startswith("forbid") for p in probs), leak
    # "מפסיקים" זו לא הסגרת מפס — הרגקס תחום מילה
    ok = "Hudson — לא מפסיקים לדבר עליו\nPOMO — קלאסיקה\nלסגור לך אחת מהם?"
    assert pipeline._say_violations("recommend_results", ctx, ok) == []
