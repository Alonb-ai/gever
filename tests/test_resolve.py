"""בדיקות ל-_match_restaurant (דיסאמביגואציה), ל-regexים (ontopo/tabit),
לחיפוש הפנימי (שלב 1) ול-resolve_reservation_url (multi-platform, Ontopo › Tabit)."""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation import resolve  # noqa: E402
from app.automation.resolve import _match_restaurant  # noqa: E402
from app.automation.resolve import (  # noqa: E402
    _PAGE,
    _TABIT,
    _from_brave,
    resolve_reservation_url,
)


@pytest.fixture(autouse=True)
def _no_internal(monkeypatch):
    """שלב 1 (חיפוש פנימי) מכבה כברירת מחדל בטסטים — בלי רשת; טסטים של שלב 1
    מזייפים את ה-HTTP או קוראים למקורות ישירות."""
    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", ())
    monkeypatch.setattr(resolve, "_INTERNAL_GAP_S", 0)


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


def test_tabit_org_deeplink_becomes_candidate():
    """דיפ-לינק orgId של טאביט (תרחיש גרקו הרצליה, 16.7) → מועמד tabit עם URL קנוני,
    בלי לזהם את הכותרת ב-hex."""
    data = {
        "web": {
            "results": [
                {
                    "url": "https://tabitisrael.co.il/online-reservations/create-reservation"
                    "?step=search&orgId=5a005ba1b697f322003f3020",
                    "title": "גרקו הרצליה - הזמנת מקום, הזמנת שולחן",
                }
            ]
        }
    }
    out = _from_brave(data)
    assert len(out) == 1
    assert out[0]["platform"] == "tabit"
    assert out[0]["url"] == (
        "https://www.tabitisrael.co.il/online-reservations/create-reservation"
        "?step=search&orgId=5a005ba1b697f322003f3020"
    )
    assert "5a005ba1" not in out[0]["title"]  # ה-hex לא נוסף לכותרת


def test_dead_ontopo_falls_to_tabit_org_deeplink(monkeypatch):
    """התרחיש המלא של גרקו הרצליה (נצפה חי 16.7): דף Ontopo רפאים + דיפ-לינק orgId
    בתוצאות → הרפאים נפסל וטאביט (דיפ-לינק) זוכה, במקום none."""
    org_url = (
        "https://www.tabitisrael.co.il/online-reservations/create-reservation"
        "?step=search&orgId=5a005ba1b697f322003f3020"
    )

    async def fake_search(name):
        return [
            {
                "title": "גרקו הרצליה הרצליה: הזמנת מקום | אונטופו",
                "url": "https://ontopo.com/he/il/page/96550266",
                "platform": "ontopo",
            },
            {
                "title": "גרקו הרצליה - הזמנת מקום, הזמנת שולחן",
                "url": org_url,
                "platform": "tabit",
            },
        ], []

    async def fake_titles(c):
        pass

    async def fake_dead(url):
        return "ontopo.com" in url

    monkeypatch.setattr(resolve, "search_reservation", fake_search)
    monkeypatch.setattr(resolve, "_real_titles", fake_titles)
    monkeypatch.setattr(resolve, "_ontopo_dead", fake_dead)
    r = asyncio.run(resolve_reservation_url("גרקו הרצליה"))
    assert r["status"] == "one"
    assert r["platform"] == "tabit"
    assert r["url"] == org_url


def test_site_fallback_finds_tabit_org_deeplink_in_body(monkeypatch):
    """אתר-המסעדה מקשר להזמנות דרך דיפ-לינק orgId (ולא /site/) → נלכד, URL קנוני."""
    raw = [{"title": "גרקו הרצליה - האתר הרשמי", "url": "https://www.greco.co.il/"}]
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([], raw))
    _no_extra_brave(monkeypatch)
    body = (
        '<a href="https://tabitisrael.co.il/online-reservations/create-reservation'
        '?step=search&amp;orgId=5a005ba1b697f322003f3020">הזמינו שולחן</a>'
    )
    _fake_site_http(monkeypatch, {"https://www.greco.co.il/": body})
    res = asyncio.run(resolve_reservation_url("גרקו הרצליה"))
    assert res["status"] == "one"
    assert res["platform"] == "tabit"
    assert res["url"].endswith("orgId=5a005ba1b697f322003f3020")


def test_hudson_rishon_lezion_offers_only_brand_branches(monkeypatch):
    """תרחיש הדסון ראשון לציון (נצפה חי 16.7, אושר דטרמיניסטי בבנצ' 17.7): הסניף
    המבוקש לא קיים בפלטפורמה → many של סניפי המותג בלבד (הלקוח בוחר). "דדה ראשון
    לציון" — שחלקה רק את שם העיר ועמדה ראשונה ברשימה — מסוננת לגמרי, וגם הסניף
    האנגלי (Hudson) נתפס דרך גישור התעתיק."""
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "דדה ראשון לציון: הזמנת מקום | אונטופו",
                    "url": "https://ontopo.com/he/il/page/68790380",
                    "platform": "ontopo",
                },
                {
                    "title": "הדסון לילינבלום תל אביב-יפו: הזמנת מקום | אונטופו",
                    "url": "https://ontopo.com/he/il/page/22512632",
                    "platform": "ontopo",
                },
                {
                    "title": "Book now Hudson Ramat Hahayal Tel Aviv-Yafo | ontopo",
                    "url": "https://ontopo.com/he/il/page/92184508",
                    "platform": "ontopo",
                },
            ]
        ),
    )
    res = asyncio.run(resolve_reservation_url("הדסון ראשון לציון"))
    assert res["status"] == "many"
    titles = [c["title"] for c in res["candidates"]]
    assert len(titles) == 2  # רק סניפי הדסון; דדה בחוץ
    assert any("הדסון" in t for t in titles)
    assert any("Hudson" in t for t in titles)  # תעתיק: הדסון ↔ Hudson
    assert not any("דדה" in t for t in titles)


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


# --- קולנוע: _CINEMA_PLATFORMS + resolve_cinema_url (אותו חוזה החזרה) ---


def _fake_search_list(cands):
    """כמו _fake_search אבל לחוזה-הרשימה של search_cinema/search_events (בלי raw)."""

    async def fake(name, extra=""):
        return cands

    return fake


_PLANET_RE = resolve._CINEMA_PLATFORMS[0][1]
_RAVHEN_RE = resolve._CINEMA_PLATFORMS[1][1]
_CC_RE = resolve._CINEMA_PLATFORMS[2][1]


def _fake_cinema(cands):
    # search_cinema מחזיר רשימת מועמדים בלבד — בלי ה-raw של search_reservation.
    async def fake(movie):
        return cands

    return fake


