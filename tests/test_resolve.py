"""בדיקות ל-_match_restaurant (דיסאמביגואציה), ל-_PAGE (חילוץ page id) ול-resolve_ontopo_url."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation import resolve  # noqa: E402
from app.automation.ontopo import _match_restaurant  # noqa: E402
from app.automation.resolve import _PAGE, resolve_ontopo_url  # noqa: E402


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


def test_resolve_no_strong_match_never_picks_arbitrary_one(monkeypatch):
    # שאילתה בלי match חזק (כל המועמדים זרים) — לעולם לא 'one' שרירותי; שואלים את הלקוח.
    async def fake_search(name, city=""):
        return [
            {"title": "רוסטיקו בזל", "url": "https://ontopo.com/he/il/page/1"},
            {"title": "קפה אחר", "url": "https://ontopo.com/he/il/page/2"},
        ]

    monkeypatch.setattr(resolve, "search_ontopo", fake_search)
    res = asyncio.run(resolve_ontopo_url("רוטשילד"))
    assert res["status"] in ("many", "none")
    assert res["status"] != "one"
    assert res["url"] is None


def test_resolve_no_candidates_is_none(monkeypatch):
    async def fake_search(name, city=""):
        return []

    monkeypatch.setattr(resolve, "search_ontopo", fake_search)
    res = asyncio.run(resolve_ontopo_url("רוטשילד"))
    assert res["status"] == "none"
    assert res["url"] is None


if __name__ == "__main__":
    test_match_one()
    test_match_many()
    test_match_one_prefers_real_page_over_deal()
    test_match_none()
    test_page_matches()
    test_page_no_match()
    print("ok")
