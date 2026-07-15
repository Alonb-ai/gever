"""
resolver: שם מסעדה → URL של דף הזמנות, בלי דפדפן. multi-platform: Ontopo › Tabit.

חיפוש web בשאילתה רחבה ("<שם> הזמנת מקום") שתופסת את שתי הפלטפורמות, ואז
דיסאמביגואציה לפי הכותרת (חשוב — לרשת כמו "הדסון" יש כמה סניפים) פלטפורמה-פלטפורמה
לפי סדר עדיפות. מחזיר 'one' עם url+platform, 'many' עם מועמדים לשאלת הבהרה, או 'none'.

מנוע החיפוש: Brave Search API (BRAVE_API_KEY חובה). נתיב ה-DDG נמחק: מת בפרוד
(202 אנטי-בוט ל-IP של דטהסנטר) ומיותר ב-dev — ה-tier החינמי של Brave מספיק.
"""

import asyncio
import html
import re
import urllib.parse

import httpx

from app.config import settings

BRAVE = "https://api.search.brave.com/res/v1/web/search"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
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


# --- דיסאמביגואציה לפי כותרת (הועבר מ-ontopo.py — הצרכן היחיד הוא ה-resolver) ---


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch == " ")


# מילות-מפתח שמסמנות דיל/רשימה/שובר ולא את דף ההזמנה האמיתי של המסעדה
_LISTING_WORDS = ("ארוחת", "טעימות", "דיל", "מבצע", "כרטיס", "שובר", "חבילת", "זוגית", "גיפט")


def _is_listing(title: str) -> bool:
    """True אם הכותרת היא דיל/שובר/חבילה ולא דף הזמנה אמיתי של מסעדה."""
    return any(w in title for w in _LISTING_WORDS)


# מילות-רעש שאינן מבחינות בין סניפים (שם האתר וכו') — מותר שיופיעו בכותרת "נקייה".
_NOISE_WORDS = {"ontopo"}


def _is_clean_name(req: str, title: str) -> bool:
    """True אם הכותרת היא השם המבוקש ללא מילים מבחינות — כלומר דף ההזמנה הראשי
    ("<שם> - Ontopo"), להבדיל מסניף אמיתי ("הדסון לילינבלום") שמוסיף מילה.
    req ו-title שניהם מנורמלים (_norm)."""
    req_words = set(req.split())
    extra = [w for w in title.split() if w not in req_words]
    return all(w in _NOISE_WORDS for w in extra)


def _match_restaurant(requested: str, candidates: list[str]) -> tuple[str, str | None, list[str]]:
    """דיסאמביגואציה (שם->URL). status: one|many|none."""
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


# og:title מופיע בדפי Ontopo גם כ-meta-tag וגם בתוך JSON מוטמע — הרגקס תופס את שניהם.
_OG_TITLE = re.compile(r'og:title"?[^>{]{0,120}?content"?\s*[:=]\s*\\?"([^"<>\\]+)')
_URLISH_TITLE = re.compile(r"https?://|www\.")


def _og_title(body: str) -> str:
    m = _OG_TITLE.search(body)
    return html.unescape(m.group(1)).strip() if m else ""


async def _real_titles(candidates: list[dict]) -> None:
    """כותרת שהיא URL (Brave מחזיר כאלה כשאין לו כותרת) → מביאים את השם האמיתי
    מה-og:title של הדף עצמו. בלעדיו המסעדה בלתי-ניתנת להזמנה בכלל: אין שם להציג
    ברשימה ואין על מה לעשות match — נצפה חי (AKA): כל שיחה מתה ב'יש כמה כאלה'."""
    targets = [c for c in candidates if _URLISH_TITLE.search(c["title"]) or not c["title"]][:3]
    if not targets:
        return
    async with httpx.AsyncClient(
        timeout=10, headers={"User-Agent": UA}, follow_redirects=True
    ) as http:
        for c in targets:
            try:
                resp = await http.get(c["url"])
                title = _og_title(resp.text)
                if title:
                    c["title"] = title
            except Exception:  # noqa: BLE001 — best-effort: בלי שם הדף יסונן מהרשימה
                pass


