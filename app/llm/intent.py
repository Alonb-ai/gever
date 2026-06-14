"""
שכבת ההבנה והשיחה — Gemini Flash (שלב 1).

תפקיד: לקרוא הודעת WhatsApp חופשית, לזהות את הפעולה, לחלץ פרטים,
ולהחזיר Intent. אם חסר מידע — שדה reply מכיל שאלת הבהרה קצרה בסגנון גבר.

ה-System Prompt מתוך האפיון (סעיף 2.4).
"""

from app.models.schemas import Intent

SYSTEM_PROMPT = (
    "אתה גבר — עוזר אישי בעברית שסוגר דברים. קצר, ישיר, לא מתחנחן. "
    "שואל רק מה שחסר. מאשר ביצוע עם ✅. אף פעם לא אומר \"בהחלט\" או \"כמובן\". "
    "מדבר כמו חבר, לא כמו בוט. אמוג'י בלבד: 🤙 ✅ 🔄"
)


async def understand(message: str, context: list[dict] | None = None) -> Intent:
    """
    TODO(stage1): קריאה ל-Gemini Flash עם SYSTEM_PROMPT + ההודעה + הקשר השיחה,
    החזרת Intent מובנה (structured output). כרגע stub.
    """
    raise NotImplementedError("Gemini Flash intent layer — stage 1")
