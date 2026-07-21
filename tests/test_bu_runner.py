"""בדיקת _parse_result — הנתיב הבטיחותי: בסגירה success=True רק אם נסגר באמת (BOOKED)
ולא נעצר בקיר כרטיס (CARD_REQUIRED). ב-recon הצלחה = SUMMARY_REACHED, אף פעם לא 'booked'.
כרטיס מזוהה *רק* לפי marker מפורש (לא substring עברי שתופס שלילה); MISSING:<field> נכשל."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.bu_runner import (  # noqa: E402
    PAGE_READY_TIMEOUT_S,
    _build_task,
    _il_tz_hook,
    _make_llm,
    _parse_result,
    _profile_kwargs,
    _shorten_page_readiness,
)

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


def test_build_task_forbids_search_engines_and_fails_fast_on_server_error():
    """ספירלת גרקו-טאביט (נצפה חי 16.7, טאביט במפולת CloudFront 503): הסוכן בזבז
    10 צעדים ו-6.5 דק' על חיפושי גוגל/DDG והזיית 'URL קטוע' במקום להיכשל מהר.
    ה-task חייב לאסור מנועי חיפוש ולהכתיב רענון-אחד-ואז-broken_page."""
    task = _build_task({**_JOB, "dry_run": True})
    assert "מנוע חיפוש" in task and "אסור" in task
    assert "רענן פעם אחת" in task
    assert "FAILED:broken_page מיד" in task


def test_restaurant_task_click_sequence_rule_in_both_variants():
    """ממצא בטא #4 (אונטופו של גאיג'ין, 2 ריצות): שעה/תאריך נראו זמינים אך הלחיצות
    לא הובילו למעבר דף — הנחיית רצף-העכבר (אלמנט לחיץ ולא עטיפה, mousedown/mouseup/
    click, אזור אחר) חלה גם על שני נוסחי המסעדות (חוק-שעה רגיל וגמיש)."""
    for extra in ({}, {"time_flex": True}):
        task = _build_task({**_JOB, "dry_run": True, **extra})
        assert "mousedown/mouseup/click" in task
        assert "האלמנט הלחיץ" in task and "עטיפה" in task and "אזור אחר" in task


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


def test_markerless_final_report_is_browser_error():
    # ev iter 1 (ריצה חיה מול לאן): סשן Browserbase מת באמצע (keepalive→410) וה-agent
    # נעצר בלי שורת סיום — final ריק. חייב לצאת failed=browser_error, לא תוצאה ריקה.
    for commit in (False, True):
        r = _parse_result("", commit=commit)
        assert r["success"] is False
        assert r["failed"] == "browser_error"
    # רווחים בלבד = אותו דין.
    assert _parse_result("   \n ", commit=False)["failed"] == "browser_error"
    # ev4 (ריצה חיה מול קופת): הדפדפן נהרג באמצע (sweep) ו-history.final_result()
    # החזיר את הד הפעולה האחרונה — לא-ריק ובלי marker. גם זה browser_error, לא שתיקה.
    for garbage in ("Waited for 5 seconds", "נתקעתי בבורר"):
        r = _parse_result(garbage, commit=False)
        assert r["success"] is False
        assert r["failed"] == "browser_error"
    # marker אמיתי בשורה האחרונה — הרשת לא נדרכת.
    assert _parse_result("הכל תקין\nCARD_REQUIRED", commit=False)["failed"] == ""
    assert _parse_result("BOOKED 42", commit=True)["failed"] == ""


def test_markerless_with_options_is_missing_not_browser_error():
    # QA הופעות 21.7 (עדן בן זקן, ערד): ה-agent הגיע לקטגוריות המחיר, מנה אותן
    # ב-OPTIONS:, ועצר לשאלת הלקוח — אבל שורת ה-marker האחרונה נחתכה במגבלת אורך
    # הפלט. שורת OPTIONS: = ראיה שהדפדפן חי בקיר-בחירה (דפדפן מת לעולם לא פולט
    # OPTIONS), אז שחזור כ-MISSING:price_category, לא browser_error שקרי.
    final = (
        "נמצא מועד אחד להופעה בערד. המופע בעמידה.\n"
        "ישנן מספר קטגוריות מחיר, אך לא צוינה העדפה.\n"
        'OPTIONS: כרטיס כניסה 129 ש"ח | תושב ערד 85 ש"ח'
    )
    for commit in (False, True):
        r = _parse_result(final, commit=commit)
        assert r["failed"] == ""
        assert r["missing"] == "price_category"
        assert r["missing_fields"] == ["price_category"]
        assert r["success"] is False
        assert r["options"] == ['כרטיס כניסה 129 ש"ח', 'תושב ערד 85 ש"ח']
    # markerless בלי OPTIONS = דפדפן שמת → נשאר browser_error (הרשת לא נחלשה).
    assert _parse_result("Waited for 5 seconds", commit=False)["failed"] == "browser_error"
    # OPTIONS *עם* marker אמיתי — לא נכנס למסלול השחזור, ה-marker קובע.
    r = _parse_result("OPTIONS: א | ב\nMISSING:seats", commit=False)
    assert r["failed"] == "" and r["missing"] == "seats"


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


def test_make_llm_picks_provider_by_model_prefix(monkeypatch):
    """השוואת מודלים: קידומת שם המודל בוחרת ספק — bu-/claude-/gpt-, וכל השאר Google
    (המסלול הקיים, אפס שינוי התנהגות). browser_use לא מותקן ב-.venv — מוזרק fake."""
    import types

    class _Chat:
        def __init__(self, model=None):
            self.model = model

    llm_mod = types.ModuleType("browser_use.llm")
    for name in ("ChatGoogle", "ChatBrowserUse", "ChatAnthropic", "ChatOpenAI"):
        setattr(llm_mod, name, type(name, (_Chat,), {}))
    pkg = types.ModuleType("browser_use")
    pkg.llm = llm_mod
    monkeypatch.setitem(sys.modules, "browser_use", pkg)
    monkeypatch.setitem(sys.modules, "browser_use.llm", llm_mod)

    assert type(_make_llm("bu-2-0")).__name__ == "ChatBrowserUse"
    assert type(_make_llm("claude-haiku-4-5")).__name__ == "ChatAnthropic"
    assert type(_make_llm("gpt-5.4-mini")).__name__ == "ChatOpenAI"
    llm = _make_llm("gemini-3-flash-preview")
    assert type(llm).__name__ == "ChatGoogle"
    assert llm.model == "gemini-3-flash-preview"  # המודל עובר כמו שהוא, בלי עיבוד


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
    # לקח סבב סינמה סיטי (ריצה חיה 15.07.26): קליק תכנותי על SVG לא נקלט —
    # צריך רצף אירועי עכבר על אלמנט ה-hit-area (8 צעדי ניסוי-וטעייה בלי הרמז)
    assert "hit-area" in recon and "mousedown/mouseup/click" in recon
    # QA 19.7 (הוט): evaluate סינתטי נדחה — אחרי שני כשלונות עוברים לקליק קואורדינטות אמיתי
    assert "coordinate_x" in recon
    # פרוב 21.7: המתכון המוכח — שיגור רצף אירועים על elementFromPoint + אימות המונה
    assert "elementFromPoint" in recon
    # אימות E2E 21.7: reCAPTCHA אחרי בחירת מושבים = קיר-כרטיס (מסירה ללקוח), לא כישלון
    assert "reCAPTCHA" in recon
    # שני חוקי הברזל הרוחביים (189241a במסעדות) חלים גם על הקולנוע (⚠ מה-ledger)
    assert "מנוע חיפוש" in recon and "FAILED:broken_page מיד" in recon
    # לקח ההופעות (e60f9d0): תבניות "אזלו" נסתרות לא קובעות זמינות — רק מה שמוצג
    assert "תבניות טקסט נסתרות" in recon and "חזותית" in recon


def test_cinema_task_seat_default_is_declared_choice():
    """ברירת המחדל למושבים (החריג היחיד לכלל 'לא בוחרים') מוצהרת ב-task:
    צמודים, אמצע האולם, לא שורה ראשונה; תוספת תשלום → עצירה."""
    recon = _build_task({**_CJOB, "dry_run": True})
    assert "צמודים" in recon and "אמצע האולם" in recon and "שורה ראשונה" in recon
    assert "תוספת תשלום" in recon


def test_cinema_task_hot_cinema_addendum_is_conditional():
    """הוט סינמה: עובדות ה-recon (דומיין כרטוס נפרד, החזקת מושבים 9 דקות) נכנסות
    ל-task רק כש-platform="hot-cinema" — רשתות אחרות לא רואות אותן."""
    hot = _build_task({**_CJOB, "dry_run": True, "platform": "hot-cinema"})
    assert "tickets.hotcinema.co.il" in hot and "9 דקות" in hot
    # בורר-התאריך של דף הסרט הוא shadow DOM מקונן (QA חי 22.7): הקלדה/סקריפט לא נקלטים,
    # רק לחיצה→לוח-שנה. השורה נכנסת רק להוט.
    assert "shadow DOM" in hot and "לוח-שנה" in hot
    other = _build_task({**_CJOB, "dry_run": True, "platform": "planet"})
    assert "tickets.hotcinema.co.il" not in other and "9 דקות" not in other
    assert "shadow DOM" not in other
    assert "hotcinema" not in _build_task({**_CJOB, "dry_run": True})


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


def test_parse_result_seats_trailing_pipe_live_regression():
    """רגרסיה חיה (ריצת אמת): ה-agent שם | גם לפני ה-marker —
    'SUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 | CARD_REQUIRED' — והלקוח קיבל
    'שורה 5 מושבים 7,8 |' עם פייפ יתום בסוף. תווי ההפרדה נחתכים מהקצוות."""
    final = "URL: https://x/checkout\nSUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 | CARD_REQUIRED"
    r = _parse_result(final, commit=False)
    assert r["success"] is True and r["card_required"] is True
    assert r["seats"] == "שורה 5 מושבים 7,8"
    # וגם פייפ יתום בלי marker אחריו (agent שסיים את השורה ב-|)
    r = _parse_result("SUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 |", commit=False)
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


# --- הופעות: _build_concert_task (דרך _build_task) — אותם markers, מחיר במקטע ה-| ---

_EJOB = {
    "task_type": "events",
    "url": "https://www.leaan.co.il/events/kobi-peretz/5514",
    "artist": "קובי פרץ",
    "venue": "היכל מנורה",
    "party_size": 2,
    "date": "11.08",
    "name": "אלון",
    "email": "a@b.com",
    "phone": "0540000000",
}


def test_concert_task_keeps_contract_and_event_rules():
    """ה-task של הופעות: markers קיימים בלבד, וכל חוקי ההופעות נוכחים — תאריך=אירוע
    בדיד (MISSING:date+OPTIONS), קטגוריית מחיר, sold_out, ת"ז, שורת-סיום-אחת."""
    recon = _build_task({**_EJOB, "dry_run": True})
    commit = _build_task({**_EJOB, "dry_run": False})
    assert _EJOB["url"] in recon and "קובי פרץ" in recon and "היכל מנורה" in recon
    # חוזה ה-markers הקיים — לא ממציאים חדש (אין PRICE: וכדומה)
    assert "SUMMARY_REACHED" in recon and "CARD_REQUIRED" in recon
    assert "MISSING" in recon and "FAILED" in recon and "URL:" in recon
    assert "BOOKED" in commit and "PRICE:" not in recon
    # חוקי הופעות
    assert "MISSING:date" in recon and "OPTIONS:" in recon
    assert "MISSING:price_category" in recon
    assert "FAILED:sold_out" in recon and "FAILED:no_event_in_city" in recon
    # לקח ריצה חיה (ev2): תבניות "אזלו" נסתרות ב-SPA לא קובעות sold_out — רק מה שמוצג
    assert "תבניות טקסט נסתרות" in recon and "חזותית" in recon
    assert "MISSING:id_number" in recon and "לעולם אל תמציא" in recon
    assert "MISSING:seats" in recon
    assert "FAILED:login_required" in recon
    # אין שעה מבוקשת בהופעות — השעה נגזרת מהמופע (אין ±90 דק')
    assert "90 דקות" not in recon
    # כלל שורת-סיום-אחת: MISSING/FAILED לבדה, בלי SUMMARY_REACHED לפניה
    assert "בלי SUMMARY_REACHED לפניה" in recon
    # השורה המורחבת: שעה | קטגוריה+מושבים+מחיר
    assert 'SUMMARY_REACHED 21:00 | פרטר שורה 12 מושבים 7,8 — סה"כ 640 ש"ח' in recon
    # לקחי הקולנוע מועתקים מילה-במילה: SVG hit-area + אימות אבטחה + מפה היררכית
    assert "hit-area" in recon and "mousedown/mouseup/click" in recon
    # QA 19.7 (הוט): evaluate סינתטי נדחה — אחרי שני כשלונות עוברים לקליק קואורדינטות אמיתי
    assert "coordinate_x" in recon
    # פרוב 21.7: המתכון המוכח — שיגור רצף אירועים על elementFromPoint + אימות המונה
    assert "elementFromPoint" in recon
    # אימות E2E 21.7: reCAPTCHA אחרי בחירת מושבים = קיר-כרטיס (מסירה ללקוח), לא כישלון
    assert "reCAPTCHA" in recon
    assert "אימות אבטחה" in recon
    assert "גוש" in recon  # אולמות גדולים — בחירת גוש/מפלס לפני מפת המושבים
    # קיר התשלום הוא הסוף הטבעי (כרטיס דיגיטלי) — כמו קולנוע
    assert "מסך התשלום הוא מסך הסיכום" in recon and "מסך התשלום הוא מסך הסיכום" in commit


