"""error_detail — סיומת פירוט-שגיאה להודעת WhatsApp (dev/MVP).

המנוע הדטרמיניסטי (act_verified + סולם ה-observe→act→agent) הוסר במעבר ל-browser-use
כשכבת הניווט האוטונומית. נשארה רק הפונקציה הזו, שה-pipeline משתמש בה.
"""

from app.config import settings


def error_detail(exc, *, session_id: str | None = None) -> str:
    """סיומת לפירוט שגיאה בהודעת WhatsApp: סוג+טקסט השגיאה (+session ל-replay). ריק
    כש-DEBUG_ERRORS כבוי (פרודקשן) או כשאין שגיאה — אז ההודעה נשארת בדמות בלבד."""
    if not settings.debug_errors or not exc:
        return ""
    head = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    tail = f" · session {session_id}" if session_id else ""
    return f"\n\nשגיאה טכנית: {head}{tail}"
