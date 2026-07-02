"""בדיקת _parse_result — הנתיב הבטיחותי: בסגירה success=True רק אם נסגר באמת (BOOKED)
ולא נעצר בקיר כרטיס (CARD_REQUIRED). ב-recon הצלחה = SUMMARY_REACHED, אף פעם לא 'booked'.
כרטיס מזוהה *רק* לפי marker מפורש (לא substring עברי שתופס שלילה); MISSING:<field> נכשל."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.bu_runner import _build_task, _parse_result  # noqa: E402

_JOB = {
    "url": "https://tabitisrael.co.il/site/גרקו",
    "party_size": 2,
    "date": "2026-06-30",
    "time": "20:00",
    "name": "אלון",
    "email": "a@b.com",
    "phone": "0540000000",
}


def test_build_task_is_platform_agnostic_and_keeps_contract():
    """ה-task עקרוני (לא מתכון נעול ל-Ontopo) אבל שומר על חוזה ה-markers + חוקי הברזל."""
    recon = _build_task({**_JOB, "dry_run": True})
    commit = _build_task({**_JOB, "dry_run": False})
    # פלטפורמה-אגנוסטי: ה-URL והפרטים מוזרקים, ואין כפתור Ontopo קשיח.
    assert _JOB["url"] in recon and "אלון" in recon
    assert "מצאו לי שולחן" not in recon  # לא לקודד כפתור ספציפי של Ontopo
    # חוזה ה-markers נשמר.
    assert "SUMMARY_REACHED" in recon and "CARD_REQUIRED" in recon
    assert "BOOKED" in commit and "CARD_REQUIRED" in commit
    # חוקי ברזל: לא להמציא (MISSING) + לא לסגור ב-recon.
    assert "MISSING" in recon
    assert "אל תלחץ" in recon  # recon עוצר לפני הכפתור הסופי


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


def test_recon_summary_reached_succeeds_not_booked():
    # recon: הגענו למסך הסיכום ועצרנו (בלי כרטיס) → הצלחה, אבל אף פעם לא 'booked'.
    r = _parse_result("עצרתי במסך הסיכום. SUMMARY_REACHED", commit=False)
    assert r["success"] is True
    assert r["booked"] is False
    assert r["card_required"] is False


def test_recon_summary_reached_flags_card_only_via_marker():
    r = _parse_result("מסך הסיכום דורש תשלום. SUMMARY_REACHED CARD_REQUIRED", commit=False)
    assert r["success"] is True
    assert r["booked"] is False
    assert r["card_required"] is True


def test_recon_card_negation_does_not_light_flag():
    # באג 6: 'לא נדרש כרטיס' חייב *לא* להדליק card_required — רק ה-marker מדליק.
    r = _parse_result("לא נדרש כרטיס אשראי. SUMMARY_REACHED", commit=False)
    assert r["card_required"] is False
    assert r["success"] is True


def test_recon_missing_field_fails_and_surfaces_field():
    # באג 3: שדה חובה ריק → כישלון, וה-שדה החסר עולה ב-details.
    r = _parse_result("שדה המייל בטופס חובה וריק. MISSING:email", commit=False)
    assert r["success"] is False
    assert r["booked"] is False
    assert r["missing"] == "email"


def test_commit_missing_field_is_not_a_booking():
    r = _parse_result("חסר מייל. MISSING:email", commit=True)
    assert r["success"] is False
    assert r["booked"] is False
    assert r["missing"] == "email"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
