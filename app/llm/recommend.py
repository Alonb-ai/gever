"""המלצות אמיתיות — Gemini Grounding: Google Maps (מקומות) / Google Search (סרטים).

המנגנון הוכרע ואומת חי (ראה merge-ledger, "המלצות — מנגנון הוכרע"): אותם נתוני
מפות (דירוג, כמות ביקורות, פתוח-עכשיו) על מפתח ה-Gemini הקיים. הפרומפט למקומות
באנגלית בלבד (מגבלה רשמית של maps grounding) — התרגום קורה בשכבת ה-extract;
הנתונים המובנים נפרסים מ-grounding_chunks[].maps.text (markdown עקבי, נצפה
בניסוי maps_grounding_trial). לסרטים search grounding באותו דפוס, בעברית.
"""

import asyncio
import re

from google import genai
from google.genai import types

from app.config import settings

# מרכז ת"א כנקודת הטיה (bias) בלבד — השאילתה נוקבת באזור המבוקש, וזה החזיר
# תוצאות נכונות גם לערים אחרות בניסוי החי (10/10).
_TLV = types.LatLng(latitude=32.0853, longitude=34.7818)

# תקרת המתנה לקריאת ההמלצות — מעבר לה עדיף כנות ("לא הסתדר") על לקוח תקוע.
REC_TIMEOUT_S = 40.0

# שקלול כמות ביקורות — ממוצע עם prior של 4.0 במשקל 200 ביקורות (בלי מדע):
# 5.0 על 141 ביקורות (score ‎4.41) לא גובר על 4.5 על 9K (score ‎4.49).
_PRIOR_MEAN = 4.0
_PRIOR_WEIGHT = 200

_RATING_RE = re.compile(r"\*\*Rating:\*\*\s*([0-9.]+)")
_REVIEWS_RE = re.compile(r"\(([\d,]+)\s*reviews?\)", re.IGNORECASE)
# "שם הסרט | סיבה קצרה" — שורת הפלט שהפרומפט לסרטים כופה
_MOVIE_LINE_RE = re.compile(r"^\s*(?:\d+[.)]\s*)?(.+?)\s*\|\s*(.+?)\s*$")

_client: genai.Client | None = None


async def _generate(prompt: str, config: types.GenerateContentConfig):
    """קריאת ה-grounding (חוסמת → thread, כמו שאר קריאות ה-genai). מופרד כדי
    שטסטים ימקו רק אותו."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return await asyncio.to_thread(
        _client.models.generate_content,
        model=settings.gemini_model,
        contents=prompt,
        config=config,
    )


def _score(rating: float, reviews: int) -> float:
    """דירוג משוקלל-ביקורות: מושך דירוגים עם מעט ביקורות לכיוון ה-prior."""
    return (rating * reviews + _PRIOR_MEAN * _PRIOR_WEIGHT) / (reviews + _PRIOR_WEIGHT)


def parse_maps_chunks(chunks) -> list[dict]:
    """‎grounding_chunks → רשימת מקומות {name, rating, reviews, open_now, uri,
    place_id}. הדירוג/ביקורות חיים בתוך maps.text (markdown), לא בשדות מובנים."""
    places: list[dict] = []
    seen: set[str] = set()
    for c in chunks or []:
        m = getattr(c, "maps", None)
        title = ((getattr(m, "title", "") or "") if m else "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        text = getattr(m, "text", "") or ""
        rating_m = _RATING_RE.search(text)
        reviews_m = _REVIEWS_RE.search(text)
        places.append(
            {
                "name": title,
                "rating": float(rating_m.group(1)) if rating_m else None,
                "reviews": int(reviews_m.group(1).replace(",", "")) if reviews_m else 0,
                "open_now": "Open Now" in text,
                "uri": getattr(m, "uri", "") or "",
                "place_id": getattr(m, "place_id", "") or "",
            }
        )
    return places


def rank(places: list[dict], limit: int = 3) -> list[dict]:
    """מיון לפי הדירוג המשוקלל; מקומות בלי דירוג נדחקים לסוף."""
    rated = sorted(
        (p for p in places if p["rating"] is not None),
        key=lambda p: _score(p["rating"], p["reviews"]),
        reverse=True,
    )
    unrated = [p for p in places if p["rating"] is None]
    return (rated + unrated)[:limit]


async def recommend_places(category: str, area: str = "", constraints: str = "") -> list[dict]:
    """עד 3 מקומות אמיתיים מ-Maps grounding. הקלטים כבר באנגלית (מה-extract)."""
    what = category or "restaurant"
    if constraints:
        what += f", {constraints}"
    where = f" in {area}, Israel" if area else " in Israel"
    prompt = (
        f"Recommend up to 5 highly-rated {what} options{where}. "
        "For each place give its name, star rating, and number of reviews. Be concise."
    )
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_maps=types.GoogleMaps())],
        tool_config=types.ToolConfig(retrieval_config=types.RetrievalConfig(lat_lng=_TLV)),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    resp = await _generate(prompt, config)
    cand = resp.candidates[0] if resp.candidates else None
    gm = getattr(cand, "grounding_metadata", None) if cand else None
    return rank(parse_maps_chunks(getattr(gm, "grounding_chunks", None)))


async def recommend_movies(constraints: str = "") -> list[dict]:
    """עד 3 סרטים שרצים עכשיו — search grounding (אין דירוגי Maps לסרטים);
    השם והשורה מגיעים מהפלט הכפוי-פורמט, לא מהמצאה של מודל השיחה."""
    extra = f" ({constraints})" if constraints else ""
    prompt = (
        f"אילו 3 סרטים שמוקרנים עכשיו בבתי הקולנוע בישראל הכי שווים{extra}? "
        "ענה בדיוק שורה אחת לכל סרט בפורמט: שם הסרט | סיבה קצרה אחת לפי הביקורות. "
        "בלי שום טקסט אחר."
    )
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    resp = await _generate(prompt, config)
    items: list[dict] = []
    for line in (resp.text or "").splitlines():
        m = _MOVIE_LINE_RE.match(line)
        if m:
            items.append(
                {
                    "name": m.group(1).strip("*# "),
                    "rating": None,
                    "reviews": 0,
                    "blurb": m.group(2).strip("* "),
                    "uri": "",
                    "place_id": "",
                }
            )
    return items[:3]
