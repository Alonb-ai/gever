"""קטלוג הופעות פנימי — שלב-1 ל-resolver של ההופעות + מקור העובדות לסקירת
"מה יש הופעות קרובות" (עוגני אמת: שמות/תאריכים/ערים אמיתיים בלבד).

מחקר 20.7 (HTTP בלבד, אומת חי):
- לאן (leaan.co.il): דף הבית הוא Next.js עם __NEXT_DATA__ מוטמע;
  initialState.search.events = הקטלוג המלא (~440 אירועים: name,
  location{name,city}, event_start אפוק, active, categories). דף האירוע:
  /events/<שם-במקפים>/<id> — ה-id הוא שמנתב (slug שגוי עדיין 200, אומת חי).
- קופת (kupat.co.il): ה-WP REST‏ (wp-json/wp/v2/shows-api) מחזיר 1,403 רשומות
  אבל בלי תאריך/מקום ברי-שימוש ורובן ישנות; גריד דף הבית ה-server-rendered
  מציג את ~56 המופעים הפעילים: <article aria-label="אמן"> + לינק /show/<slug>.
  בלי תאריכים — אינדקס אמן→URL בלבד, וזה בדיוק הפער שאומת חי (19.7): דף
  אייל גולן נעלם מסט התוצאות של Brave.

endpoints לא רשמיים — כל כשל/שינוי מבנה נופל בשקט לרשימה ריקה (הצרכנים
ממשיכים ל-Brave / להודעת כנות); לעולם לא חריגה החוצה.
"""

import html
import json
import logging
import re
import time
import zoneinfo
from datetime import datetime

import httpx

log = logging.getLogger("gever")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
_IL_TZ = zoneinfo.ZoneInfo("Asia/Jerusalem")
_TTL_S = 3600.0  # הקטלוג מתחלף לאט — שעה של cache חוסכת 4MB לכל resolve

_LEAAN_HOME = "https://www.leaan.co.il/"
_KUPAT_HOME = "https://www.kupat.co.il/"
_NEXT_DATA = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# כרטיס מופע בגריד של קופת: שם האמן ב-aria-label של ה-article, הלינק בפנים.
# הפירסור פר-article (split) ולא regex חוצה-הכל — באנר בלי לינק בלע את הלינק
# של ה-article הבא ("קופת תל אביב +"→shlomo-artzi, נתפס בsmoke החי 20.7).
_KUPAT_LABEL = re.compile(r'aria-label="([^"]+)"')
_KUPAT_LINK = re.compile(r'href="(https://www\.kupat\.co\.il/show/[^"]+)"')

_HE_MONTHS = (
    "ינואר",
    "פברואר",
    "מרץ",
    "אפריל",
    "מאי",
    "יוני",
    "יולי",
    "אוגוסט",
    "ספטמבר",
    "אוקטובר",
    "נובמבר",
    "דצמבר",
)


def _he_date(ts: float) -> str:
    """אפוק → "25 באוגוסט" (בשעון ישראל; שנה מצורפת רק כשאינה השנה הנוכחית).
    טקסטואלי בכוונה: קריא בוואטסאפ, ולא נופל על איסור הדירוג-המספרי (\\d.\\d)
    של כרטיס recommend_results."""
    d = datetime.fromtimestamp(ts, tz=_IL_TZ)
    out = f"{d.day} ב{_HE_MONTHS[d.month - 1]}"
    if d.year != datetime.now(tz=_IL_TZ).year:
        out += f" {d.year}"
    return out


async def _get(url: str) -> str:
    """GET אחד עם ה-UA/timeout המשותפים — הנקודה שהטסטים ממקקים."""
    async with httpx.AsyncClient(
        timeout=20, headers={"User-Agent": UA}, follow_redirects=True
    ) as http:
        return (await http.get(url)).text


async def _leaan() -> list[dict]:
    """הקטלוג המלא של לאן מדף הבית: אירועים פעילים שטרם קרו, עם תאריך/היכל/עיר."""
    m = _NEXT_DATA.search(await _get(_LEAAN_HOME))
    if not m:
        return []
    state = json.loads(m.group(1))["props"]["pageProps"]["initialState"]
    now = time.time()
    out = []
    for e in (state.get("search") or {}).get("events") or []:
        name, ts = (e.get("name") or "").strip(), e.get("event_start") or 0
        if not name or not e.get("id") or not e.get("active") or ts <= now:
            continue
        loc = e.get("location") or {}
        cats = [c.get("category_name") or "" for c in (e.get("categories") or {}).values()]
        out.append(
            {
                "title": name,
                "date": _he_date(ts),
                "ts": ts,
                "venue": (loc.get("name") or "").strip(),
                "city": (loc.get("city") or "").strip(),
                # slug = השם במקפים (רווח וגם '/' — סלאש היה שובר את הנתיב);
                # ה-id הוא שמנתב בפועל, ה-slug קוסמטי (אומת חי).
                "url": f"{_LEAAN_HOME}events/{re.sub(r'[ /]', '-', name)}/{e['id']}",
                "platform": "leaan",
                "category": next((c for c in cats if c), ""),
            }
        )
    return out