def test_concert_task_sold_out_date_offers_alt_dates():
    """QA חי הופעות #5 (זמינות-תחילה): המועד המבוקש אזל אבל יש מועדים אחרים בדף →
    MISSING:date + OPTIONS (הצעה ללקוח), לא כישלון יבש."""
    recon = _build_task({**_EJOB, "dry_run": True})
    flat = " ".join(recon.split())
    assert "המועד המבוקש אזל אבל הדף מציג מועדים אחרים שעדיין זמינים" in flat
    assert "MISSING:date עם שורת OPTIONS: של המועדים שכן זמינים" in flat


def test_concert_task_no_upcoming_dates_not_false_sold_out():
    """QA חי הופעות #3: דף רפאים בלי מועדים דווח sold_out כוזב — עכשיו יש
    FAILED:no_upcoming_dates לדף בלי אף מועד לרכישה, ו-sold_out רק כשמוצג חזותית."""
    recon = _build_task({**_EJOB, "dry_run": True})
    flat = " ".join(recon.split())
    assert "FAILED:no_upcoming_dates" in flat
    assert 'טופס "הרשמו לעדכונים" בלבד' in flat
    assert "FAILED:sold_out רק כשמוצג חזותית" in flat


def test_concert_task_foreign_iframe_rule():
    """QA חי הופעות #1 (לאן, seatmap.vivenu.com): מפת המושבים חיה ב-iframe דומיין-זר
    (OOPIF) — evaluate/JS רץ על הדף החיצוני ומחזיר ריק תמיד; הריצה החיה שרפה 19 צעדי
    evaluate ריקים. החוק: בלי JS על המפה, קליקים בקואורדינטות בלבד, ושני evaluate
    ריקים = עצירה כנה."""
    recon = _build_task({**_EJOB, "dry_run": True})
    flat = " ".join(recon.split())
    assert "iframe של דומיין אחר" in flat
    assert "יחזיר ריק" in flat
    assert "שני ניסיונות evaluate שחזרו ריקים = עצור בכנות מיד" in flat
    assert "MISSING:price_category עם שורת OPTIONS:" in flat
    assert "FAILED:broken_page אם המפה לא מציגה כלום" in flat


