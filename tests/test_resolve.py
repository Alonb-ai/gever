"""בדיקות ל-_match_restaurant (דיסאמביגואציה), ל-regexים (ontopo/tabit)
ול-resolve_reservation_url (multi-platform, תיעדוף Ontopo › Tabit)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation import resolve  # noqa: E402
from app.automation.ontopo import _match_restaurant  # noqa: E402
from app.automation.resolve import (  # noqa: E402
    _PAGE,
    _TABIT,
    _from_brave,
    _parse_results,
    resolve_reservation_url,
)


def _fake_search(cands):
    async def fake(name, city=""):
        return cands

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


def test_parse_results_tabit_generic_title_gets_slug_and_entities_unescaped():
    # נצפה חי: כותרות Tabit ב-DDG גנריות — שם המסעדה יושב ב-slug (URL-encoded עברית),
    # ו-DDG מחזיר entities (&#x27;). הפרסינג חייב לפענח את שניהם כדי שה-match יעבוד.
    slug = "%D7%92%D7%A8%D7%A7%D7%95-%D7%A4%D7%A8%D7%99%D7%A9%D7%9E%D7%9F"  # גרקו-פרישמן
    body = f"""
    <a href="/l/?uddg=https://www.tabitisrael.co.il/site/{slug}">הזמנת מקום - טאביט</a>
    <a href="/l/?uddg=https://ontopo.com/he/il/page/123">גרקו ביץ&#x27; תל אביב</a>
    """
    out = _parse_results(body)
    tabit = next(c for c in out if c["platform"] == "tabit")
    ontopo = next(c for c in out if c["platform"] == "ontopo")
    assert "גרקו פרישמן" in tabit["title"]  # ה-slug המפוענח נוסף לכותרת הגנרית
    assert ontopo["title"] == "גרקו ביץ' תל אביב"  # &#x27; פוענח


def test_from_brave_extracts_platform_candidates_and_dedups():
    # פורמט התשובה של Brave web search: data["web"]["results"] עם url+title.
    data = {
        "web": {
            "results": [
                {"url": "https://ontopo.com/he/il/page/123", "title": "רוסטיקו בזל: הזמנת מקום"},
                {"url": "https://www.tabitisrael.co.il/site/greco", "title": "הזמנת מקום - טאביט"},
                {"url": "https://ontopo.com/he/il/page/123", "title": "כפול — לא נספר"},
                {"url": "https://example.com/rustico", "title": "אתר לא רלוונטי"},
            ]
        }
    }
    out = _from_brave(data)
    assert [c["platform"] for c in out] == ["ontopo", "tabit"]
    assert out[0]["url"] == "https://ontopo.com/he/il/page/123"
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


def test_resolve_no_candidates_is_none(monkeypatch):
    monkeypatch.setattr(resolve, "search_reservation", _fake_search([]))
    res = asyncio.run(resolve_reservation_url("רוטשילד"))
    assert res["status"] == "none"
    assert res["url"] is None
    assert res["platform"] is None


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
