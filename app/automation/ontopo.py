"""
ביצוע הזמנת מסעדה ב-Ontopo דרך Stagehand (שלב 2).

מגיע אחרי שה-PoC (poc/ontopo_poc.py) הוכיח שהזרימה עוברת.
כאן עוטפים אותה כפונקציה שמקבלת פרטים ומחזירה ActionResult.
"""

from app.models.schemas import ActionResult


async def book_table(
    restaurant: str,
    party_size: int,
    date: str,
    time: str,
    name: str,
    phone: str,
) -> ActionResult:
    """
    TODO(stage2): לקחת את הזרימה מ-poc/ontopo_poc.py, להוסיף פרטי משתמש
    ואישור סופי, ולהחזיר ActionResult עם פרטי ההזמנה.
    """
    raise NotImplementedError("Ontopo booking action — stage 2")