def test_profile_pins_cross_origin_iframes():
    """OOPIF (מפות מושבים של הופעות) תלוי ב-cross_origin_iframes — ב-0.13.1 זו ברירת
    המחדל, אבל מקובע מפורשות כדי ששדרוג browser-use לא יכבה אותו בשקט."""
    assert _profile_kwargs({"headless": True})["cross_origin_iframes"] is True
    assert _profile_kwargs({"cdp_url": "wss://x"})["cross_origin_iframes"] is True


def test_concert_task_sms_code_wall_is_missing_not_failed():
    """קיר קוד-SMS של קופת (סבב 4) = עצירת לקוח-בלולאה: MISSING:sms_code והסשן
    ממתין — לא FAILED:login_required, גם כשהקיר הוא חלק ממסך התחברות; קוד שנדחה →
    MISSING:sms_code שוב, בלי לנחש."""
    recon = _build_task({**_EJOB, "dry_run": True})
    assert "MISSING:sms_code" in recon
    assert "לעולם אל תמציא ואל תנחש קוד" in recon
    flat = " ".join(recon.split())
    assert "אל תדווח עליו FAILED:login_required" in flat
    assert "MISSING:sms_code שוב" in recon
    # login_required נשאר לקירות חשבון אמיתיים (בלי רכישה כאורח)
    assert "FAILED:login_required" in recon


