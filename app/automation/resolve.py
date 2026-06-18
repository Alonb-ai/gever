"""
resolver: שם מסעדה → Ontopo page URL (deep-link), בלי דפדפן.

חיפוש web (DuckDuckGo HTML) שמחזיר את דף ה-Ontopo, ואז דיסאמביגואציה לפי
הכותרת (חשוב — לרשת כמו "הדסון" יש כמה סניפים). מחזיר 'one' עם url, 'many'
עם מועמדים לשאלת הבהרה, או 'none'.

הערה: DDG HTML scraping מתאים ל-MVP; לפרודקשן עדיף search API עם מפתח (Brave/Serp).
"""

import re
import urllib.parse

import httpx

from app.automation.ontopo import _is_listing, _match_restaurant

DDG = "https://html.duckduckgo.com/html/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
_ANCHOR = re.compile(r'<a[^>]*uddg=([^&"]+)[^>]*>(.*?)</a>', re.S)
_PAGE = re.compile(r"ontopo\.com/[a-z]{2}/[a-z]{2}/page/(\d+)")
_TAG = re.compile(r"<[^>]+>")


def _clean(t: str) -> str:
    return _TAG.sub("", t).strip()


async def search_ontopo(name: str, city: str = "") -> list[dict]:
    """[{title, url}] של דפי Ontopo התואמים לשאילתה, לפי רלוונטיות (deduped)."""
    query = " ".join(p for p in [name, city, "ontopo"] if p)
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as http:
        resp = await http.get(DDG, params={"q": query})
        resp.raise_for_status()
        html = resp.text

    out, seen = [], set()
    for enc_url, raw_title in _ANCHOR.findall(html):
        url = urllib.parse.unquote(enc_url)
        m = _PAGE.search(url)
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        out.append({"title": _clean(raw_title), "url": f"https://ontopo.com/he/il/page/{m.group(1)}"})
    return out


async def resolve_ontopo_url(name: str, city: str = "") -> dict:
    """
    מחזיר {'status': one|many|none, 'url': str|None, 'candidates': [...]}.
    one → url מוכן; many → צריך לשאול את המשתמש לאיזה סניף; none → לא נמצא.
    """
    candidates = await search_ontopo(name, city)
    if not candidates:
        return {"status": "none", "url": None, "candidates": []}

    # סינון דילים/שוברים/חבילות לפני הדיסאמביגואציה — אלה מבלבלים את הלקוח.
    # אם הסינון מרוקן הכל, נשארים עם הסט המקורי (fallback).
    filtered = [c for c in candidates if not _is_listing(c["title"])]
    candidates = filtered or candidates

    titles = [c["title"] for c in candidates]
    status, chosen_title, good = _match_restaurant(name, titles)
    if status == "one":
        url = next(c["url"] for c in candidates if c["title"] == chosen_title)
        return {"status": "one", "url": url, "candidates": candidates}
    if status == "many":
        return {"status": "many", "url": None, "candidates": [c for c in candidates if c["title"] in good]}
    # אף כותרת לא תאמה חזק → ברירת מחדל: התוצאה הראשונה (הכי רלוונטית)
    return {"status": "one", "url": candidates[0]["url"], "candidates": candidates}
