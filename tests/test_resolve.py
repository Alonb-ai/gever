"""בדיקות ל-_match_restaurant (דיסאמביגואציה), ל-regexים (ontopo/tabit)
ול-resolve_reservation_url (multi-platform, תיעדוף Ontopo › Tabit)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation import resolve  # noqa: E402
from app.automation.resolve import _match_restaurant  # noqa: E402
from app.automation.resolve import (  # noqa: E402
    _PAGE,
    _TABIT,
    _from_brave,
    resolve_reservation_url,
)


def _fake_search(cands, raw=None):
    async def fake(name, city=""):
        return cands, (raw or [])

    return fake


def test_match_one():
    status, chosen, good = _match_restaurant("טאיזו", ["טאיזו תל אביב", "קפה אחר"])
    assert status == "one"
    assert chosen == "טאיזו תל אביב"
    assert good == ["טאיזו תל אביב"]


def test_match_many():
    status, chosen, good = _match_restaurant("הדסון", ["הדסון לילינבלום", "הדסון בורגר"])
    assert status == "many"
    assert chosen is None
    assert good == ["הדסון לילינבלום", "הדסון בורגר"]


def test_match_one_prefers_real_page_over_deal():
    # דף ההזמנה האמיתי מול דיל/טעימות — לא לשאול את הלקוח, לבחור את דף ההזמנה.
    status, chosen, good = _match_restaurant(
        "טאיזו", ["טאיזו - Ontopo", "ארוחת טעימות זוגית מבית טאיזו תל אביב"]
    )
    assert status == "one"
    assert chosen == "טאיזו - Ontopo"
    assert good == ["טאיזו - Ontopo"]


def test_match_none():
    status, chosen, good = _match_restaurant("טאיזו", ["קפה אחר", "מסעדה אחרת"])
    assert status == "none"
    assert chosen is None
    assert good == []


def test_page_matches():
    m = _PAGE.search("https://ontopo.com/he/il/page/123456")
    assert m is not None
    assert m.group(1) == "123456"


def test_page_no_match():
    assert _PAGE.search("https://example.com/he/il/page/123456") is None


def test_tabit_matches_site_slug():
    m = _TABIT.search("https://www.tabitisrael.co.il/site/greco-beach?x=1")
    assert m is not None
    assert m.group(1) == "greco-beach"


def test_tabit_no_match_on_other_paths():
    assert _TABIT.search("https://www.tabitisrael.co.il/online-reservations/create") is None


def test_from_brave_extracts_platform_candidates_and_dedups():
    # פורמט התשובה של Brave web search: data["web"]["results"] עם url+title.
    data = {
        "web": {
            "results": [
                {
                    "url": "https://ontopo.com/he/il/page/123",
                    "title": "רוסטיקו בזל&#x27;ה: הזמנת מקום",  # entities מפוענחים (_clean)
                },
                {"url": "https://www.tabitisrael.co.il/site/greco", "title": "הזמנת מקום - טאביט"},
                {"url": "https://ontopo.com/he/il/page/123", "title": "כפול — לא נספר"},
                {"url": "https://example.com/rustico", "title": "אתר לא רלוונטי"},
            ]
        }
    }
    out = _from_brave(data)
    assert [c["platform"] for c in out] == ["ontopo", "tabit"]
    assert out[0]["url"] == "https://ontopo.com/he/il/page/123"
    assert out[0]["title"] == "רוסטיקו בזל'ה: הזמנת מקום"  # &#x27; פוענח
    assert "greco" in out[1]["title"]  # ה-slug נוסף לכותרת הגנרית
    assert _from_brave({}) == []  # תשובה ריקה — לא קורס


def test_resolve_no_strong_match_never_picks_arbitrary_one(monkeypatch):
    # שאילתה בלי match חזק (כל המועמדים זרים) — לעולם לא 'one' שרירותי; שואלים את הלקוח.
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "רוסטיקו בזל",
                    "url": "https://ontopo.com/he/il/page/1",
                    "platform": "ontopo",
                },
                {
                    "title": "קפה אחר",
                    "url": "https://ontopo.com/he/il/page/2",
                    "platform": "ontopo",
                },
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("רוטשילד"))
    assert res["status"] in ("many", "none")
    assert res["status"] != "one"
    assert res["url"] is None


def _no_extra_brave(monkeypatch, results=None):
    """חוסם את חיפוש-הטלפון הנוסף (בלי רשת אמיתית בטסטים) ומאפס את מרווח הקצב."""
    calls = []

    async def fake_raw(query):
        calls.append(query)
        return results or []

    monkeypatch.setattr(resolve, "_brave_raw", fake_raw)
    monkeypatch.setattr(resolve, "_BRAVE_GAP_S", 0)
    monkeypatch.setattr(resolve.settings, "brave_api_key", "test-key")
    return calls


def test_resolve_no_candidates_is_none(monkeypatch):
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([]))
    _no_extra_brave(monkeypatch)
    res = asyncio.run(resolve_reservation_url("רוטשילד"))
    assert res["status"] == "none"
    assert res["url"] is None
    assert res["platform"] is None
    assert res["phone_hint"] is None


def test_resolve_prefers_ontopo_when_both_match(monkeypatch):
    # שתי הפלטפורמות עם match חזק → Ontopo מנצחת (התיעדוף), ו-Tabit נשמרת כ-fallback
    # לניסיון שני אם ההזמנה נכשלת בפועל (A3, תרחיש גרקו).
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "טאיזו Tabit",
                    "url": "https://www.tabitisrael.co.il/site/taizu",
                    "platform": "tabit",
                },
                {
                    "title": "טאיזו תל אביב",
                    "url": "https://ontopo.com/he/il/page/1",
                    "platform": "ontopo",
                },
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("טאיזו"))
    assert res["status"] == "one"
    assert res["platform"] == "ontopo"
    assert res["url"] == "https://ontopo.com/he/il/page/1"
    assert res["fallback"] == {
        "url": "https://www.tabitisrael.co.il/site/taizu",
        "platform": "tabit",
    }


def test_resolve_falls_back_to_tabit_when_ontopo_weak(monkeypatch):
    # תרחיש גרקו (dry-run 3): ב-Ontopo רק תוצאה זרה, ב-Tabit match אמיתי → Tabit.
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "אירוע שפג",
                    "url": "https://ontopo.com/he/il/page/37007370",
                    "platform": "ontopo",
                },
                {
                    "title": "גרקו ביץ' פרישמן",
                    "url": "https://www.tabitisrael.co.il/site/greco",
                    "platform": "tabit",
                },
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("גרקו"))
    assert res["status"] == "one"
    assert res["platform"] == "tabit"
    assert res["url"] == "https://www.tabitisrael.co.il/site/greco"


def test_resolve_tabit_only_works(monkeypatch):
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "גרקו ביץ'",
                    "url": "https://www.tabitisrael.co.il/site/greco",
                    "platform": "tabit",
                }
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("גרקו"))
    assert res["status"] == "one"
    assert res["platform"] == "tabit"
    assert res["fallback"] is None  # פלטפורמה אחת בלבד — אין ניסיון שני


if __name__ == "__main__":
    test_match_one()
    test_match_many()
    test_match_one_prefers_real_page_over_deal()
    test_match_none()
    test_page_matches()
    test_page_no_match()
    print("ok")


def test_og_title_extracts_both_page_formats():
    """og:title בדפי Ontopo: גם meta-tag קלאסי וגם JSON מוטמע (הפורמט שנצפה חי)."""
    meta = '<meta data-hid="og:title" property="og:title" content="A.K.A תל אביב-יפו: הזמנת מקום | אונטופו">'
    blob = '{"ogTitle":{"name":"og:title","content":"A.K.A תל אביב-יפו: הזמנת מקום | אונטופו"}}'
    assert resolve._og_title(meta) == "A.K.A תל אביב-יפו: הזמנת מקום | אונטופו"
    assert resolve._og_title(blob) == "A.K.A תל אביב-יפו: הזמנת מקום | אונטופו"
    assert resolve._og_title("<html>אין כאן כלום</html>") == ""


def test_resolve_url_title_enriched_from_page(monkeypatch):
    """ריצת ה-AKA (נצפה חי): Brave החזיר את דף המסעדה עם ה-URL ככותרת — בלי שם אין
    match ואין רשימה, והלקוח נתקע לנצח על 'יש כמה כאלה'. ההעשרה מביאה את השם
    האמיתי מה-og:title של הדף, וההזמנה יוצאת לדרך (status=one)."""

    class _FakeResp:
        text = '<meta property="og:title" content="A.K.A תל אביב-יפו: הזמנת מקום | אונטופו">'

    class _FakeHTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResp()

    monkeypatch.setattr(resolve.httpx, "AsyncClient", _FakeHTTP)
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "https://ontopo.com/he/il/page/58397013?source=google",
                    "url": "https://ontopo.com/he/il/page/58397013",
                    "platform": "ontopo",
                }
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("Aka"))
    assert res["status"] == "one"
    assert res["url"] == "https://ontopo.com/he/il/page/58397013"
    assert "A.K.A" in res["candidates"][0]["title"]


def _fake_site_http(monkeypatch, bodies):
    """מזייף httpx.AsyncClient למשיכת דפי אתר-המסעדה; מחזיר את רשימת ה-URLים שנמשכו."""
    fetched = []

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _HTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            fetched.append(url)
            return _Resp(bodies.get(url, "<html>אין כאן לינק</html>"))

    monkeypatch.setattr(resolve.httpx, "AsyncClient", _HTTP)
    return fetched


def test_site_fallback_finds_platform_link_on_restaurant_site(monkeypatch):
    """Phase 4-lite: אפס דפי פלטפורמה בחיפוש, אבל האתר של המסעדה עצמה מקשר ל-Ontopo
    (דלי A במחקר, ~30% מהפספוסים) → status=one עם ה-URL הקנוני, בלי לוותר."""
    raw = [
        {"title": "הרמיטאז' טבריה - האתר הרשמי", "url": "https://hermitage.co.il/"},
    ]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    extra = _no_extra_brave(monkeypatch)
    fetched = _fake_site_http(
        monkeypatch,
        {"https://hermitage.co.il/": '<a href="https://ontopo.com/he/il/page/58569787">הזמינו</a>'},
    )
    res = asyncio.run(resolve_reservation_url("הרמיטאז"))
    assert res["status"] == "one"
    assert res["platform"] == "ontopo"
    assert res["url"] == "https://ontopo.com/he/il/page/58569787"
    assert fetched == ["https://hermitage.co.il/"]
    assert extra == []  # מצאנו פלטפורמה — אין חיפוש-טלפון נוסף


def test_site_fallback_prefers_ontopo_when_page_links_both(monkeypatch):
    """הדף מקשר גם ל-Ontopo וגם ל-Tabit → סדר העדיפויות הקיים נשמר (Ontopo)."""
    raw = [{"title": "פסטורי אילת", "url": "https://www.pastory.co.il/"}]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    _no_extra_brave(monkeypatch)
    body = (
        '<a href="https://www.tabitisrael.co.il/site/pastory">טאביט</a>'
        '<a href="https://ontopo.com/he/il/page/111">אונטופו</a>'
    )
    _fake_site_http(monkeypatch, {"https://www.pastory.co.il/": body})
    res = asyncio.run(resolve_reservation_url("פסטורי"))
    assert res["status"] == "one"
    assert res["platform"] == "ontopo"
    assert res["url"] == "https://ontopo.com/he/il/page/111"


def test_site_fallback_skips_indexes_and_caps_at_two_pages(monkeypatch):
    """אינדקסים/רשתות (rest.co.il, פייסבוק) לא נמשכים; תקרת בקשות — שני דפים לכל היותר;
    כותרת שלא תואמת את השם לא נחשבת האתר-העצמי."""
    raw = [
        {"title": "דיאנא נצרת - הזמנות", "url": "https://www.rest.co.il/reservations/80205267/"},
        {"title": "דיאנא נצרת", "url": "https://facebook.com/diana"},
        {"title": "מסעדה אחרת לגמרי", "url": "https://other.co.il/"},
        {"title": "דיאנא המסעדה", "url": "https://site1.co.il/"},
        {"title": "דיאנא נצרת האתר הרשמי", "url": "https://site2.co.il/"},
        {"title": "דיאנא סניף שלישי", "url": "https://site3.co.il/"},
    ]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    _no_extra_brave(monkeypatch)
    fetched = _fake_site_http(monkeypatch, {})  # אף דף לא מכיל לינק פלטפורמה
    res = asyncio.run(resolve_reservation_url("דיאנא"))
    assert fetched == ["https://site1.co.il/", "https://site2.co.il/"]  # 2 לכל היותר, בלי אינדקסים
    assert res["status"] == "none"


def test_site_fallback_survives_fetch_error(monkeypatch):
    """האתר הראשון נופל → ממשיכים לשני; חריגת רשת לא מפילה את ה-resolve."""
    raw = [
        {"title": "דיאנא המסעדה", "url": "https://dead.co.il/"},
        {"title": "דיאנא נצרת", "url": "https://alive.co.il/"},
    ]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    _no_extra_brave(monkeypatch)

    class _Resp:
        text = '<a href="https://www.tabitisrael.co.il/site/diana">הזמינו</a>'

    class _HTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            if "dead" in url:
                raise RuntimeError("network down")
            return _Resp()

    monkeypatch.setattr(resolve.httpx, "AsyncClient", _HTTP)
    res = asyncio.run(resolve_reservation_url("דיאנא"))
    assert res["status"] == "one"
    assert res["platform"] == "tabit"
    assert res["url"] == "https://www.tabitisrael.co.il/site/diana"


def test_phone_hint_from_existing_snippets_no_extra_search(monkeypatch):
    """הטלפון כבר יושב ב-snippet של תוצאת חיפוש (אינדקסים כמו easy) → phone_hint,
    בלי בקשת Brave נוספת ובלי משיכת דפים."""
    raw = [
        {
            "title": "דיאנא נצרת - easy",
            "url": "https://easy.co.il/page/10031158",
            "description": "מסעדה בנצרת. טלפון: 04-6572919, פתוח כל השבוע",
        }
    ]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    extra = _no_extra_brave(monkeypatch)
    res = asyncio.run(resolve_reservation_url("דיאנא"))
    assert res["status"] == "none"
    assert res["phone_hint"] == "04-6572919"
    assert extra == []  # לא היה צורך בחיפוש נוסף


def test_phone_hint_via_one_extra_search(monkeypatch):
    """אין טלפון בתוצאות הקיימות → בדיוק חיפוש Brave אחד נוסף ("<שם> טלפון")."""
    raw = [{"title": "בלה בלה", "url": "https://easy.co.il/x", "description": "בלי מספר"}]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    extra = _no_extra_brave(
        monkeypatch,
        results=[{"title": "פקין דאק", "url": "https://x", "description": "חייגו 03-5222922"}],
    )
    res = asyncio.run(resolve_reservation_url("פקין דאק"))
    assert res["status"] == "none"
    assert res["phone_hint"] == "03-5222922"
    assert extra == ["פקין דאק טלפון"]  # בדיוק בקשה אחת נוספת


def test_phone_hint_absent_stays_none(monkeypatch):
    """אין טלפון בשום מקום → phone_hint=None וה-none נשאר כמו שהיה."""
    raw = [{"title": "בלה", "url": "https://easy.co.il/x", "description": "כלום"}]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    _no_extra_brave(monkeypatch)
    res = asyncio.run(resolve_reservation_url("אבו חסן"))
    assert res["status"] == "none"
    assert res["phone_hint"] is None


def test_real_titles_leaves_textual_titles_and_survives_fetch_error(monkeypatch):
    """כותרת טקסטואלית לא נוגעים בה (בלי GET מיותר); כשל fetch לא מפיל את ה-resolve."""

    class _BoomHTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise RuntimeError("network down")

    monkeypatch.setattr(resolve.httpx, "AsyncClient", _BoomHTTP)
    cands = [
        {"title": "גרקו פרישמן: הזמנת מקום | אונטופו", "url": "u1", "platform": "ontopo"},
        {"title": "https://ontopo.com/he/il/page/9", "url": "u2", "platform": "ontopo"},
    ]
    asyncio.run(resolve._real_titles(cands))
    assert cands[0]["title"] == "גרקו פרישמן: הזמנת מקום | אונטופו"  # לא השתנה
    assert cands[1]["title"] == "https://ontopo.com/he/il/page/9"  # כשל — נשאר, יסונן ברשימה


def test_dead_ontopo_page_loses_to_tabit(monkeypatch):
    """מלכודת גרקו (נצפתה שוב חי 15.7, הרצליה): דף Ontopo עם כותרת מושלמת אבל
    'לא פעיל' — נפסל, וטאביט החי זוכה במקומו."""
    import asyncio

    from app.automation import resolve as rs

    async def fake_search(name):
        return [
            {
                "title": "גרקו הרצליה הרצליה",
                "url": "https://ontopo.com/he/il/page/965",
                "platform": "ontopo",
            },
            {
                "title": "גרקו הרצליה",
                "url": "https://tabitisrael.co.il/site/greco-h",
                "platform": "tabit",
            },
        ], []

    async def fake_titles(c):
        pass

    async def fake_dead(url):
        return "ontopo.com" in url

    monkeypatch.setattr(rs, "search_reservation", fake_search)
    monkeypatch.setattr(rs, "_real_titles", fake_titles)
    monkeypatch.setattr(rs, "_ontopo_dead", fake_dead)
    r = asyncio.run(rs.resolve_reservation_url("גרקו הרצליה"))
    assert r["status"] == "one" and r["platform"] == "tabit"
    assert "tabitisrael" in r["url"]


def test_live_ontopo_page_still_wins(monkeypatch):
    """דף Ontopo חי — שום שינוי בסדר העדיפויות (ontopo לפני tabit)."""
    import asyncio

    from app.automation import resolve as rs

    async def fake_search(name):
        return [
            {"title": "הדסון", "url": "https://ontopo.com/he/il/page/1", "platform": "ontopo"},
            {"title": "הדסון", "url": "https://tabitisrael.co.il/site/hudson", "platform": "tabit"},
        ], []

    async def fake_titles(c):
        pass

    async def fake_dead(url):
        return False

    monkeypatch.setattr(rs, "search_reservation", fake_search)
    monkeypatch.setattr(rs, "_real_titles", fake_titles)
    monkeypatch.setattr(rs, "_ontopo_dead", fake_dead)
    r = asyncio.run(rs.resolve_reservation_url("הדסון"))
    assert r["status"] == "one" and r["platform"] == "ontopo"
    assert r["fallback"]["platform"] == "tabit"  # ה-fallback נשמר


def test_looks_dead_markers():
    from app.automation.resolve import _looks_dead

    assert _looks_dead("<div>העסק לא פעיל</div>") is True
    assert _looks_dead("<div>הזמינו שולחן עכשיו</div>") is False