def test_concert_task_optional_date_and_venue():
    """בלי date — ה-task לא ממציא תאריך ומנחה MISSING:date על ריבוי מועדים;
    בלי venue — אין ' ב-' ריק בכותרת המשימה."""
    bare = _build_task({**_EJOB, "date": "", "venue": "", "dry_run": True})
    assert "בתאריך" not in bare.split("\n")[2]  # שורת המשימה בלי זנב תאריך ריק
    assert "לא צוין" in bare  # date_line מציין שאין תאריך מבוקש
    assert "MISSING:date" in bare


def test_concert_task_injects_notes_and_contact():
    """העדפת מחיר/ישיבה ('הכי זול') מגיעה ב-notes — _notes_line הקיים, בלי מנגנון חדש."""
    with_notes = _build_task({**_EJOB, "dry_run": True, "notes": "הכי זול"})
    assert "הכי זול" in with_notes and "העדפות מהלקוח" in with_notes
    bare = _build_task({**_EJOB, "dry_run": True})
    assert "העדפות מהלקוח" not in bare
    assert "אלון" in bare and "a@b.com" in bare


def test_concert_resume_continues_frozen_screen():
    """resume: intro של המשך — בלי 'התחל מהכתובת', עם ה-recap."""
    t = _build_task({**_EJOB, "dry_run": True, "resume": {"recap": "עצרתי על בחירת קטגוריה"}})
    assert "אל תנווט" in t and "עצרתי על בחירת קטגוריה" in t
    assert "התחל מהכתובת" not in t and _EJOB["url"] not in t