def test_cinema_regexes_match_live_url_shapes():
    """הצורות שאומתו חיות (14.07.26): פלאנט slug+id, רב-חן זהה, סינמה סיטי מספרי."""
    m = _PLANET_RE.search("https://www.planetcinema.co.il/films/the-odyssey/7460s2r")
    assert m and m.group(1) == "the-odyssey/7460s2r"
    # yesplanet legacy (302 → planetcinema) — Brave עלול עוד להחזיר את הדומיין הישן
    m = _PLANET_RE.search("https://www.yesplanet.co.il/films/the-odyssey/7460s2r")
    assert m and m.group(1) == "the-odyssey/7460s2r"
    m = _RAVHEN_RE.search("https://www.rav-hen.co.il/films/the-odyssey/7460s2r")
    assert m and m.group(1) == "the-odyssey/7460s2r"
    m = _CC_RE.search("https://www.cinema-city.co.il/movie/6031")
    assert m and m.group(1) == "6031"
    # דפים שאינם דף סרט — לא נתפסים
    assert _PLANET_RE.search("https://www.planetcinema.co.il/cinemas/Rishon_Letziyon/1072") is None
    assert _CC_RE.search("https://www.cinema-city.co.il/branches") is None


def test_from_brave_cinema_canonicalizes_and_keeps_planet_ravhen_apart():
    """yesplanet → URL קנוני planetcinema; אותו movie id בפלאנט וברב-חן = שתי רשומות
    בכוונה (רב-חן היא ה-fallback כשבעיר אין פלאנט); כפילות באותה פלטפורמה מסוננת."""
    data = {
        "web": {
            "results": [
                {
                    "url": "https://www.yesplanet.co.il/films/the-odyssey/7460s2r",
                    "title": "האודיסאה",
                },
                {
                    "url": "https://www.rav-hen.co.il/films/the-odyssey/7460s2r",
                    "title": "האודיסאה — להזמנת כרטיסים באתר יס פלאנט",
                },
                {
                    "url": "https://www.planetcinema.co.il/films/the-odyssey/7460s2r",
                    "title": "כפול — לא נספר",
                },
                {"url": "https://www.cinema-city.co.il/movie/6031", "title": "האודיסאה סינמה סיטי"},
                {"url": "https://www.lev.co.il/movies/odyssey/", "title": "לב — מחוץ לאבטיפוס"},
            ]
        }
    }
    out = _from_brave(data, resolve._CINEMA_PLATFORMS)
    assert [c["platform"] for c in out] == ["planet", "rav-hen", "cinema-city"]
    assert out[0]["url"] == "https://www.planetcinema.co.il/films/the-odyssey/7460s2r"  # קנוני
    assert out[1]["url"] == "https://www.rav-hen.co.il/films/the-odyssey/7460s2r"
    assert out[2]["url"] == "https://www.cinema-city.co.il/movie/6031"


def test_resolve_cinema_prefers_planet_with_ravhen_fallback(monkeypatch):
    """פלאנט ורב-חן שתיהן match חזק → פלאנט מנצחת ורב-חן נשמרת כ-fallback
    (תרחיש גרקו של קולנוע: אין סניף פלאנט בעיר → הניסיון השני רץ לבד)."""
    monkeypatch.setattr(
        resolve,
        "search_cinema",
        _fake_cinema(
            [
                {
                    "title": "האודיסאה",
                    "url": "https://www.planetcinema.co.il/films/the-odyssey/7460s2r",
                    "platform": "planet",
                },
                {
                    "title": "האודיסאה — רב חן",
                    "url": "https://www.rav-hen.co.il/films/the-odyssey/7460s2r",
                    "platform": "rav-hen",
                },
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] == "one"
    assert res["platform"] == "planet"
    assert res["url"] == "https://www.planetcinema.co.il/films/the-odyssey/7460s2r"
    assert res["fallback"] == {
        "url": "https://www.rav-hen.co.il/films/the-odyssey/7460s2r",
        "platform": "rav-hen",
    }


def test_resolve_cinema_never_picks_ambiguous_movie(monkeypatch):
    """כלל הברזל נשמר גם בקולנוע: אין match חזק (שם דו-משמעי / גרסה מחודשת) →
    many/none, לעולם לא בוחרים סרט לבד."""
    monkeypatch.setattr(
        resolve,
        "search_cinema",
        _fake_cinema(
            [
                {"title": "סרט אחר לגמרי", "url": "u1", "platform": "planet"},
                {"title": "עוד סרט זר", "url": "u2", "platform": "cinema-city"},
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] in ("many", "none") and res["status"] != "one"
    assert res["url"] is None

    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema([]))
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] == "none" and res["platform"] is None


def test_resolve_cinema_city_only_no_fallback(monkeypatch):
    """רק סינמה סיטי עם match → one בלי fallback (אין פלטפורמה נוספת בתור)."""
    monkeypatch.setattr(
        resolve,
        "search_cinema",
        _fake_cinema(
            [
                {
                    "title": "האודיסאה — הזמנת כרטיסים",
                    "url": "https://www.cinema-city.co.il/movie/6031",
                    "platform": "cinema-city",
                }
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] == "one" and res["platform"] == "cinema-city"
    assert res["fallback"] is None


def test_resolve_cinema_chain_steers_past_planet(monkeypatch):
    """chain="cinema-city": הלקוח ביקש רשת ספציפית → פלאנט לא משתתפת, גם כשיש לה
    match חזק (בלי chain היא תמיד מנצחת — ראשונה בסדר התיעדוף). נצפה חי 15.07.26:
    'חינה אמריקאית' קיים בשתי הרשתות ותמיד נפתר לפלאנט."""
    cands = [
        {
            "title": "חינה אמריקאית",
            "url": "https://www.planetcinema.co.il/films/american-hina/8256s2r",
            "platform": "planet",
        },
        {
            "title": "חינה אמריקאית",
            "url": "https://www.cinema-city.co.il/movie/6117",
            "platform": "cinema-city",
        },
    ]
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(cands))
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="cinema-city"))
    assert res["status"] == "one" and res["platform"] == "cinema-city"
    assert res["url"] == "https://www.cinema-city.co.il/movie/6117"
    assert res["fallback"] is None  # רשת אחת בלבד בתור — אין fallback
    # בלי chain — ההתנהגות הקיימת לא משתנה: פלאנט מנצחת
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית"))
    assert res["platform"] == "planet"


class _FakeHTTP:
    """AsyncClient מזויף ל-_ravhen_from_planet: מחזיר status קבוע (או זורק)."""

    status = 200
    calls: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        _FakeHTTP.calls.append(url)
        if isinstance(_FakeHTTP.status, Exception):
            raise _FakeHTTP.status
        return type("R", (), {"status_code": _FakeHTTP.status})()


_HINA_PLANET_ONLY = [
    {
        "title": "חינה אמריקאית",
        "url": "https://www.planetcinema.co.il/films/american-hina/8256s2r",
        "platform": "planet",
    },
    {
        "title": "חינה אמריקאית",
        "url": "https://www.cinema-city.co.il/movie/6117",
        "platform": "cinema-city",
    },
]


def test_resolve_cinema_chain_ravhen_derives_from_planet(monkeypatch):
    """chain="rav-hen" כש-Brave לא מחזיר אף תוצאת rav-hen (נצפה חי 16.07.26 —
    רב-חן כמעט לא מאונדקסת): דף הסרט נגזר מה-match של פלאנט (אותה פלטפורמה,
    אותם movie ids), אחרי אימות GET שהחזיר 200."""
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(list(_HINA_PLANET_ONLY)))
    monkeypatch.setattr(resolve.httpx, "AsyncClient", _FakeHTTP)
    _FakeHTTP.status, _FakeHTTP.calls = 200, []
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="rav-hen"))
    assert res["status"] == "one" and res["platform"] == "rav-hen"
    assert res["url"] == "https://www.rav-hen.co.il/films/american-hina/8256s2r"
    assert _FakeHTTP.calls == ["https://www.rav-hen.co.il/films/american-hina/8256s2r"]


