"""קטלוג ההופעות הפנימי: פירסור לאן (__NEXT_DATA__) וקופת (גריד דף הבית),
cache+כשל-שקט, סקירת recommend_shows, ושלב-1 הפנימי ב-resolve_event_url.
המבנים בפיקסצ'רות משקפים את מה שנצפה חי במחקר 20.7. אפס רשת."""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import pipeline  # noqa: E402
from app.automation import resolve, shows_catalog  # noqa: E402

_DAY = 86400
_FUTURE = time.time() + 30 * _DAY
_PAST = time.time() - 30 * _DAY


# ── פיקסצ'רות (מבנה אמיתי, נצפה חי 20.7) ────────────────────────────────────
def _leaan_event(name, event_id, ts, venue, city, active=True, category="מוזיקה"):
    return {
        "id": event_id,
        "name": name,
        "event_name": name,
        "active": active,
        "event_start": ts,
        "location": {"name": venue, "city": city, "country": "IL"},
        "categories": {"3": {"category_id": "3", "category_name": category}},
        "starting_price": 220,
    }


def _leaan_html(events):
    state = {"props": {"pageProps": {"initialState": {"search": {"events": events}}}}}
    return (
        "<html><head></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(state, ensure_ascii=False)
        + "</script></body></html>"
    )


# מבנה ה-article האמיתי מדף הבית של קופת (מקוצר). הבאנר הראשון — article עם
# aria-label אתרי ("קופת תל אביב +") בלי לינק מופע: ב-smoke החי (20.7) regex
# חוצה-articles נתן לו את הלינק של שלמה ארצי ובלע את הרשומה האמיתית.
_KUPAT_HTML = """
<article role="banner" aria-label="קופת תל אביב +"><div>באנר בלי לינק מופע</div></article>
<article role="link" id="show-1" class="item-show" aria-label="שלמה ארצי ">
  <div><a class="item_link" href="https://www.kupat.co.il/show/shlomo-artzi">שלמה ארצי</a></div>
</article>
<article role="link" id="show-9801" class="item-show" aria-label="אייל גולן ">
  <div><a class="item_link" href="https://www.kupat.co.il/show/eyalgolan">אייל גולן</a></div>
</article>
<article role="link" id="show-9802" class="item-show" aria-label="ארנה פארק &#8211; קופת ירושלים">
  <div><a class="item_link" href="https://www.kupat.co.il/show/arena-park-jer">ארנה פארק</a></div>
</article>
<article role="link" id="show-9801b" class="item-show" aria-label="אייל גולן ">
  <div><a class="item_link" href="https://www.kupat.co.il/show/eyalgolan">אייל גולן</a></div>
</article>
"""


def _fake_get(pages):
    async def get(url):
        return pages[url]

    return get


def _use_sources(monkeypatch, *sources):
    monkeypatch.setattr(shows_catalog, "_SOURCES", sources)


# ── לאן: __NEXT_DATA__ ──────────────────────────────────────────────────────
def test_leaan_parses_upcoming_only(monkeypatch):
    """פעיל+עתידי נכנס; עבר/לא-פעיל בחוץ. URL נבנה משם-במקפים + id (ה-id מנתב)."""
    html = _leaan_html(
        [
            _leaan_event("ליאת בנאי", 6809, _FUTURE, "רידינג 3", "תל אביב"),
            _leaan_event("מופע שעבר", 1, _PAST, "היכל", "חיפה"),
            _leaan_event("לא פעיל", 2, _FUTURE, "היכל", "חיפה", active=False),
        ]
    )
    monkeypatch.setattr(shows_catalog, "_get", _fake_get({shows_catalog._LEAAN_HOME: html}))
    items = asyncio.run(shows_catalog._leaan())
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "ליאת בנאי"
    assert it["venue"] == "רידינג 3" and it["city"] == "תל אביב"
    assert it["url"] == "https://www.leaan.co.il/events/ליאת-בנאי/6809"
    assert it["platform"] == "leaan" and it["category"] == "מוזיקה"
    assert it["ts"] == _FUTURE and it["date"]
    # ה-URL מהקטלוג חייב להתאים ל-regex של _EVENT_PLATFORMS (dedup/קנוניזציה)
    leaan_re = resolve._EVENT_PLATFORMS[0][1]
    assert leaan_re.search(it["url"])


