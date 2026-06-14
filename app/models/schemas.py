"""סכמות נתונים משותפות (pydantic)."""

from enum import Enum

from pydantic import BaseModel


class ActionType(str, Enum):
    RESTAURANT = "restaurant"      # ✅ MVP — Ontopo
    INSURANCE = "insurance"        # שלב מאוחר — כולל תשלום
    TICKETS = "tickets"            # שלב מאוחר — כולל תשלום
    UNKNOWN = "unknown"


class Intent(BaseModel):
    """תוצר שכבת ההבנה (Gemini Flash) על הודעת משתמש."""

    action: ActionType
    # שדות שחולצו מההודעה. None = חסר, ולכן צריך לשאול עליו.
    fields: dict[str, str | None] = {}
    missing: list[str] = []
    reply: str = ""               # מה שגבר עונה בינתיים (שאלת הבהרה / אישור)


class ActionResult(BaseModel):
    success: bool
    summary: str = ""             # אישור קצר למשתמש
    details: dict = {}