def test_resolve_cinema_chain_ravhen_302_means_not_showing(monkeypatch):
    """הסרט לא מוקרן ברב-חן → ה-GET מחזיר 302 (נבדק חי מול סרטי planet-only) —
    אין גזירה, ולעולם לא ממציאים "one" על רשת שאין בה את הסרט. גם כשל רשת
    (best-effort) לא מפיל את ה-resolve."""
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(list(_HINA_PLANET_ONLY)))
    monkeypatch.setattr(resolve.httpx, "AsyncClient", _FakeHTTP)
    _FakeHTTP.status, _FakeHTTP.calls = 302, []
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="rav-hen"))
    assert res["status"] != "one"
    assert res["url"] is None

    _FakeHTTP.status = RuntimeError("network down")
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="rav-hen"))
    assert res["status"] != "one"


def test_resolve_cinema_ravhen_no_derivation_without_chain(monkeypatch):
    """בלי chain אין גזירה (פלאנט ממילא מנצחת — אין מה לשלם GET מיותר), וכשיש
    תוצאת rav-hen אמיתית מ-Brave היא מנצחת בלי GET."""
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(list(_HINA_PLANET_ONLY)))
    monkeypatch.setattr(resolve.httpx, "AsyncClient", _FakeHTTP)
    _FakeHTTP.status, _FakeHTTP.calls = 200, []
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית"))
    assert res["platform"] == "planet" and _FakeHTTP.calls == []

    real_ravhen = list(_HINA_PLANET_ONLY) + [
        {
            "title": "חינה אמריקאית",
            "url": "https://www.rav-hen.co.il/films/american-hina/8256s2r",
            "platform": "rav-hen",
        }
    ]
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(real_ravhen))
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="rav-hen"))
    assert res["status"] == "one" and res["platform"] == "rav-hen"
    assert _FakeHTTP.calls == []


# --- הוט סינמה: entry רביעי + שלב-1 מקטלוג דף הבית (recon 17.7) ---

_HOT_HTML = """<html><script>
app.currentLang = 'he';
app.movies = [{"ID":3305,"Name":"האודיסאה","PageUrl":"/movie/3305/the-odyssey"},
 {"ID":3310,"Name":"זוטרופוליס 2","PageUrl":"/movie/3310/zootropolis-2"},
 {"ID":3311,"Name":"זוטרופוליס 2 מדובב","PageUrl":"/movie/3311/zootropolis-2-heb"}];
app.theaters = [];</script></html>"""


def test_hot_cinema_platform_entry_is_last_and_matches_url_shape():
    """ה-entry של הוט סינמה אחרון בכוונה (לא משנה תיעדוף קיים), וה-regex תופס את
    צורת ה-URL החיה; ה-URL הקנוני בלי slug עושה 302 לדף המלא (אומת חי 17.7)."""
    plat, rx, canon = resolve._CINEMA_PLATFORMS[-1]
    assert plat == "hot-cinema"
    m = rx.search("https://www.hotcinema.co.il/movie/3305/the-odyssey")
    assert m and canon.format(m.group(1)) == "https://www.hotcinema.co.il/movie/3305"
    assert rx.search("https://www.hotcinema.co.il/theaters") is None


def test_hot_internal_parses_embedded_catalog(monkeypatch):
    """app.movies המוטמע בדף הבית → מועמדי {title, url, platform}, כולל וריאנטים
    מדובבים (שיישארו מובחנים לדיסאמביגואציה)."""
    _fake_site_http(monkeypatch, {resolve._HOT_HOME: _HOT_HTML})
    cands = asyncio.run(resolve._hot_internal())
    assert [c["title"] for c in cands] == ["האודיסאה", "זוטרופוליס 2", "זוטרופוליס 2 מדובב"]
    assert cands[0]["url"] == "https://www.hotcinema.co.il/movie/3305/the-odyssey"
    assert all(c["platform"] == "hot-cinema" for c in cands)


def test_hot_internal_failure_is_silent(monkeypatch):
    """דף בלי הקטלוג או כשל רשת → [] שקט (Brave ימשיך), לעולם לא חריגה החוצה."""
    _fake_site_http(monkeypatch, {resolve._HOT_HOME: "<html>בלי קטלוג</html>"})
    assert asyncio.run(resolve._hot_internal()) == []
    monkeypatch.setattr(resolve.httpx, "AsyncClient", _FakeHTTP)
    _FakeHTTP.status, _FakeHTTP.calls = RuntimeError("network down"), []
    assert asyncio.run(resolve._hot_internal()) == []


def test_resolve_cinema_hot_chain_resolves_from_catalog(monkeypatch):
    """chain="hot-cinema": שלב 1 מהקטלוג מכריע בלי לגעת ב-Brave — התאמה מדויקת
    → one (via=internal); שם שמתאים לכמה וריאנטים (מדובב) → many של הרשת,
    שהלקוח יבחר גרסה — התנהגות רצויה."""

    async def boom_search(movie):
        raise AssertionError("Brave לא אמור להיקרא כשהקטלוג מכריע")

    monkeypatch.setattr(resolve, "search_cinema", boom_search)
    _fake_site_http(monkeypatch, {resolve._HOT_HOME: _HOT_HTML})

    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה", chain="hot-cinema"))
    assert res["status"] == "one" and res["platform"] == "hot-cinema"
    assert res["url"] == "https://www.hotcinema.co.il/movie/3305/the-odyssey"
    assert res["via"] == "internal"

    res = asyncio.run(resolve.resolve_cinema_url("זוטרופוליס", chain="hot-cinema"))
    assert res["status"] == "many" and res["platform"] == "hot-cinema"
    assert res["via"] == "internal"
    assert [c["title"] for c in res["candidates"]] == ["זוטרופוליס 2", "זוטרופוליס 2 מדובב"]