def test_leaan_no_next_data_is_empty(monkeypatch):
    monkeypatch.setattr(
        shows_catalog, "_get", _fake_get({shows_catalog._LEAAN_HOME: "<html>ריק</html>"})
    )
    assert asyncio.run(shows_catalog._leaan()) == []


def test_he_date_format():
    """תאריך טקסטואלי ("25 באוגוסט") — לא נופל על איסור \\d\\.\\d של recommend_results;
    שנה מצורפת רק כשאינה השנה הנוכחית."""
    d = datetime(2026, 8, 25, 21, 0, tzinfo=shows_catalog._IL_TZ)
    assert shows_catalog._he_date(d.timestamp()) == (
        "25 באוגוסט" if datetime.now().year == 2026 else "25 באוגוסט 2026"
    )
    d2 = datetime(2031, 1, 2, tzinfo=shows_catalog._IL_TZ)
    assert shows_catalog._he_date(d2.timestamp()) == "2 בינואר 2031"
    assert not re.search(r"\d\.\d", shows_catalog._he_date(d.timestamp()))


# ── קופת: גריד דף הבית ──────────────────────────────────────────────────────
def test_kupat_parses_grid(monkeypatch):
    """aria-label → שם (עם unescape), הלינק מאותו article בלבד (באנר בלי לינק
    לא בולע את השכן — ה-smoke החי), dedup לפי URL."""
    monkeypatch.setattr(shows_catalog, "_get", _fake_get({shows_catalog._KUPAT_HOME: _KUPAT_HTML}))
    items = asyncio.run(shows_catalog._kupat())
    assert [it["title"] for it in items] == [
        "שלמה ארצי",
        "אייל גולן",
        "ארנה פארק – קופת ירושלים",
    ]
    assert items[1]["url"] == "https://www.kupat.co.il/show/eyalgolan"
    assert items[1]["platform"] == "kupat"
    assert items[1]["ts"] == 0 and items[1]["date"] == ""  # אין תאריכים בקופת


# ── fetch_upcoming: cache + כשל שקט ─────────────────────────────────────────
def test_fetch_upcoming_caches_for_ttl(monkeypatch):
    calls = {"n": 0}

    async def src():
        calls["n"] += 1
        return [{"title": "x", "ts": _FUTURE}]

    _use_sources(monkeypatch, src)
    a = asyncio.run(shows_catalog.fetch_upcoming())
    b = asyncio.run(shows_catalog.fetch_upcoming())
    assert a == b and calls["n"] == 1  # הקריאה השנייה מה-cache


def test_fetch_upcoming_source_failure_is_silent(monkeypatch):
    async def boom():
        raise RuntimeError("down")

    async def ok():
        return [{"title": "y", "ts": _FUTURE}]

    _use_sources(monkeypatch, boom, ok)
    items = asyncio.run(shows_catalog.fetch_upcoming())
    assert [it["title"] for it in items] == ["y"]  # המקור שנפל לא מפיל


def test_fetch_upcoming_all_failed_is_empty_no_raise(monkeypatch):
    async def boom():
        raise RuntimeError("down")

    _use_sources(monkeypatch, boom, boom)
    assert asyncio.run(shows_catalog.fetch_upcoming()) == []
    assert shows_catalog._cache["items"] == []  # כשל לא נכנס ל-cache