def _candidate(url: str, raw_title: str, seen: set, platforms=_PLATFORMS) -> dict | None:
    """URL+כותרת של תוצאת חיפוש → מועמד {title, url קנוני, platform}, או None
    אם זה לא דף הזמנות של פלטפורמה מוכרת (או כפול)."""
    for platform, pattern, canon in platforms:
        m = pattern.search(url)
        if not m or (platform, m.group(1)) in seen:
            continue
        seen.add((platform, m.group(1)))
        title = _clean(raw_title)
        if platform == "tabit":
            # כותרות Tabit בתוצאות חיפוש גנריות ("הזמנת מקום - טאביט") — שם המסעדה
            # יושב ב-slug של ה-URL. מוסיפים אותו לכותרת כדי שהדיסאמביגואציה תעבוד.
            slug = urllib.parse.unquote(m.group(1)).replace("-", " ").strip()
            if slug and slug not in title:
                title = f"{title} | {slug}"
        return {"title": title, "url": canon.format(m.group(1)), "platform": platform}
    return None


def _from_brave(data: dict, platforms=_PLATFORMS) -> list[dict]:
    """JSON של Brave web search → [{title, url, platform}] (deduped, לפי סדר)."""
    out, seen = [], set()
    for r in (data.get("web") or {}).get("results") or []:
        c = _candidate(r.get("url") or "", r.get("title") or "", seen, platforms)
        if c:
            out.append(c)
    return out