def test_resolve_cinema_hot_chain_falls_back_to_brave(monkeypatch):
    """הקטלוג לא הכריע — נפל (אין app.movies) או שהסרט פשוט לא בו — נופלים בשקט
    ל-Brave, שם ה-regex החדש תופס דפי hotcinema ו-chain עדיין מסנן רשתות אחרות."""
    cands = [
        {
            "title": "חינה אמריקאית",
            "url": "https://www.planetcinema.co.il/films/american-hina/8256s2r",
            "platform": "planet",
        },
        {
            "title": "חינה אמריקאית",
            "url": "https://www.hotcinema.co.il/movie/2222",
            "platform": "hot-cinema",
        },
    ]
    monkeypatch.setattr(resolve, "search_cinema", _fake_cinema(cands))
    for homepage in ("<html>בלי קטלוג</html>", _HOT_HTML):  # קטלוג נפל / סרט לא בקטלוג
        _fake_site_http(monkeypatch, {resolve._HOT_HOME: homepage})
        res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="hot-cinema"))
        assert res["status"] == "one" and res["platform"] == "hot-cinema"
        assert res["url"] == "https://www.hotcinema.co.il/movie/2222"
        assert res["via"] == "brave"


def test_from_brave_cinema_city_strips_site_name_suffix():
    """כותרות סינמה סיטי חיות ("<סרט> - סינמה סיטי") — שם האתר נחתך, כך שגרסה
    מדובבת-לרוסית נשארת מובחנת והגרסה המבוקשת המדויקת נבחרת (נצפה חי 15.07.26:
    'סופר מריו גלקסי הסרט-מדובב' מול '...מדובב לרוסית')."""
    data = {
        "web": {
            "results": [
                {
                    "url": "https://www.cinema-city.co.il/movie/6054",
                    "title": "סופר מריו גלקסי הסרט-מדובב - סינמה סיטי",
                },
                {
                    "url": "https://www.cinema-city.co.il/movie/6113",
                    "title": "סופר מריו גלקסי הסרט-מדובב לרוסית - סינמה סיטי",
                },
            ]
        }
    }
    out = _from_brave(data, resolve._CINEMA_PLATFORMS)
    assert [c["title"] for c in out] == [
        "סופר מריו גלקסי הסרט-מדובב",
        "סופר מריו גלקסי הסרט-מדובב לרוסית",
    ]
    # ומקצה לקצה: הבקשה המדויקת בוחרת את הגרסה הנכונה ("one"), לא נופלת ל-many
    status, chosen, _ = resolve._match_restaurant(
        "סופר מריו גלקסי הסרט-מדובב", [c["title"] for c in out]
    )
    assert status == "one" and chosen == "סופר מריו גלקסי הסרט-מדובב"


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

    # המבנה שנצפה בדפי הרפאים האמיתיים (גרקו הרצליה, MAZA — בנצ' 17.7)
    assert _looks_dead('"shifts":{"out_of_business":{"cta_url":null}}') is True
    assert (
        _looks_dead(
            "<p>מסעדה זו אינה זמינה להזמנות דרך מערכת אונטופו, להזמנות יש לפנות ישירות למסעדה</p>"
        )
        is True
    )
    assert _looks_dead("<div>האירוע הסתיים</div>") is True
    assert _looks_dead("<div>הזמינו שולחן עכשיו</div>") is False
    # ה-i18n שמוטמע בכל דף אונטופו חי — המרקר הישן "לא פעיל" נפל עליו (בנצ' 17.7)
    assert _looks_dead('"active":"פעיל","nonActive":"לא פעיל","default":"ברירת מחדל"') is False


# --- תיקוני הבנצ' 17.7: משקל מותג, הכרעת סניף, גישור תעתיק ---


def test_skeleton_bridges_hebrew_and_latin():
    from app.automation.resolve import _skeleton

    assert _skeleton("אסה") == _skeleton("asa")  # אסה ↔ ASA
    assert _skeleton("הדסון") == _skeleton("hudson")
    assert _skeleton("מסא") == _skeleton("maza")  # ז/z ↔ ס/s מקופלים
    assert _skeleton("קלארו") == _skeleton("claro")  # c ↔ ק
    assert _skeleton("רוסטיקו") == _skeleton("rustico")
    assert _skeleton("בזל") == _skeleton("basel")
    assert _skeleton("אסה") != _skeleton("house")  # תנועת הפתיחה מבחינה
    assert _skeleton("אסה") != _skeleton("izakaya")


def test_has_token_prefix_guard():
    from app.automation.resolve import _has_token

    assert _has_token("בזל", "רוסטיקו בזלה הזמנת מקום")  # בזל'ה = תוספת אות אחת
    assert not _has_token("מסא", "טיקה מסאלה אילת")  # מסאלה ≠ מסא (תוספת ארוכה)
    assert _has_token("קלארו", "קלארוהחדר הפרטי")  # טוקן ארוך — תחילית חופשית


def test_match_requires_brand_word_generic_not_enough():
    """באג אסה→גייג'ין (דטרמיניסטי בכל 4 סבבי הבנצ'): "איזקאיה"+"תל אביב" המשותפות
    לא מספיקות — המותג חייב להופיע, וגם באנגלית (ASA) הוא נתפס."""
    status, chosen, _ = _match_restaurant(
        "אסה איזקאיה תל אביב",
        [
            "גייג'ין איזקאיה תל אביב-יפו: הזמנת מקום | אונטופו",
            "ASA Izakaya תל אביב-יפו: הזמנת מקום | אונטופו",
            "איזאקיה - אומאי - UMAI תל אביב-יפו: הזמנת מקום | אונטופו",
        ],
    )
    assert status == "one"
    assert "ASA" in chosen


def test_match_branch_token_decides_between_branches():
    """באג רוסטיקו בזל→רוטשילד: כששני סניפים קיימים, טוקן הסניף מהבקשה מכריע —
    גם כשכותרת הסניף בלי עיר (בזל'ה) והמתחרה דווקא מכיל את שם העיר."""
    status, chosen, _ = _match_restaurant(
        "רוסטיקו בזל תל אביב",
        ["רוסטיקו רוטשילד תל אביב-יפו: הזמנת מקום | אונטופו", "רוסטיקו בזל'ה: הזמנת מקום"],
    )
    assert status == "one"
    assert "בזל" in chosen


def test_match_missing_branch_never_picks_silently():
    """טוקן סניף בבקשה שאינו באף מועמד (סניף בזל לא בתוצאות) → many (שאלת אישור),
    לא בחירה שקטה בסניף אחר של אותו מותג."""
    status, chosen, good = _match_restaurant(
        "רוסטיקו בזל תל אביב", ["רוסטיקו רוטשילד תל אביב-יפו: הזמנת מקום | אונטופו"]
    )
    assert status == "many"
    assert chosen is None
    assert good == ["רוסטיקו רוטשילד תל אביב-יפו: הזמנת מקום | אונטופו"]