# ── recommend_shows: הסקירה ─────────────────────────────────────────────────
def _cat_item(title, ts, venue="היכל", city="תל אביב", category="מוזיקה", platform="leaan"):
    return {
        "title": title,
        "date": shows_catalog._he_date(ts) if ts else "",
        "ts": ts,
        "venue": venue,
        "city": city,
        "url": "https://www.leaan.co.il/events/x/1",
        "platform": platform,
        "category": category,
    }


def _seed_catalog(monkeypatch, items):
    monkeypatch.setattr(shows_catalog, "_cache", {"ts": time.monotonic(), "items": items})


def test_recommend_shows_shape_sort_and_filters(monkeypatch):
    """הקרוב בזמן קודם; ילדים/ספורט וקופת-בלי-תאריך בחוץ; הצורה של recommend_movies
    (name עוגן, blurb עובדות תאריך+מקום)."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("מאוחר", _FUTURE + _DAY),
            _cat_item("מוקדם", _FUTURE),
            _cat_item("מופע ילדים", _FUTURE, category="ילדים"),
            _cat_item("משחק כדורגל", _FUTURE, category="ספורט"),
            _cat_item("אייל גולן", 0, venue="", city="", category="", platform="kupat"),
        ],
    )
    items = asyncio.run(shows_catalog.recommend_shows())
    assert [p["name"] for p in items] == ["מוקדם", "מאוחר"]
    p = items[0]
    assert p["rating"] is None and p["reviews"] == 0 and p["uri"] == ""
    assert "היכל תל אביב" in p["blurb"] and shows_catalog._he_date(_FUTURE) in p["blurb"]


def test_recommend_shows_no_city_duplication(monkeypatch):
    """היכל שכבר מכיל את העיר ("מוזיאון אורי גלר, תל אביב") לא מקבל אותה שוב —
    נתפס ב-smoke החי (‏"תל אביב, תל אביב")."""
    _seed_catalog(
        monkeypatch,
        [_cat_item("מופע", _FUTURE, venue="מוזיאון אורי גלר, תל אביב", city="תל אביב")],
    )
    (p,) = asyncio.run(shows_catalog.recommend_shows())
    assert p["blurb"].count("תל אביב") == 1


def test_recommend_shows_area_filter_with_transliteration(monkeypatch):
    """אזור מה-extract מגיע באנגלית ("Tel Aviv") — גישור התעתיק של ה-resolver
    מתאים אותו לעיר העברית; אזור בלי אף התאמה → מגישים את מה שכן קיים."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("בתל אביב", _FUTURE, city="תל אביב"),
            _cat_item("בחיפה", _FUTURE + _DAY, city="חיפה"),
        ],
    )
    items = asyncio.run(shows_catalog.recommend_shows("Tel Aviv"))
    assert [p["name"] for p in items] == ["בתל אביב"]
    items = asyncio.run(shows_catalog.recommend_shows("אילת"))  # אין באילת כלום
    assert [p["name"] for p in items] == ["בתל אביב", "בחיפה"]


# ── שלב-1 פנימי ב-resolve_event_url ─────────────────────────────────────────
async def _brave_forbidden(*a, **k):
    raise AssertionError("Brave נקרא למרות שהקטלוג הכריע")


def test_resolve_event_internal_one_no_brave(monkeypatch):
    """הפער שאומת חי (19.7): אייל גולן נעלם מ-Brave — הקטלוג הפנימי מכריע one
    בלי לגעת ב-Brave בכלל, via=internal."""
    _seed_catalog(monkeypatch, [_cat_item("אייל גולן", 0, venue="", city="", platform="kupat")])
    shows_catalog._cache["items"][0]["url"] = "https://www.kupat.co.il/show/eyalgolan"
    monkeypatch.setattr(resolve, "search_events", _brave_forbidden)
    res = asyncio.run(resolve.resolve_event_url("אייל גולן"))
    assert res["status"] == "one" and res["via"] == "internal"
    assert res["url"] == "https://www.kupat.co.il/show/eyalgolan"
    assert res["platform"] == "kupat"


