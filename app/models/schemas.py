"""סכמות נתונים משותפות (pydantic)."""

from pydantic import BaseModel


class ActionResult(BaseModel):
    success: bool
    summary: str = ""  # אישור קצר למשתמש
    details: dict = {}