def test_match_duplicate_clean_titles_are_one():
    """תרחיש טאיזו מהבנצ': אותו דף הזמנה מופיע פעמיים (שני מזהים) לצד סניפים
    אמיתיים — הכפילות אינה עמימות, והכותרת הנקייה זוכה."""
    status, chosen, _ = _match_restaurant(
        "טאיזו תל אביב",
        [
            "טאיזו תל אביב-יפו: הזמנת מקום | אונטופו",
            "טאיזו תל אביב-יפו: הזמנת מקום | אונטופו",
            "קפה טאיזו תל אביב-יפו: הזמנת מקום | אונטופו",
            "טאיזו אירועים תל אביב-יפו: הזמנת מקום | אונטופו",
        ],
    )
    assert status == "one"
    assert chosen == "טאיזו תל אביב-יפו: הזמנת מקום | אונטופו"


def test_dead_brand_page_yields_none_not_noise_many(monkeypatch):
    """באג מסא→MAZA: המותג זוהה (MAZA, בגישור תעתיק) אבל הדף רפאים → נפסל, ושאר
    ה-pool (CASAMAYA) הוא רעש — none עם phone_hint, לא רשימת many מטעה."""
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "MAZA תל אביב-יפו: הזמנת מקום | אונטופו",
                    "url": "https://ontopo.com/he/il/page/36234429",
                    "platform": "ontopo",
                },
                {
                    "title": "CASAMAYA תל אביב-יפו: הזמנת מקום | אונטופו",
                    "url": "https://ontopo.com/he/il/page/1111",
                    "platform": "ontopo",
                },
            ]
        ),
    )
    _no_extra_brave(monkeypatch)

    async def fake_titles(c):
        pass

    async def fake_dead(url):
        return "36234429" in url

    monkeypatch.setattr(resolve, "_real_titles", fake_titles)
    monkeypatch.setattr(resolve, "_ontopo_dead", fake_dead)
    res = asyncio.run(resolve_reservation_url("מסא תל אביב"))
    assert res["status"] == "none"
    assert res["url"] is None


# --- שלב 1: החיפוש הפנימי של הפלטפורמות ---


def _fake_internal_http(monkeypatch, handlers):
    """מזייף httpx.AsyncClient עבור המקורות הפנימיים: handlers = פונקציה
    (url, params) → dict של JSON. מחזיר את יומן הקריאות."""
    calls = []

    class _Resp:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    class _HTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append((url, dict(params or {})))
            return _Resp(handlers(url, params or {}))

    monkeypatch.setattr(resolve.httpx, "AsyncClient", _HTTP)
    monkeypatch.setattr(resolve, "_INTERNAL_GAP_S", 0)
    return calls


def test_ontopo_internal_finds_branch_via_brand_query(monkeypatch):
    """תרחיש רוסטיקו בזל: השם המלא לא נמצא, שאילתת המותג מחזירה את שני הסניפים,
    וה-URL נבנה מדף ה-reservation שב-venue_profile (venue slug ≠ page slug)."""
    profiles = {
        "34201385": {"pages": [{"slug": "57585571", "content_type": "reservation"}]},
        "51060511": {"pages": [{"slug": "37905695", "content_type": "reservation"}]},
    }

    def handlers(url, params):
        if url.endswith("/unified_search"):
            if params["terms"] == "רוסטיקו":
                return {
                    "found": True,
                    "suggestions": [
                        {
                            "type": "venue",
                            "label": "רוסטיקו רוטשילד",
                            "secondary": "תל אביב-יפו",
                            "slug": "34201385",
                        },
                        {
                            "type": "venue",
                            "label": "רוסטיקו בזל",
                            "secondary": "תל אביב-יפו",
                            "slug": "51060511",
                        },
                    ],
                }
            return {"found": False, "suggestions": []}
        return profiles[params["slug"]]

    _fake_internal_http(monkeypatch, handlers)
    cands = asyncio.run(resolve._ontopo_internal("רוסטיקו בזל תל אביב"))
    # תיקון 19.7: המועמדים מדורגים לפי התאמה לבקשה (טוקן הסניף "בזל") לפני החיתוך
    assert [c["title"] for c in cands] == ["רוסטיקו בזל תל אביב-יפו", "רוסטיקו רוטשילד תל אביב-יפו"]
    assert cands[0]["url"] == "https://ontopo.com/he/il/page/37905695"
    assert all(c["platform"] == "ontopo" for c in cands)


def test_ontopo_internal_filters_fuzzy_and_unbookable(monkeypatch):
    """סינון מותג על ההצעות (מסא ≠ טיקה מסאלה) + venue בלי דף reservation נשמט."""

    def handlers(url, params):
        if url.endswith("/unified_search"):
            return {
                "found": True,
                "suggestions": [
                    {"type": "venue", "label": "טיקה מסאלה אילת", "secondary": "אילת", "slug": "1"},
                    {"type": "city", "label": "מסא-עיר", "slug": None},
                ],
            }
        raise AssertionError("venue_profile לא אמור להיקרא — אף הצעה לא עברה סינון")

    _fake_internal_http(monkeypatch, handlers)
    assert asyncio.run(resolve._ontopo_internal("מסא תל אביב")) == []

    def handlers2(url, params):
        if url.endswith("/unified_search"):
            return {
                "found": True,
                "suggestions": [
                    {"type": "venue", "label": "קלארו", "secondary": "תל אביב-יפו", "slug": "9"}
                ],
            }
        return {"pages": [{"slug": "77", "content_type": "event"}]}  # אין דף הזמנות

    _fake_internal_http(monkeypatch, handlers2)
    assert asyncio.run(resolve._ontopo_internal("קלארו תל אביב")) == []


def test_tabit_internal_matches_hebrew_via_aliases(monkeypatch):
    """ה-bridge של טאביט fuzzy — הסינון לפי name+aliases משאיר רק את המותג, בונה
    דיפ-לינק orgId קנוני, ומדלג על ארגונים בלי services.book."""

    def handlers(url, params):
        assert url == resolve._TABIT_BRIDGE
        return {
            "organizations": [
                {
                    "_id": "6092fb6a991ff07306ca899e",
                    "name": "Hudson לילינבלום",
                    "city": "תל אביב",
                    "aliases": ["האדסון", "הדסון"],
                    "services": {"book": True},
                },
                {
                    "_id": "57d7abddbdbaae1e00feb6af",
                    "name": "הדסון רמת החייל",
                    "city": "תל אביב",
                    "aliases": [],
                    "services": {"book": True},
                },
                {
                    "_id": "65f977255048c76ba370df4a",
                    "name": "CASA TUA",
                    "city": "הרצליה",
                    "aliases": ["קאסה טואה"],
                    "services": {"book": True},
                },
                {
                    "_id": "0000",
                    "name": "הדסון דליברי",
                    "city": "חיפה",
                    "aliases": [],
                    "services": {"book": False},  # אין הזמנות — נשמט
                },
            ]
        }

    _fake_internal_http(monkeypatch, handlers)
    cands = asyncio.run(resolve._tabit_internal("הדסון ראשון לציון"))
    assert [c["title"] for c in cands] == ["Hudson לילינבלום תל אביב", "הדסון רמת החייל תל אביב"]
    assert cands[0]["url"].endswith("orgId=6092fb6a991ff07306ca899e")
    assert all(c["platform"] == "tabit" for c in cands)