def test_parse_result_concert_price_lives_in_pipe_section():
    """אפס שינוי ב-_parse_result: המחיר חי במקטע ה-| — seats מכיל קטגוריה+מחיר,
    time נתפס, card_required נדלק מה-marker."""
    final = 'SUMMARY_REACHED 21:00 | פרטר שורה 12 מושבים 7,8 — סה"כ 640 ש"ח CARD_REQUIRED'
    r = _parse_result(f"נבחר מופע 11/08.\n{final}", commit=False)
    assert r["success"] is True
    assert r["time"] == "21:00"
    assert r["card_required"] is True
    seats = r["seats"]
    assert "640" in seats and "פרטר" in seats
    assert "CARD_REQUIRED" not in seats and "SUMMARY_REACHED" not in seats


def test_parse_result_concert_options_with_prices():
    """OPTIONS של קטגוריות מחיר → שתי אופציות עם המחירים כלשונן."""
    r = _parse_result('OPTIONS: פרטר 320 ש"ח | יציע 180 ש"ח\nMISSING:price_category', commit=False)
    assert r["missing"] == "price_category"
    assert r["options"] == ['פרטר 320 ש"ח', 'יציע 180 ש"ח']


def test_parse_result_concert_missing_date_with_venues():
    """MISSING:date + OPTIONS של מועדים (כולל עיר/היכל) — הרשימה שהלקוח יקבל."""
    r = _parse_result(
        'OPTIONS: 11/08 היכל מנורה ת"א | 15/08 היכל הפיס חיפה\nMISSING:date', commit=False
    )
    assert r["missing"] == "date"
    assert r["options"] == ['11/08 היכל מנורה ת"א', "15/08 היכל הפיס חיפה"]