def test_resolve_event_internal_two_dates_is_many(monkeypatch):
    """שני מועדים לאותו אמן בקטלוג → many עם תאריך+היכל בכותרות — רשימת
    הבחירה של הלקוח היא המועדים האמיתיים, בלי Brave."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("קובי פרץ", _FUTURE, venue="היכל מנורה", city="תל אביב"),
            _cat_item("קובי פרץ", _FUTURE + _DAY, venue="היכל הפיס", city="חיפה"),
        ],
    )
    shows_catalog._cache["items"][1]["url"] = "https://www.leaan.co.il/events/x/2"
    monkeypatch.setattr(resolve, "search_events", _brave_forbidden)
    res = asyncio.run(resolve.resolve_event_url("קובי פרץ"))
    assert res["status"] == "many" and res["via"] == "internal"
    titles = [c["title"] for c in res["candidates"]]
    assert len(titles) == 2
    assert "היכל מנורה" in titles[0] and "היכל הפיס" in titles[1]


def test_resolve_event_internal_city_disambiguates(monkeypatch):
    """הלקוח נקב עיר (venue) — טוקן העיר מכריע בין שני מועדי הקטלוג → one פנימי."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("עומר אדם", _FUTURE, venue="פארק הירקון", city="תל אביב"),
            _cat_item("עומר אדם", _FUTURE + _DAY, venue="חוף הים", city="אילת"),
        ],
    )
    shows_catalog._cache["items"][1]["url"] = "https://www.leaan.co.il/events/x/2"
    monkeypatch.setattr(resolve, "search_events", _brave_forbidden)
    res = asyncio.run(resolve.resolve_event_url("עומר אדם", "אילת"))
    assert res["status"] == "one" and res["via"] == "internal"
    assert res["url"] == "https://www.leaan.co.il/events/x/2"