async def _brave_raw(query: str) -> list[dict]:
    """שאילתת Brave אחת → תוצאות web גולמיות ([{url, title, description}, ...])."""
    if not settings.brave_api_key:
        # כישלון קולני ולא [] שקט — בלי מפתח אין resolver, וזה באג קונפיגורציה
        raise RuntimeError("BRAVE_API_KEY חסר — ה-resolver לא יכול לחפש")
    async with httpx.AsyncClient(timeout=20) as http:
        # בלי country: ישראל לא ב-enum של Brave (422, נבדק חי) — השאילתה העברית
        # ממילא מחזירה תוצאות ישראליות.
        resp = await http.get(
            BRAVE,
            params={"q": query, "count": 20},
            headers={
                "X-Subscription-Token": settings.brave_api_key,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
    return (resp.json().get("web") or {}).get("results") or []


async def search_reservation(name: str) -> tuple[list[dict], list[dict]]:
    """(candidates, raw): דפי הזמנה Ontopo/Tabit (deduped) + תוצאות Brave גולמיות.
    ה-raw משמש את ה-fallbackים של ענף none: לינק פלטפורמה מהאתר העצמי, טלפון."""
    raw = await _brave_raw(f"{name} הזמנת מקום")
    return _from_brave({"web": {"results": raw}}), raw


# --- fallbackים לענף none (מחקר site-fallback, 2026-07-14) ---

# דומיינים שהם אינדקסים/אגרגטורים/רשתות חברתיות ולא האתר של המסעדה עצמה —
# לא מושכים מהם דף בחיפוש לינק-פלטפורמה.
_NOT_SITE = (
    "ontopo.",
    "tabitisrael.",
    "rest.co.il",
    "easy.co.il",
    "2eat.co.il",
    "wolt.com",
    "10bis.co.il",
    "mishloha.co.il",
    "facebook.com",
    "instagram.com",
    "tripadvisor.",
    "google.",
    "waze.com",
    "youtube.com",
    "tiktok.com",
)


def _looks_like_own_site(name: str, r: dict) -> bool:
    """True אם תוצאת Brave גולמית נראית כמו האתר של המסעדה עצמה: לא אינדקס/פלטפורמה,
    והכותרת תואמת את השם המבוקש (אותה לוגיקת התאמה כמו _match_restaurant)."""
    url = r.get("url") or ""
    if not url or any(d in url for d in _NOT_SITE):
        return False
    req = _norm(name)
    title = _norm(_clean(r.get("title") or ""))
    req_words = [w for w in req.split() if len(w) >= 2]
    return bool(req) and (req in title or bool(req_words and all(w in title for w in req_words)))


async def _platform_link_from_site(name: str, raw: list[dict]) -> dict | None:
    """Phase 4-lite: הפלטפורמות לא בתוצאות החיפוש, אבל האתר של המסעדה עצמה הוא לרוב
    שלט הכוונה לפלטפורמה (~30% מהפספוסים, מחקר 14.7). מושכים עד 2 דפים שנראים כמו
    האתר העצמי ומחפשים בהם לינק Ontopo/Tabit עם ה-regexים הקיימים. סדר _PLATFORMS
    נשמר (Ontopo לפני Tabit) גם כאן."""
    sites = [r["url"] for r in raw if _looks_like_own_site(name, r)][:2]
    if not sites:
        return None
    async with httpx.AsyncClient(
        timeout=10, headers={"User-Agent": UA}, follow_redirects=True
    ) as http:
        for site in sites:
            try:
                body = (await http.get(site)).text
            except Exception:  # noqa: BLE001 — best-effort: דף שנפל לא מפיל את ה-resolve
                continue
            for platform, pattern, canon in _PLATFORMS:
                m = pattern.search(body)
                if m:
                    url = canon.format(m.group(1))
                    return {
                        "status": "one",
                        "url": url,
                        "platform": platform,
                        "candidates": [{"title": name, "url": url, "platform": platform}],
                        "fallback": None,
                    }
    return None


# טלפון ישראלי (קווי/נייד) בתוך snippet של תוצאת חיפוש: 03-1234567 / 04 6572919 / 0501234567
_PHONE = re.compile(r"\b0\d{1,2}[-\s]?\d{7}\b")
_BRAVE_GAP_S = 1.1  # ה-tier החינמי של Brave: מקס 1 בקשה/שנייה


def _find_phone(raw: list[dict]) -> str | None:
    for r in raw:
        m = _PHONE.search(_clean(f"{r.get('title') or ''} {r.get('description') or ''}"))
        if m:
            return m.group(0)
    return None


async def _phone_hint(name: str, raw: list[dict]) -> str | None:
    """טלפון של המסעדה לענף none — במקום מבוי סתום ("לא מצאתי") הלקוח מקבל לאן להתקשר.
    קודם מהתוצאות שכבר בידינו; אין → חיפוש Brave אחד נוסף. best-effort בלבד."""
    found = _find_phone(raw)
    if found or not settings.brave_api_key:
        return found
    try:
        await asyncio.sleep(_BRAVE_GAP_S)  # מרווח מהשאילתה הראשונה — תקרת הקצב של Brave
        return _find_phone(await _brave_raw(f"{name} טלפון"))
    except Exception:  # noqa: BLE001 — הטלפון הוא בונוס; כשל לא מפיל את ה-resolve
        return None


async def resolve_reservation_url(name: str) -> dict:
    """
    מחזיר {'status': one|many|none, 'url', 'platform', 'candidates', 'fallback'}.
    one → url מוכן, ו-fallback = match חזק מהפלטפורמה הבאה בתור (לניסיון שני אם
    ההזמנה נכשלת בפועל — תרחיש גרקו: דף Ontopo שפג עם כותרת מושלמת); many → לשאול
    את המשתמש; none → לא נמצא (ואז 'phone_hint' = טלפון המסעדה אם נמצא).
    הפלטפורמה הראשונה עם match חזק מכריעה.
    """
    candidates, raw = await search_reservation(name)
    await _real_titles(candidates)  # כותרות-URL → השם האמיתי מהדף, לפני כל התאמה
    picked = _pick(name, candidates, _PLATFORMS, drop_listings=True)
    if picked["status"] != "none":
        return picked
    # אפס דפי פלטפורמה בחיפוש — לפני שמוותרים: לינק פלטפורמה מהאתר של המסעדה עצמה
    # (Phase 4-lite), ואם גם זה אין — לפחות טלפון במקום מבוי סתום.
    from_site = await _platform_link_from_site(name, raw)
    if from_site:
        return from_site
    return {**picked, "phone_hint": await _phone_hint(name, raw)}


def _pick(name: str, candidates: list[dict], platforms, *, drop_listings: bool) -> dict:
    """דיסאמביגואציה פלטפורמה-פלטפורמה לפי סדר התיעדוף — הלב המשותף של ה-resolvers
    (הועתק כמו-שהוא מענף הקולנוע לקראת המיזוג). drop_listings: סינון דילים/שוברים
    (רלוונטי למסעדות בלבד)."""
    primary, fallback = None, None
    for platform, _, _ in platforms:
        plat = [c for c in candidates if c["platform"] == platform]
        if not plat:
            continue
        if drop_listings:
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


# ורטיקל ביטוח: ספק יחיד, יעד קבוע — resolve בלי חיפוש, באותו חוזה החזרה בדיוק.
INSURANCE_URL = "https://purchase.passportcard.co.il/"


async def resolve_insurance_url() -> dict:
    """ביטוח נסיעות (פספורטכארד): תמיד 'one'. async לשמירת חוזה resolve_reservation_url."""
    return {
        "status": "one",
        "url": INSURANCE_URL,
        "platform": "passportcard",
        "candidates": [{"title": "פספורטכארד", "url": INSURANCE_URL, "platform": "passportcard"}],
        "fallback": None,
    }