def test_resolve_internal_wins_without_brave(monkeypatch):
    """שלב 1 מכריע → Brave לא נקרא בכלל, via=internal, ודף הרפאים עדיין נבדק."""

    async def fake_ontopo(name):
        return [
            {
                "title": "רוסטיקו בזל תל אביב-יפו",
                "url": "https://ontopo.com/he/il/page/37905695",
                "platform": "ontopo",
            }
        ]

    async def boom(name):
        raise AssertionError("Brave לא אמור להיקרא כששלב 1 הכריע")

    async def fake_dead(url):
        return False

    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", (fake_ontopo,))
    monkeypatch.setattr(resolve, "search_reservation", boom)
    monkeypatch.setattr(resolve, "_ontopo_dead", fake_dead)
    res = asyncio.run(resolve_reservation_url("רוסטיקו בזל תל אביב"))
    assert res["status"] == "one"
    assert res["via"] == "internal"
    assert res["url"] == "https://ontopo.com/he/il/page/37905695"


def test_resolve_internal_failure_falls_back_to_brave_silently(monkeypatch):
    """endpoint פנימי שקורס (או מחזיר ריק) — degradation חלק למסלול Brave הקיים."""

    async def broken(name):
        raise RuntimeError("endpoint changed")

    async def empty(name):
        return []

    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", (broken, empty))
    monkeypatch.setattr(
        resolve,
        "search_reservation",
        _fake_search(
            [
                {
                    "title": "טאיזו תל אביב",
                    "url": "https://ontopo.com/he/il/page/1",
                    "platform": "ontopo",
                }
            ]
        ),
    )

    async def fake_dead(url):
        return False

    monkeypatch.setattr(resolve, "_ontopo_dead", fake_dead)
    res = asyncio.run(resolve_reservation_url("טאיזו"))
    assert res["status"] == "one"
    assert res["via"] == "brave"


def test_resolve_internal_many_asks_client(monkeypatch):
    """שלב 1 מחזיר כמה סניפים בלי טוקן מכריע → many מהרשימה הפנימית (הלקוח בוחר)."""

    async def fake_tabit(name):
        return [
            {"title": "Hudson לילינבלום תל אביב", "url": "u1", "platform": "tabit"},
            {"title": "הדסון רמת החייל תל אביב", "url": "u2", "platform": "tabit"},
        ]

    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", (fake_tabit,))
    res = asyncio.run(resolve_reservation_url("הדסון ראשון לציון"))
    assert res["status"] == "many"
    assert res["via"] == "internal"
    assert len(res["candidates"]) == 2


# --- הופעות: _EVENT_PLATFORMS + resolve_event_url (אותו חוזה החזרה) ---

_LEAAN_RE = resolve._EVENT_PLATFORMS[0][1]
_KUPAT_RE = resolve._EVENT_PLATFORMS[1][1]

_LEAAN_SLUG = "%D7%A7%D7%95%D7%91%D7%99-%D7%A4%D7%A8%D7%A5/5514"  # קובי-פרץ/5514 מקודד


def test_event_regexes_match_live_url_shapes():
    """הצורות שאומתו חיות (15.07.26): לאן /events/<slug מקודד>/<id>, קופת /show/<slug>."""
    m = _LEAAN_RE.search(f"https://www.leaan.co.il/events/{_LEAAN_SLUG}")
    assert m and m.group(1) == _LEAAN_SLUG
    # הסאב-אתר הישן של לאן — לא דף אירוע, אסור לתפוס
    assert not _LEAAN_RE.search("https://www.leaan.co.il/eco99/he-IL/shows/12345")
    m = _KUPAT_RE.search("https://www.kupat.co.il/show/omer-adam")
    assert m and m.group(1) == "omer-adam"
    m = _KUPAT_RE.search("https://kupat.co.il/show/eyalgolan?utm=x")
    assert m and m.group(1) == "eyalgolan"


def test_from_brave_events_canonicalizes_and_dedups():
    """קנוניזציה ל-URL הרשמי + dedup לפי (platform, id); שני עמודי קופת לאותו אמן
    (eyalgolan / eyalgolan-idf) = שתי רשומות מובחנות בכוונה."""
    data = {
        "web": {
            "results": [
                {
                    "url": f"https://leaan.co.il/events/{_LEAAN_SLUG}?utm_source=brave",
                    "title": "קובי פרץ - הופעה חיה בתל אביב | 11/08/26 היכל מנורה | כרטיסים רשמיים בלאן",
                },
                {  # אותו אירוע שוב — נבלע ב-dedup
                    "url": f"https://www.leaan.co.il/events/{_LEAAN_SLUG}",
                    "title": "קובי פרץ | כרטיסים בלאן",
                },
                {"url": "https://www.kupat.co.il/show/eyalgolan", "title": "אייל גולן"},
                {
                    "url": "https://www.kupat.co.il/show/eyalgolan-idf",
                    "title": "אייל גולן לובש מדים",
                },
            ]
        }
    }
    out = _from_brave(data, resolve._EVENT_PLATFORMS)
    assert [c["url"] for c in out] == [
        f"https://www.leaan.co.il/events/{_LEAAN_SLUG}",
        "https://www.kupat.co.il/show/eyalgolan",
        "https://www.kupat.co.il/show/eyalgolan-idf",
    ]
    assert out[0]["platform"] == "leaan" and out[1]["platform"] == "kupat"


def test_leaan_title_suffix_keeps_date_and_venue():
    """חותכים רק את זנב שם-האתר — התאריך וההיכל נשארים (הם רשימת הבחירה של הלקוח)."""
    seen = set()
    c = resolve._candidate(
        f"https://www.leaan.co.il/events/{_LEAAN_SLUG}",
        "קובי פרץ - הופעה חיה בתל אביב | 11/08/26 היכל מנורה | כרטיסים רשמיים בלאן",
        seen,
        resolve._EVENT_PLATFORMS,
    )
    assert c["title"] == "קובי פרץ - הופעה חיה בתל אביב | 11/08/26 היכל מנורה"


def test_leaan_title_suffix_all_tail_variants():
    """שלושת וריאנטי הזנב שנצפו חי: '| כרטיסים רשמיים בלאן', '| כרטיסים רשמיים | לאן',
    '| כרטיסים בלאן' — כולם נחתכים, בלי לגעת בשאר הכותרת."""
    for tail in (" | כרטיסים רשמיים בלאן", " | כרטיסים רשמיים | לאן", " | כרטיסים בלאן"):
        assert (
            resolve._LEAAN_TITLE_SUFFIX.sub("", f"קובי פרץ | 11/08/26 היכל מנורה{tail}").strip()
            == "קובי פרץ | 11/08/26 היכל מנורה"
        )


