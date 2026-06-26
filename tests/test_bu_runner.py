"""בדיקת _parse_result — הנתיב הבטיחותי: בסגירה success=True רק אם נסגר באמת (BOOKED)
ולא נעצר בקיר כרטיס (CARD_REQUIRED). ב-recon אף פעם לא 'booked'."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.bu_runner import _parse_result  # noqa: E402


def test_commit_booked_succeeds_with_confirmation():
    r = _parse_result("ההזמנה נסגרה. BOOKED 12345", commit=True)
    assert r["success"] is True
    assert r["booked"] is True
    assert r["confirmation"] == "12345"
    assert r["card_required"] is False


def test_commit_card_wall_is_not_a_booking():
    # גם אם המודל מזכיר 'BOOKED' בטעות — CARD_REQUIRED גובר, לא נרשמת הזמנה.
    r = _parse_result("נדרש כרטיס. CARD_REQUIRED", commit=True)
    assert r["success"] is False
    assert r["booked"] is False
    assert r["card_required"] is True


def test_commit_stuck_is_not_a_booking():
    r = _parse_result("נתקעתי בבורר השעה", commit=True)
    assert r["success"] is False and r["booked"] is False


def test_recon_never_books_but_flags_card():
    r = _parse_result("הגעתי לשלב כרטיס אשראי", commit=False)
    assert r["booked"] is False
    assert r["success"] is True  # recon: הגענו עד הכרטיס
    assert r["card_required"] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
