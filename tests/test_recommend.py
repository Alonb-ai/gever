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
    async def fake_places(category, area="", constraints=""):
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
    assert pipeline._recs["r1"] == ["Hudson Brasserie", "POMO"]


def test_run_recommend_movies_path(monkeypatch, _io):
    called = {}

    async def fake_movies(constraints=""):
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
    pipeline._recs["r6"] = ["Hudson Brasserie", "POMO"]
    note = pipeline._recs_note("r6")
    assert "Hudson Brasserie" in note and "POMO" in note
    assert "אל תמליץ" in note  # לא ממציאים מקומות מעבר לרשימה
    assert "restaurant" in note  # ההנחיה לגשר לבקשת הזמנה רגילה
    assert pipeline._recs_note("nobody") == ""
    pipeline._recs.clear()


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