async def _kupat() -> list[dict]:
    """המופעים הפעילים מגריד דף הבית של קופת — אמן→URL בלבד (אין שם תאריכים)."""
    body = await _get(_KUPAT_HOME)
    out, seen = [], set()
    for card in body.split("<article")[1:]:
        label, link = _KUPAT_LABEL.search(card), _KUPAT_LINK.search(card)
        if not label or not link:
            continue
        title, url = html.unescape(label.group(1)).strip(), link.group(1)
        if not title or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "title": title,
                "date": "",
                "ts": 0,
                "venue": "",
                "city": "",
                "url": url,
                "platform": "kupat",
                "category": "",
            }
        )
    return out


# סדר = סדר הקטלוג (לאן קודם — יש לה תאריכים); הטסטים מאפסים/דורסים את זה.
_SOURCES = (_leaan, _kupat)
_cache: dict = {"ts": 0.0, "items": []}


async def fetch_upcoming() -> list[dict]:
    """הקטלוג המשולב, עם cache בזיכרון (TTL שעה). כל מקור שנופל — לוג והמשך;
    שני המקורות נפלו → רשימה ריקה. לעולם לא זורק החוצה."""
    if _cache["items"] and time.monotonic() - _cache["ts"] < _TTL_S:
        return _cache["items"]
    items: list[dict] = []
    for source in _SOURCES:
        try:
            items += await source()
        except Exception:  # noqa: BLE001 — endpoint לא רשמי: כשל שקט, הצרכן ממשיך
            log.info("shows_catalog: %s failed", source.__name__, exc_info=True)
    if items:
        _cache.update(ts=time.monotonic(), items=items)
    return items


# קטגוריות לאן שאינן "הופעה" במובן שהלקוח מתכוון אליו כשהוא מבקש המלצה
# (מופעי ילדים ומשחקי ספורט) — מסוננות מהסקירה; ה-resolver כן רואה אותן.
_NOT_A_SHOW = ("ילדים", "ספורט")


def _area_ok(area: str, it: dict) -> bool:
    """התאמת אזור סלחנית: מילה מהאזור המבוקש (גם באנגלית — ה-extract של recommend
    מתרגם) מופיעה בעיר/היכל, בגישור התעתיק הקיים של ה-resolver."""
    from app.automation.resolve import _has_token, _norm  # מקומי — נגד מעגל import

    ntarget = _norm(f"{it['city']} {it['venue']}")
    return any(_has_token(w, ntarget) for w in _norm(area).split() if len(w) >= 2)


def _place_line(it: dict) -> str:
    """היכל+עיר לשורת עובדות אחת, בלי כפל עיר (היכלי לאן כבר מכילים אותה:
    "מוזיאון אורי גלר, תל אביב" + city="תל אביב" — נתפס ב-smoke החי 20.7)."""
    from app.automation.resolve import _with_city  # מקומי — נגד מעגל import

    return _with_city(it["venue"], it["city"])


async def recommend_shows(area: str = "") -> list[dict]:
    """סקירת ההופעות הקרובות מהקטלוג, בצורת הפריטים של recommend_movies
    (הצרכן: _send_rec_batch — name עוגן-אמת, blurb עובדות תאריך/מקום).
    רק אירועים עם תאריך אמיתי (לאן); הקרובים בזמן קודם. אזור מבוקש מסנן,
    ואם אין בו כלום — מגישים את מה שכן קיים (הערים מוצגות בהודעה)."""
    items = [it for it in await fetch_upcoming() if it["ts"] and it["category"] not in _NOT_A_SHOW]
    if area:
        items = [it for it in items if _area_ok(area, it)] or items
    items.sort(key=lambda it: it["ts"])
    return [
        {
            "name": it["title"],
            "rating": None,
            "reviews": 0,
            "blurb": " · ".join(x for x in (it["date"], _place_line(it)) if x),
            "uri": "",
            "place_id": "",
        }
        for it in items
    ]