# --- _il_tz_hook: שעון ישראל לדפדפן (נצפה חי ev3: לאן הציגה 13:00 EDT למופע של 20:00 IL) ---


class _FakeCDPSession:
    """מדמה CDPSession של browser-use: מקליט קריאות Emulation/Page."""

    def __init__(self, calls: list, fail: bool = False):
        self.session_id = "sess-1"
        self._calls = calls
        self._fail = fail
        outer = self

        class _Emulation:
            async def setTimezoneOverride(self, params, session_id=None):
                if outer._fail:
                    raise RuntimeError("cdp down")
                outer._calls.append(("tz", params["timezoneId"], session_id))

        class _Page:
            async def reload(self, session_id=None):
                outer._calls.append(("reload", session_id))

        class _Send:
            Emulation = _Emulation()
            Page = _Page()

        class _Client:
            send = _Send()

        self.cdp_client = _Client()


class _FakeAgent:
    def __init__(self, calls: list, fail: bool = False):
        outer_session = _FakeCDPSession(calls, fail=fail)

        class _BS:
            async def get_or_create_cdp_session(self):
                return outer_session

        self.browser_session = _BS()


def test_il_tz_hook_sets_israel_tz_and_reloads_once():
    """ריצה טרייה: כל צעד מזריק Asia/Jerusalem; reload רק בצעד הראשון (הדף הראשון
    כבר רונדר בשעון חו"ל לפני ה-override)."""
    import asyncio

    calls: list = []
    hook = _il_tz_hook(resume=False)
    agent = _FakeAgent(calls)
    asyncio.run(hook(agent))
    asyncio.run(hook(agent))
    assert calls == [
        ("tz", "Asia/Jerusalem", "sess-1"),
        ("reload", "sess-1"),
        ("tz", "Asia/Jerusalem", "sess-1"),
    ]


def test_il_tz_hook_resume_never_reloads():
    """resume: המסך החי מחזיק בחירות (מושבים) — reload היה מוחק אותן."""
    import asyncio

    calls: list = []
    hook = _il_tz_hook(resume=True)
    agent = _FakeAgent(calls)
    asyncio.run(hook(agent))
    asyncio.run(hook(agent))
    assert all(c[0] == "tz" for c in calls) and len(calls) == 2


def test_il_tz_hook_swallows_cdp_failure_and_retries_reload():
    """best-effort: כשל CDP לא מפיל את הריצה, וה-reload החד-פעמי עוד ינוסה בצעד הבא."""
    import asyncio

    calls: list = []
    hook = _il_tz_hook(resume=False)
    asyncio.run(hook(_FakeAgent(calls, fail=True)))  # נופל בשקט
    assert calls == []
    asyncio.run(hook(_FakeAgent(calls)))  # הצעד הבא: tz + reload (first עוד דלוק)
    assert calls == [("tz", "Asia/Jerusalem", "sess-1"), ("reload", "sess-1")]


# --- זירוז 17.7: חוק המחסום העיקש, דיאטת צעדים, וקיצור ה-Page readiness ---


