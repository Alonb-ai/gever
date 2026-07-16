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


# --- קולנוע: _CINEMA_PLATFORMS + resolve_cinema_url (אותו חוזה החזרה) ---

_PLANET_RE = resolve._CINEMA_PLATFORMS[0][1]
_RAVHEN_RE = resolve._CINEMA_PLATFORMS[1][1]
_CC_RE = resolve._CINEMA_PLATFORMS[2][1]


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
        _fake_search(
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
        _fake_search(
            [
                {"title": "סרט אחר לגמרי", "url": "u1", "platform": "planet"},
                {"title": "עוד סרט זר", "url": "u2", "platform": "cinema-city"},
            ]
        ),
    )
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] in ("many", "none") and res["status"] != "one"
    assert res["url"] is None

    monkeypatch.setattr(resolve, "search_cinema", _fake_search([]))
    res = asyncio.run(resolve.resolve_cinema_url("האודיסאה"))
    assert res["status"] == "none" and res["platform"] is None


def test_resolve_cinema_city_only_no_fallback(monkeypatch):
    """רק סינמה סיטי עם match → one בלי fallback (אין פלטפורמה נוספת בתור)."""
    monkeypatch.setattr(
        resolve,
        "search_cinema",
        _fake_search(
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
    monkeypatch.setattr(resolve, "search_cinema", _fake_search(cands))
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
    monkeypatch.setattr(resolve, "search_cinema", _fake_search(list(_HINA_PLANET_ONLY)))
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
    monkeypatch.setattr(resolve, "search_cinema", _fake_search(list(_HINA_PLANET_ONLY)))
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
    monkeypatch.setattr(resolve, "search_cinema", _fake_search(list(_HINA_PLANET_ONLY)))
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
    monkeypatch.setattr(resolve, "search_cinema", _fake_search(real_ravhen))
    res = asyncio.run(resolve.resolve_cinema_url("חינה אמריקאית", chain="rav-hen"))
    assert res["status"] == "one" and res["platform"] == "rav-hen"
    assert _FakeHTTP.calls == []


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