def test_resolve_event_internal_needs_all_artist_words(monkeypatch):
    """ה-smoke החי (20.7): "שלמה ארצי" מול קטלוג עם "אצטדיון שלמה ביטוח" —
    מילת-מותג אחת לא מספיקה לשלב הפנימי; ה-one הנקי מקופת גובר על רעש-הכדורגל
    של לאן, בלי Brave."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("הפועל פ״ת - מכבי פ״ת", _FUTURE, venue="אצטדיון שלמה ביטוח", city="פ״ת"),
            _cat_item("שלמה ארצי", 0, venue="", city="", platform="kupat"),
        ],
    )
    shows_catalog._cache["items"][1]["url"] = "https://www.kupat.co.il/show/shlomo-artzi"
    monkeypatch.setattr(resolve, "search_events", _brave_forbidden)
    res = asyncio.run(resolve.resolve_event_url("שלמה ארצי"))
    assert res["status"] == "one" and res["via"] == "internal"
    assert res["url"] == "https://www.kupat.co.il/show/shlomo-artzi"


def test_resolve_event_catalog_miss_falls_to_brave(monkeypatch):
    """אמן שלא בקטלוג → השלב הפנימי שקוף, Brave ממשיך כרגיל (via=brave)."""
    _seed_catalog(monkeypatch, [_cat_item("אמן אחר", _FUTURE)])

    async def fake_search(artist, venue=""):
        return [
            {
                "title": "עומר אדם - הופעה חיה | 20/09/26 פארק הירקון",
                "url": "https://www.leaan.co.il/events/omer/9",
                "platform": "leaan",
            }
        ]

    async def alive(url):
        return False

    monkeypatch.setattr(resolve, "search_events", fake_search)
    monkeypatch.setattr(resolve, "_event_dead", alive)
    res = asyncio.run(resolve.resolve_event_url("עומר אדם"))
    assert res["status"] == "one" and res["via"] == "brave"
    assert res["url"] == "https://www.leaan.co.il/events/omer/9"


def test_resolve_event_empty_catalog_unchanged(monkeypatch):
    """קטלוג ריק (ברירת המחדל בטסטים) → ההתנהגות הקיימת אחת-לאחת."""

    async def fake_search(artist, venue=""):
        return []

    monkeypatch.setattr(resolve, "search_events", fake_search)
    res = asyncio.run(resolve.resolve_event_url("להקה לא קיימת"))
    assert res["status"] == "none" and res["via"] == "brave"


# ── run_recommend: קטגוריית הופעות → הקטלוג הוא מקור העובדות ─────────────────
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


async def _grounding_forbidden(*a, **k):
    raise AssertionError("grounding נקרא בבקשת הופעות — הקטלוג הוא המקור")


def test_run_recommend_concert_serves_catalog_names(monkeypatch, _io):
    """category=concert → הקטלוג בלבד: שמות אמיתיים בהודעה, אפס grounding,
    והשמות נשמרים ל-_recs ("תסגור את הראשון" / "מה עוד יש")."""
    _seed_catalog(
        monkeypatch,
        [
            _cat_item("ליאת בנאי", _FUTURE, venue="רידינג 3", city="תל אביב"),
            _cat_item("שלמה ארצי", _FUTURE + _DAY, venue="קיסריה", city="קיסריה"),
        ],
    )
    monkeypatch.setattr(pipeline, "recommend_places", _grounding_forbidden)
    monkeypatch.setattr(pipeline, "recommend_movies", _grounding_forbidden)
    asyncio.run(pipeline.run_recommend("s1", {"task_type": "recommend", "category": "concert"}))
    msg = _io[0]
    assert "ליאת בנאי" in msg and "שלמה ארצי" in msg
    assert pipeline._recs_shown("s1") == ["ליאת בנאי", "שלמה ארצי"]


def test_run_recommend_hebrew_show_category(monkeypatch, _io):
    """גם category עברי ('הופעות') מנותב לקטלוג — לא ל-grounding."""
    _seed_catalog(monkeypatch, [_cat_item("עומר אדם", _FUTURE)])
    monkeypatch.setattr(pipeline, "recommend_places", _grounding_forbidden)
    monkeypatch.setattr(pipeline, "recommend_movies", _grounding_forbidden)
    asyncio.run(pipeline.run_recommend("s2", {"task_type": "recommend", "category": "הופעות"}))
    assert "עומר אדם" in _io[0]


def test_run_recommend_empty_catalog_is_honest_failure(monkeypatch, _io):
    """קטלוג ריק → הודעת הכנות הקיימת (recommend_failed) — אפס מופעים מומצאים."""
    monkeypatch.setattr(pipeline, "recommend_places", _grounding_forbidden)
    asyncio.run(pipeline.run_recommend("s3", {"task_type": "recommend", "category": "concert"}))
    assert len(_io) == 1
    for name in ("ליאת בנאי", "שלמה ארצי", "עומר אדם"):
        assert name not in _io[0]


def test_run_recommend_movie_show_is_still_movies(monkeypatch, _io):
    """'movie show' לא נבלע בענף ההופעות — movies נבדק קודם."""
    called = {}

    async def fake_movies(constraints="", exclude=None):
        called["movies"] = True
        return [
            {
                "name": "דיונה 3",
                "rating": None,
                "reviews": 0,
                "blurb": "",
                "uri": "",
                "place_id": "",
            }
        ]

    monkeypatch.setattr(pipeline, "recommend_movies", fake_movies)
    asyncio.run(pipeline.run_recommend("s4", {"task_type": "recommend", "category": "movie show"}))
    assert called.get("movies") and "דיונה 3" in _io[0]


def test_extract_mentions_concert_category():
    """ההנחיה ל-extract כוללת את קטגוריית ההופעות — בלעדיה המודל לא ידע לסווג."""
    assert "'concert'" in pipeline._EXTRACT
