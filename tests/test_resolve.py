"""בדיקות ל-_match_restaurant (דיסאמביגואציה) ול-_PAGE (חילוץ page id מ-URL)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.ontopo import _match_restaurant  # noqa: E402
from app.automation.resolve import _PAGE  # noqa: E402


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


if __name__ == "__main__":
    test_match_one()
    test_match_many()
    test_match_none()
    test_page_matches()
    test_page_no_match()
    print("ok")
