"""בדיקת _parse_result — הנתיב הבטיחותי: בסגירה success=True רק אם נסגר באמת (BOOKED)
ולא נעצר בקיר כרטיס (CARD_REQUIRED). ב-recon הצלחה = SUMMARY_REACHED, אף פעם לא 'booked'.
כרטיס מזוהה *רק* לפי marker מפורש (לא substring עברי שתופס שלילה); MISSING:<field> נכשל."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.bu_runner import _build_task, _parse_result, _profile_kwargs  # noqa: E402

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
    # חוזה שורת-הסיום: marker בשורה האחרונה, שמות שדות באנגלית, FAILED קיים.
    assert "השורה האחרונה" in recon and "FAILED" in recon
    assert "MISSING:last_name" in recon  # נצפה חי: שדה שם-משפחה נפרד בטפסים
    # notes מהלקוח (אזור ישיבה וכו') מוזרקות ל-task — סוגרות את לולאת ה-MISSING.
    with_notes = _build_task({**_JOB, "dry_run": True, "notes": "ישיבה בחוץ"})
    assert "ישיבה בחוץ" in with_notes
    assert "העדפות מהלקוח" not in recon  # בלי notes — אין שורה ריקה


def test_markers_only_from_last_line_case_sensitive():
    # R1: פרוזת כישלון באנגלית עם 'booked' באותיות קטנות — לא הזמנה.
    r = _parse_result("The restaurant is fully booked for tonight", commit=True)
    assert r["success"] is False and r["booked"] is False
    # marker באמצע הדיווח (לא בשורה האחרונה) — לא נספר; רק שורת הסיום קובעת.
    r = _parse_result("BOOKED 123\nבסוף לא הושלם", commit=True)
    assert r["booked"] is False
    # שלילה שמצטטת marker בשורה אחרת לא מדליקה recon.
    r = _parse_result("לא הגעתי למסך הסיכום\nנתקעתי בבורר", commit=False)
    assert r["success"] is False


def test_failed_marker_reports_reason():
    r = _parse_result("אין שולחנות פנויים בטווח.\nFAILED:no_availability", commit=False)
    assert r["success"] is False
    assert r["failed"] == "no_availability"
    r = _parse_result("נדרשת התחברות. FAILED:login_required", commit=True)
    assert r["success"] is False and r["booked"] is False
    assert r["failed"] == "login_required"


def test_perk_lines_collected_for_customer():
    """PERK: מהדף (הנחה/מבצע) נאסף ועובר להודעת הלקוח; בלי PERK — ריק."""
    final = "מילאתי הכל.\nPERK: 10% הנחה על התפריט בשעה הזאת\nSUMMARY_REACHED 14:30"
    r = _parse_result(final, commit=False)
    assert r["perk"] == "10% הנחה על התפריט בשעה הזאת"
    assert r["time"] == "14:30"
    assert _parse_result("SUMMARY_REACHED", commit=False)["perk"] == ""
    # ברירת מחדל מסומנת = בחירה — ההנחיה קיימת ב-task
    assert "ברירת מחדל" in _build_task({**_JOB, "dry_run": True})
    assert "PERK" in _build_task({**_JOB, "dry_run": True})


def test_browserbase_profile_keeps_browser_alive_for_resume():
    """נצפה חי: browser-use סגר את הדפדפן בסוף הריצה והרג את סשן ה-keepAlive —
    ה-resume נפל לריצה טרייה במקום להמשיך מאותו מסך. על Browserbase חובה keep_alive."""
    bb = _profile_kwargs({"cdp_url": "wss://connect", "headless": True})
    assert bb["keep_alive"] is True and bb["cdp_url"] == "wss://connect"
    # local dev: בלי keep_alive — שלא יישאר Chrome פתוח אחרי הריצה.
    local = _profile_kwargs({"chrome_path": "/Applications/Chrome"})
    assert "keep_alive" not in local
    # record_dir ריק = בלי הקלטה (ה-fallback ל-/tmp כבר עקץ אותנו פעם).
    assert "record_video_dir" not in _profile_kwargs({"cdp_url": "w", "record_dir": ""})


def test_missing_choice_carries_real_page_options():
    """עצירה על בחירה כפויה מדווחת OPTIONS: עם האפשרויות האמיתיות מהדף — גבר מציג
    אותן ללקוח כרשימה במקום 'בפנים/בחוץ/בר' גנרי (בקשת UX מהשטח, ריצת A.K.A)."""
    final = "האתר דורש אזור ישיבה.\nOPTIONS: בפנים | בר גבוה | מרפסת מעשנים\nMISSING:seating_area"
    r = _parse_result(final, commit=False)
    assert r["missing"] == "seating_area"
    assert r["options"] == ["בפנים", "בר גבוה", "מרפסת מעשנים"]
    assert _parse_result("MISSING:email", commit=False)["options"] == []
    # ההוראה קיימת ב-task: שורת OPTIONS + חוק אנטי-התלבטות
    task = _build_task({**_JOB, "dry_run": True})
    assert "OPTIONS:" in task and "אל תתלבט" in task


def test_bare_missing_colon_does_not_crash():
    r = _parse_result("חסר שדה. MISSING:", commit=False)
    assert r["success"] is False
    assert r["missing"] == "unknown"


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


def test_recon_reports_actual_chosen_time():
    # 20:30 היה תפוס וה-agent בחר 21:00 → השעה נחלצת כדי שגבר יציע אותה ללקוח.
    r = _parse_result("נבחרו 2 סועדים ל-7.7. SUMMARY_REACHED 21:00", commit=False)
    assert r["success"] is True
    assert r["time"] == "21:00"
    # בלי שעה בשורת הסיום — ריק, לא מומצא.
    assert _parse_result("SUMMARY_REACHED", commit=False)["time"] == ""
    # התקרה החדשה (±30 דק') מופיעה ב-task.
    assert "30 דקות" in _build_task({**_JOB, "dry_run": True})


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


# --- קולנוע: _build_cinema_task (דרך _build_task) + seats ב-_parse_result ---

_CJOB = {
    "task_type": "cinema",
    "url": "https://www.planetcinema.co.il/films/the-odyssey/7460s2r",
    "movie": "האודיסאה",
    "city": "ראשון לציון",
    "party_size": 2,
    "date": "15.7",
    "time": "20:00",
    "name": "אלון",
    "email": "a@b.com",
    "phone": "0540000000",
}


def test_cinema_task_keeps_contract_and_is_principled_not_recipe():
    """ה-task של קולנוע: markers קיימים בלבד (אין חוזה חדש), אין שמות כפתורים,
    וכל חוקי הקולנוע (סניף לפי עיר, חלון 90 דק', פורמט, מושבים) נוכחים."""
    recon = _build_task({**_CJOB, "dry_run": True})
    commit = _build_task({**_CJOB, "dry_run": False})
    assert _CJOB["url"] in recon and "האודיסאה" in recon and "ראשון לציון" in recon
    # חוזה ה-markers הקיים — לא ממציאים חדש
    assert "SUMMARY_REACHED" in recon and "CARD_REQUIRED" in recon
    assert "MISSING" in recon and "FAILED" in recon and "URL:" in recon
    assert "BOOKED" in commit
    # עקרוני, לא מתכון: בלי שמות כפתורים של אתר ספציפי
    assert "מצאו לי שולחן" not in recon and "הזמנת כרטיסים אונליין" not in recon
    # recon עוצר לפני הסוף + המשפט הייחודי לקולנוע (קיר התשלום = מסך הסיכום)
    assert "אל תלחץ" in recon
    assert "מסך התשלום הוא מסך הסיכום" in recon and "מסך התשלום הוא מסך הסיכום" in commit
    # חוקי קולנוע
    assert "FAILED:no_cinema_in_city" in recon
    assert "90 דקות" in recon
    assert "MISSING:format" in recon and "OPTIONS:" in recon
    assert "MISSING:seats" in recon
    assert "אל תתלבט" in recon  # כלל האנטי-התלבטות המשותף
    # שורת הסיום המורחבת: שעה | מושבים
    assert "SUMMARY_REACHED 21:30 | שורה 7 מושבים 11,12" in recon
    # לקחי iter 2 (ריצה חיה): SVG — לבדוק מבנה לפני script, ואימות אבטחה — סבלנות
    assert "SVG" in recon and "אל תנחש" in recon
    assert "אימות אבטחה" in recon


def test_cinema_task_seat_default_is_declared_choice():
    """ברירת המחדל למושבים (החריג היחיד לכלל 'לא בוחרים') מוצהרת ב-task:
    צמודים, אמצע האולם, לא שורה ראשונה; תוספת תשלום → עצירה."""
    recon = _build_task({**_CJOB, "dry_run": True})
    assert "צמודים" in recon and "אמצע האולם" in recon and "שורה ראשונה" in recon
    assert "תוספת תשלום" in recon


def test_cinema_task_injects_notes_and_contact():
    """notes ('שורה אחורית', 'בלי תלת-ממד') סוגרות בחירות מראש — מוזרקות כמו במסעדות."""
    with_notes = _build_task({**_CJOB, "dry_run": True, "notes": "בלי תלת-ממד"})
    assert "בלי תלת-ממד" in with_notes and "העדפות מהלקוח" in with_notes
    bare = _build_task({**_CJOB, "dry_run": True})
    assert "העדפות מהלקוח" not in bare
    assert "אלון" in bare and "a@b.com" in bare


def test_cinema_resume_continues_frozen_screen():
    """resume (pause-resume): לא מנווטים מחדש — ה-URL לא מופיע, ה-recap כן."""
    t = _build_task({**_CJOB, "dry_run": True, "resume": {"recap": "עצרתי על בחירת פורמט"}})
    assert "אל תנווט" in t and "עצרתי על בחירת פורמט" in t
    assert _CJOB["url"] not in t


def test_parse_result_extracts_seats_after_pipe():
    """קולנוע: הטקסט אחרי | בשורה האחרונה → seats; השעה נתפסת כרגיל."""
    final = "נבחר פלאנט ראשון לציון.\nSUMMARY_REACHED 21:30 | שורה 7 מושבים 11,12"
    r = _parse_result(final, commit=False)
    assert r["success"] is True
    assert r["time"] == "21:30"
    assert r["seats"] == "שורה 7 מושבים 11,12"


def test_parse_result_seats_with_card_wall_marker():
    """התוצאה הצפויה בכל ריצת קולנוע מוצלחת: SUMMARY_REACHED + מושבים + CARD_REQUIRED
    באותה שורה — המושבים נחלצים נקיים, בלי ה-marker."""
    final = "URL: https://x/checkout\nSUMMARY_REACHED 21:30 | שורה 7 מושבים 11,12 CARD_REQUIRED"
    r = _parse_result(final, commit=False)
    assert r["success"] is True and r["card_required"] is True
    assert r["seats"] == "שורה 7 מושבים 11,12"
    assert r["page_now"] == "https://x/checkout"


def test_parse_result_mixed_markers_live_iter1_regression():
    """רגרסיה חיה (איטרציה 1, פלאנט ראשל"צ): ה-agent ערבב שני markers בשורת הסיום —
    'SUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 / MISSING:last_name'. MISSING חייב
    לנצח (success=False, השדה נקלט), וה-seats נחלץ נקי בלי זנב ה-marker."""
    final = "הגעתי לטופס הפרטים.\nSUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 / MISSING:last_name"
    r = _parse_result(final, commit=False)
    assert r["success"] is False
    assert r["missing"] == "last_name"
    assert r["time"] == "19:30"
    assert r["seats"] == "שורה 5 מושבים 7,8"


def test_parse_result_no_pipe_means_no_seats_restaurant_regression():
    """מסעדות לא פולטות | בשורת הסיום — seats ריק, שום שדה אחר לא זז."""
    r = _parse_result("SUMMARY_REACHED 21:00", commit=False)
    assert r["seats"] == "" and r["time"] == "21:00" and r["success"] is True
    # | בשורת OPTIONS (לא השורה האחרונה) לא הופך למושבים
    r = _parse_result("OPTIONS: רגיל | IMAX | 4DX\nMISSING:format", commit=False)
    assert r["seats"] == "" and r["missing"] == "format"
    assert r["options"] == ["רגיל", "IMAX", "4DX"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
