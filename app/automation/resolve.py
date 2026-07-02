"""
resolver: שם מסעדה → URL של דף הזמנות, בלי דפדפן. multi-platform: Ontopo › Tabit.

חיפוש web (DuckDuckGo HTML) בשאילתה רחבה ("<שם> הזמנת מקום") שתופסת את שתי
הפלטפורמות, ואז דיסאמביגואציה לפי הכותרת (חשוב — לרשת כמו "הדסון" יש כמה סניפים)
פלטפורמה-פלטפורמה לפי סדר עדיפות. מחזיר 'one' עם url+platform, 'many' עם מועמדים
לשאלת הבהרה, או 'none'.

הערה: DDG HTML scraping מתאים ל-MVP; לפרודקשן עדיף search API עם מפתח (Brave/Serp).
"""

import html
import re
import urllib.parse

import httpx

from app.automation.ontopo import _is_listing, _match_restaurant

DDG = "https://html.duckduckgo.com/html/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
_ANCHOR = re.compile(r'<a[^>]*uddg=([^&"]+)[^>]*>(.*?)</a>', re.S)
_PAGE = re.compile(r"ontopo\.com/[a-z]{2}/[a-z]{2}/page/(\d+)")
_TABIT = re.compile(r"tabitisrael\.co\.il/site/([^/?&\"#]+)")
_TAG = re.compile(r"<[^>]+>")

# סדר = תיעדוף: שתיהן קיימות → Ontopo. ה-regex לוכד מזהה קנוני (page id / slug) ל-dedup.
_PLATFORMS: list[tuple[str, re.Pattern, str]] = [
    ("ontopo", _PAGE, "https://ontopo.com/he/il/page/{}"),
    ("tabit", _TABIT, "https://www.tabitisrael.co.il/site/{}"),
]


def _clean(t: str) -> str:
    return html.unescape(_TAG.sub("", t)).strip()


def _parse_results(body: str) -> list[dict]:
    """HTML של תוצאות DDG → [{title, url, platform}] (deduped, לפי סדר הופעה)."""
    out, seen = [], set()
    for enc_url, raw_title in _ANCHOR.findall(body):
        url = urllib.parse.unquote(enc_url)
        for platform, pattern, canon in _PLATFORMS:
            m = pattern.search(url)
            if not m or (platform, m.group(1)) in seen:
                continue
            seen.add((platform, m.group(1)))
            title = _clean(raw_title)
            if platform == "tabit":
                # כותרות Tabit ב-DDG גנריות ("הזמנת מקום - טאביט") — שם המסעדה יושב
                # ב-slug של ה-URL. מוסיפים אותו לכותרת כדי שהדיסאמביגואציה תעבוד.
                slug = urllib.parse.unquote(m.group(1)).replace("-", " ").strip()
                if slug and slug not in title:
                    title = f"{title} | {slug}"
            out.append({"title": title, "url": canon.format(m.group(1)), "platform": platform})
            break
    return out


async def search_reservation(name: str, city: str = "") -> list[dict]:
    """[{title, url, platform}] של דפי הזמנה (Ontopo/Tabit) התואמים לשאילתה (deduped)."""
    query = " ".join(p for p in [name, city, "הזמנת מקום"] if p)
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as http:
        resp = await http.get(DDG, params={"q": query})
        resp.raise_for_status()
    return _parse_results(resp.text)


async def resolve_reservation_url(name: str, city: str = "") -> dict:
    """
    מחזיר {'status': one|many|none, 'url', 'platform', 'candidates', 'fallback'}.
    one → url מוכן, ו-fallback = match חזק מהפלטפורמה הבאה בתור (לניסיון שני אם
    ההזמנה נכשלת בפועל — תרחיש גרקו: דף Ontopo שפג עם כותרת מושלמת); many → לשאול
    את המשתמש; none → לא נמצא. הפלטפורמה הראשונה עם match חזק מכריעה.
    """
    candidates = await search_reservation(name, city)
    primary, fallback = None, None
    for platform, _, _ in _PLATFORMS:
        plat = [c for c in candidates if c["platform"] == platform]
        if not plat:
            continue
        # סינון דילים/שוברים/חבילות לפני הדיסאמביגואציה — אלה מבלבלים את הלקוח.
        # אם הסינון מרוקן הכל, נשארים עם הסט המקורי (fallback).
        plat = [c for c in plat if not _is_listing(c["title"])] or plat
        status, chosen_title, good = _match_restaurant(name, [c["title"] for c in plat])
        if status == "one":
            url = next(c["url"] for c in plat if c["title"] == chosen_title)
            if primary is None:
                primary = {"status": "one", "url": url, "platform": platform, "candidates": plat}
            else:
                fallback = {"url": url, "platform": platform}
                break
        elif status == "many" and primary is None:
            return {
                "status": "many",
                "url": None,
                "platform": platform,
                "candidates": [c for c in plat if c["title"] in good],
                "fallback": None,
            }
        # אין match חזק בפלטפורמה הזו → מנסים את הבאה בתור.
    if primary:
        return {**primary, "fallback": fallback}
    # אף פלטפורמה לא נתנה match חזק → לעולם לא לבחור לבד. לשאול את הלקוח (many) או none.
    return {
        "status": "many" if candidates else "none",
        "url": None,
        "platform": None,
        "candidates": candidates,
        "fallback": None,
    }
