"""עזרי דיסאמביגואציה לשם מסעדה (משמשים את resolve.py).

ה-playbook הדטרמיניסטי (book_table מעל Stagehand) הוסר במעבר ל-browser-use כשכבת
הניווט האוטונומית — ראה app/automation/browser_book.py + bu_runner.py. נשארו כאן רק
הפונקציות הטהורות (string) שה-resolver צריך כדי לבחור את דף ה-Ontopo הנכון.
"""


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch == " ")


# מילות-מפתח שמסמנות דיל/רשימה/שובר ולא את דף ההזמנה האמיתי של המסעדה
_LISTING_WORDS = (
    "ארוחת",
    "טעימות",
    "דיל",
    "מבצע",
    "כרטיס",
    "שובר",
    "חבילת",
    "זוגית",
    "גיפט",
)


def _is_listing(title: str) -> bool:
    """True אם הכותרת היא דיל/שובר/חבילה ולא דף הזמנה אמיתי של מסעדה."""
    return any(w in title for w in _LISTING_WORDS)


# מילות-רעש שאינן מבחינות בין סניפים (שם האתר וכו') — מותר שיופיעו בכותרת "נקייה".
_NOISE_WORDS = {"ontopo"}


def _is_clean_name(req: str, title: str) -> bool:
    """
    True אם הכותרת היא השם המבוקש ללא מילים מבחינות — כלומר דף ההזמנה הראשי
    ("<שם> - Ontopo"), להבדיל מסניף אמיתי ("הדסון לילינבלום") שמוסיף מילה.
    req ו-title שניהם מנורמלים (_norm).
    """
    req_words = set(req.split())
    extra = [w for w in title.split() if w not in req_words]
    return all(w in _NOISE_WORDS for w in extra)


def _match_restaurant(requested: str, candidates: list[str]) -> tuple[str, str | None, list[str]]:
    """דיסאמביגואציה (לשימוש ב-resolver של שם->URL). status: one|many|none."""
    req = _norm(requested)
    req_words = [w for w in req.split() if len(w) >= 2]
    good = []
    for c in candidates:
        nc = _norm(c)
        if req and (req in nc or nc in req or (req_words and all(w in nc for w in req_words))):
            good.append(c)
    if len(good) == 1:
        return "one", good[0], good
    if len(good) > 1:
        # מעדיפים את דף ההזמנה האמיתי: כותרת שהיא בדיוק השם המבוקש, או השם +
        # רעש בלבד (כמו "Ontopo"). וריאציות עם מילים מבחינות (סניפים אמיתיים
        # כמו "הדסון לילינבלום") אינן "נקיות" וישארו לשאלת הבהרה.
        clean = [c for c in good if _is_clean_name(req, _norm(c))]
        if len(clean) == 1:
            return "one", clean[0], clean
        return "many", None, good
    return "none", None, good