def test_stubborn_obstacle_rule_in_both_verticals():
    """חוק המחסום העיקש: אותו מחסום גם אחרי שתי גישות שונות → FAILED מיד, בלי עוד
    ניסיונות (שתי ריצות broken_page בהופעות שרפו 39 צעדים ו-13+ דק' כל אחת)."""
    for t in (_build_task({**_JOB, "dry_run": True}), _build_task({**_CJOB, "dry_run": True})):
        assert "שתי" in t and "גישות שונות" in t
        assert "אל תמשיך לנסות" in t


def test_step_diet_in_both_verticals_keeps_guardrails():
    """דיאטת צעדים: שרשור פעולות באותו צעד, בלי גלילת-חיפוש לאלמנט שנראה, בלי וידוא
    חוזר על מה שאושר — והכוונת היעילות לא מבטלת את חוקי הברזל והעצירות."""
    rest = _build_task({**_JOB, "dry_run": True})
    cine = _build_task({**_CJOB, "dry_run": True})
    conc = _build_task({**_EJOB, "dry_run": True})  # QA חי הופעות #6: הדיאטה חלה גם שם
    for t in (rest, cine, conc):
        assert "באותו צעד" in t  # שרשור פעולות
        assert "שכבר נראה על המסך" in t  # בלי scroll-חיפוש
        assert "וידוא חוזרים" in t  # בלי צעדי-וידוא כפולים
        assert "אף פעם לא מבטל את חוקי הברזל" in t  # יעילות ≠ דילוג על בדיקות אמת
    # אימות-האמת המהותי (השעה שנבחרה בפועל) נשאר במסעדות — הדיאטה לא מחקה אותו
    assert "ודא שמה שנבחר בפועל" in rest


def test_shorten_page_readiness_patches_default_only(monkeypatch):
    """browser-use 0.13.1: אין שדה BrowserProfile ל-readiness — הערך קשיח (8 שנ'
    cross-domain) בתוך BrowserSession._navigate_and_wait. העטיפה מזריקה 3 שנ' רק
    כשלא הועבר timeout מפורש; מפורש — מכובד. (browser_use לא מותקן ב-.venv — fake.)"""
    import asyncio
    import types

    calls: list = []

    class _BS:
        async def _navigate_and_wait(
            self, url, target_id, timeout=None, wait_until="load", nav_timeout=None
        ):
            calls.append((url, timeout, wait_until, nav_timeout))

    sess_mod = types.ModuleType("browser_use.browser.session")
    sess_mod.BrowserSession = _BS
    browser_mod = types.ModuleType("browser_use.browser")
    browser_mod.session = sess_mod
    pkg = types.ModuleType("browser_use")
    pkg.browser = browser_mod
    monkeypatch.setitem(sys.modules, "browser_use", pkg)
    monkeypatch.setitem(sys.modules, "browser_use.browser", browser_mod)
    monkeypatch.setitem(sys.modules, "browser_use.browser.session", sess_mod)

    _shorten_page_readiness()
    bs = _BS()
    asyncio.run(bs._navigate_and_wait("http://x", "t1"))  # בלי timeout → 3 שנ'
    asyncio.run(bs._navigate_and_wait("http://y", "t2", timeout=5.0))  # מפורש → מכובד
    assert calls[0] == ("http://x", PAGE_READY_TIMEOUT_S, "load", None)
    assert calls[1][1] == 5.0
    assert PAGE_READY_TIMEOUT_S == 3.0


def test_runner_enables_coordinate_clicking_after_agent_build():
    """QA 19.7 (הוט): browser-use מדליק קליק-קואורדינטות רק ל-allowlist מודלים —
    flash לא שם, ולכן פעולת click הייתה index-only ומפות SVG נפלו ל-evaluate סינתטי.
    בדיקה טקסטואלית (browser_use לא מותקן ב-.venv): ההדלקה קיימת אחרי בניית ה-Agent."""
    import pathlib

    runner = pathlib.Path(__file__).parent.parent / "app" / "automation" / "bu_runner.py"
    src = runner.read_text(encoding="utf-8")
    build = src.index("agent = Agent(**agent_kwargs)")
    enable = src.index("agent.tools.set_coordinate_clicking(True)")
    assert build < enable < src.index("await agent.run(")