def test_kupat_title_suffix():
    seen = set()
    c = resolve._candidate(
        "https://www.kupat.co.il/show/omer-adam",
        "עומר אדם הופעות 2026 - הזמנת כרטיסים ישירה להופעה של עומר אדם",
        seen,
        resolve._EVENT_PLATFORMS,
    )
    assert c["title"] == "עומר אדם הופעות 2026"


def test_resolve_event_two_dates_same_artist_is_many(monkeypatch):
    """שני מועדים לאותו אמן בלאן → many עם שתי כותרות מובחנות (תאריך+היכל) —
    זה הפיצ'ר: רשימת הבחירה של הלקוח היא המועדים האמיתיים."""
    monkeypatch.setattr(
        resolve,
        "search_events",
        _fake_search_list(
            [
                {
                    "title": "קובי פרץ - הופעה חיה בתל אביב | 11/08/26 היכל מנורה",
                    "url": "https://www.leaan.co.il/events/a/1",
                    "platform": "leaan",
                },
                {
                    "title": "קובי פרץ - הופעה חיה בחיפה | 15/08/26 היכל הפיס",
                    "url": "https://www.leaan.co.il/events/b/2",
                    "platform": "leaan",
                },
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_event_url("קובי פרץ"))
    assert res["status"] == "many"
    titles = [c["title"] for c in res["candidates"]]
    assert len(titles) == 2 and titles[0] != titles[1]
    assert "היכל מנורה" in titles[0] and "היכל הפיס" in titles[1]


async def _all_alive(url):
    return False


def test_resolve_event_leaan_primary_kupat_fallback(monkeypatch):
    """match חזק בלאן וגם בקופת → one על לאן (ראשית) עם fallback מקופת."""
    monkeypatch.setattr(resolve, "_event_dead", _all_alive)
    monkeypatch.setattr(
        resolve,
        "search_events",
        _fake_search_list(
            [
                {
                    "title": "עומר אדם - הופעה חיה | 20/09/26 פארק הירקון",
                    "url": "https://www.leaan.co.il/events/omer/9",
                    "platform": "leaan",
                },
                {
                    "title": "עומר אדם הופעות 2026",
                    "url": "https://www.kupat.co.il/show/omer-adam",
                    "platform": "kupat",
                },
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_event_url("עומר אדם"))
    assert res["status"] == "one"
    assert res["url"] == "https://www.leaan.co.il/events/omer/9" and res["platform"] == "leaan"
    assert res["fallback"] == {"url": "https://www.kupat.co.il/show/omer-adam", "platform": "kupat"}


def test_resolve_event_none_has_no_restaurant_fallbacks(monkeypatch):
    """אפס מועמדים → none נקי: בלי phone_hint ובלי משיכת אתר-עצמי (מסעדות בלבד)."""
    monkeypatch.setattr(resolve, "search_events", _fake_search_list([]))
    res = asyncio.run(resolve.resolve_event_url("להקה לא קיימת"))
    assert res["status"] == "none"
    assert "phone_hint" not in res


def test_dead_event_page_falls_to_next_platform(monkeypatch):
    """מלכודת עומר אדם (QA חי הופעות #2): דף show בקופת עם כותרת מושלמת אבל בלי אף
    מועד לרכישה — נפסל בבדיקת החיות, והמועמד החי מהפלטפורמה הבאה זוכה."""
    checked = []

    async def fake_dead(url):
        checked.append(url)
        return "leaan" in url  # הראשי (לאן) מת → קופת החי זוכה

    monkeypatch.setattr(resolve, "_event_dead", fake_dead)
    monkeypatch.setattr(
        resolve,
        "search_events",
        _fake_search_list(
            [
                {
                    "title": "עומר אדם - הופעה חיה | 20/09/26 פארק הירקון",
                    "url": "https://www.leaan.co.il/events/omer/9",
                    "platform": "leaan",
                },
                {
                    "title": "עומר אדם הופעות 2026",
                    "url": "https://www.kupat.co.il/show/omer-adam",
                    "platform": "kupat",
                },
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_event_url("עומר אדם"))
    assert res["status"] == "one" and res["platform"] == "kupat"
    assert res["url"] == "https://www.kupat.co.il/show/omer-adam"
    assert "https://www.leaan.co.il/events/omer/9" in checked


def test_all_event_pages_dead_is_none(monkeypatch):
    """כל המועמדים רפאים → none כן (בלי לשלוח את הריצה לדף מת)."""

    async def all_dead(url):
        return True

    monkeypatch.setattr(resolve, "_event_dead", all_dead)
    monkeypatch.setattr(
        resolve,
        "search_events",
        _fake_search_list(
            [
                {
                    "title": "עומר אדם הופעות 2026",
                    "url": "https://www.kupat.co.il/show/omer-adam",
                    "platform": "kupat",
                }
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_event_url("עומר אדם"))
    assert res["status"] == "none"


def test_event_looks_dead_markers():
    """המרקרים אומתו חי (19.7): דף חי מציג כפתור רכישה; דף הרפאים של עומר אדם —
    'הרשמו לעדכונים' בלבד, אפס סימני רכישה. הרגרסיה מהאימות החי: 'הזמנת כרטיסים'
    יושב ב-<title>/og:title של דף הרפאים עצמו — אסור שיחיה אותו."""
    from app.automation.resolve import _event_looks_dead

    assert _event_looks_dead("<div>המופע הסתיים · הרשמו לעדכונים</div>") is True
    assert _event_looks_dead('<a class="btn">לרכישת כרטיסים</a>') is False  # קופת חי
    assert _event_looks_dead("<button>רכישת כרטיסים</button>") is False  # לאן חי
    # דף הרפאים האמיתי: הכותרת מכילה "הזמנת כרטיסים" אבל אין שום כפתור רכישה
    ghost = (
        "<title>עומר אדם הופעות 2026 - הזמנת כרטיסים ישירה להופעה של עומר אדם</title>"
        "<div>הרשמו לעדכונים</div>"
    )
    assert _event_looks_dead(ghost) is True


def test_stale_year_candidate_sinks_to_bottom_of_many(monkeypatch):
    """QA חי הופעות #4 (עדן חסון 2024): מועמד שכותרתו נושאת רק שנה שעברה יורד
    לתחתית רשימת ה-many — הלקוח רואה קודם את המועדים העדכניים."""
    monkeypatch.setattr(resolve, "_event_dead", _all_alive)
    monkeypatch.setattr(
        resolve,
        "search_events",
        _fake_search_list(
            [
                {
                    "title": "עדן חסון הופעות 2024",
                    "url": "https://www.kupat.co.il/show/edenhason-old",
                    "platform": "kupat",
                },
                {
                    "title": "עדן חסון הופעות 2026",
                    "url": "https://www.kupat.co.il/show/edenhason",
                    "platform": "kupat",
                },
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_event_url("עדן חסון"))
    assert res["status"] == "many"
    titles = [c["title"] for c in res["candidates"]]
    assert titles == ["עדן חסון הופעות 2026", "עדן חסון הופעות 2024"]
    # כותרת בלי שנה בכלל אינה "ישנה" — לא זזה
    fresh = resolve._demote_stale_years(
        [
            {"title": "עדן חסון 2024", "url": "u1", "platform": "kupat"},
            {"title": "עדן חסון בקיסריה", "url": "u2", "platform": "kupat"},
        ]
    )
    assert [c["url"] for c in fresh] == ["u2", "u1"]


def test_search_events_venue_enters_query(monkeypatch):
    """venue מחדד את השאילתה לאמן רב-ערים; בלי venue — בלי רווח כפול."""
    queries = []

    async def fake_raw(q):
        queries.append(q)
        return []

    monkeypatch.setattr(resolve, "_brave_raw", fake_raw)
    asyncio.run(resolve.search_events("אייל גולן", "היכל מנורה"))
    asyncio.run(resolve.search_events("אייל גולן"))
    assert queries[0] == "אייל גולן היכל מנורה כרטיסים הופעה"
    assert queries[1] == "אייל גולן כרטיסים הופעה"


# --- באג סלון-יווני 19.7: המלצה בהרצליה → ההזמנה נפתחה על סניף צומת סביון ---
# ההמלצות (Maps) החזירו "סלון יווני הרצליה פיתוח" והשם המלא זרם ל-resolve, אבל:
# (1) שאילתת המותג "סלון" החזירה 12 מקומות והחיתוך [:5] הפיל את סניף הרצליה (מקום 6);
# (2) _match_restaurant בלע את החטאות "הרצליה"+"פיתוח" כי "יווני" (חלק מהמותג) כבר
# "פגע" (hit_any) — ובחר בשקט את הסניף היחיד ששרד: צומת סביון (אור יהודה).

_SALON_TITLES = [
    "סלון יווני צומת סביון אור יהודה",
    "בייקר סלון - Baker Saloon פתח תקווה",
    "כריסטוף סלון יין תל אביב-יפו",
    "סלון ברלין תל אביב-יפו",
    "סופיה סלון יין רמת השרון",
]


def test_match_city_mismatch_never_picks_silently():
    """טוקן עיר מהבקשה שאינו באף מועמד + הכותרת השורדת מכריזה על סניף אחר
    (צומת סביון) → many (אישור לקוח), לעולם לא one שקט על עיר אחרת."""
    for req in ("סלון יווני הרצליה פיתוח", "סלון יווני הרצליה"):
        status, chosen, good = _match_restaurant(req, _SALON_TITLES)
        assert status == "many", req
        assert chosen is None
        assert good == ["סלון יווני צומת סביון אור יהודה"]


def test_match_missed_city_with_clean_branch_title_still_one():
    """רגרסיה על הנחת בזל'ה: עיר שהוחטאה אחרי שטוקן הסניף פגע והכותרת "נקייה"
    (כל מילותיה מכוסות ע"י הבקשה) — עדיין one, לא שאלת סרק."""
    status, chosen, _ = _match_restaurant("רוסטיקו בזל תל אביב", ["רוסטיקו בזל'ה: הזמנת מקום"])
    assert status == "one"
    assert chosen == "רוסטיקו בזל'ה: הזמנת מקום"


def test_match_multiword_brand_correct_branch_wins():
    """כשהסניף הנכון כן במועמדים — טוקן העיר מכריע אליו גם עם מותג דו-מילי,
    ו"פיתוח" החסר (אונטופו קוראת לו "סלון יווני הרצליה") לא מפריע."""
    status, chosen, _ = _match_restaurant(
        "סלון יווני הרצליה פיתוח", ["סלון יווני הרצליה הרצליה", *_SALON_TITLES]
    )
    assert status == "one"
    assert chosen == "סלון יווני הרצליה הרצליה"


def test_ontopo_internal_ranks_requested_branch_before_cap(monkeypatch):
    """הבאג החי: שאילתת המותג מחזירה 6+ מקומות בסדר של אונטופו והסניף המבוקש
    (הרצליה) במקום 6 — הדירוג לפי הבקשה מעלה אותו לראש לפני החיתוך [:5]."""
    venues = [
        ("סלון יווני צומת סביון", "אור יהודה", "1"),
        ("בייקר סלון - Baker Saloon", "פתח תקווה", "2"),
        ("כריסטוף סלון יין", "תל אביב-יפו", "3"),
        ("סלון ברלין", "תל אביב-יפו", "4"),
        ("סופיה סלון יין", "רמת השרון", "5"),
        ("סלון יווני הרצליה", "הרצליה", "6"),
    ]

    def handlers(url, params):
        if url.endswith("/unified_search"):
            if params["terms"] == "סלון":
                return {
                    "found": True,
                    "suggestions": [
                        {"type": "venue", "label": lb, "secondary": sec, "slug": sl}
                        for lb, sec, sl in venues
                    ],
                }
            return {"found": False, "suggestions": []}
        return {"pages": [{"slug": "9" + params["slug"], "content_type": "reservation"}]}

    _fake_internal_http(monkeypatch, handlers)
    cands = asyncio.run(resolve._ontopo_internal("סלון יווני הרצליה פיתוח"))
    assert cands[0]["title"] == "סלון יווני הרצליה הרצליה"
    assert cands[0]["url"] == "https://ontopo.com/he/il/page/96"


def test_resolve_recommend_city_end_to_end(monkeypatch):
    """התרחיש המלא מההמלצות: השם כולל את העיר ("סלון יווני הרצליה פיתוח") —
    כשסניף הרצליה קיים resolve מחזיר אותו (one); כשאינו — many לאישור לקוח.
    לעולם לא URL של סניף עיר-אחרת בשקט."""

    async def internal_with_branch(name):
        return [
            {
                "title": "סלון יווני הרצליה הרצליה",
                "url": "https://ontopo.com/he/il/page/50809918",
                "platform": "ontopo",
            },
            {
                "title": "סלון יווני צומת סביון אור יהודה",
                "url": "https://ontopo.com/he/il/page/71700703",
                "platform": "ontopo",
            },
        ]

    async def not_dead(url):
        return False

    monkeypatch.setattr(resolve, "_ontopo_dead", not_dead)
    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", (internal_with_branch,))
    found = asyncio.run(resolve_reservation_url("סלון יווני הרצליה פיתוח"))
    assert found["status"] == "one"
    assert found["url"] == "https://ontopo.com/he/il/page/50809918"

    async def internal_wrong_city_only(name):
        return [
            {
                "title": "סלון יווני צומת סביון אור יהודה",
                "url": "https://ontopo.com/he/il/page/71700703",
                "platform": "ontopo",
            }
        ]

    monkeypatch.setattr(resolve, "_INTERNAL_SOURCES", (internal_wrong_city_only,))
    found = asyncio.run(resolve_reservation_url("סלון יווני הרצליה פיתוח"))
    assert found["status"] == "many"
    assert found["url"] is None
    assert [c["title"] for c in found["candidates"]] == ["סלון יווני צומת סביון אור יהודה"]
