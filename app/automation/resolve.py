"""
resolver: שם מסעדה → URL של דף הזמנות, בלי דפדפן. multi-platform: Ontopo › Tabit.
ורטיקל קולנוע: שם סרט → URL של דף הסרט. פלאנט › רב-חן › סינמה סיטי › הוט סינמה
(אותו צינור).

מסעדות — דו-שלבי (החלטת אלון, 17.7 — אחרי שהבנצ' הלילי הראה נחיתות-יעד שגויות
דטרמיניסטיות): שלב 1 — חיפוש פנימי בפלטפורמות עצמן (ה-autocomplete של Ontopo
וה-bridge של Tabit): שמות קנוניים, סניפים אמיתיים, ו-aliases עברית↔אנגלית.
endpoints לא רשמיים → כל כשל נופל בשקט לשלב 2. שלב 2 (fallback) — חיפוש web
ב-Brave בשאילתה רחבה ("<שם> הזמנת מקום" / "<סרט> כרטיסים קולנוע" בקולנוע)
ודיסאמביגואציה לפי כותרת. בשני השלבים: התאמה דורשת את מילת המותג (טוקן לא-גנרי
ראשון), טוקן סניף מכריע בין סניפים, ודף-רפאים של Ontopo נפסל.
מחזיר 'one' עם url+platform, 'many' עם מועמדים לשאלת הבהרה, או 'none'.

מנוע ה-fallback: Brave Search API (BRAVE_API_KEY חובה). נתיב ה-DDG נמחק: מת בפרוד
(202 אנטי-בוט ל-IP של דטהסנטר) ומיותר ב-dev — ה-tier החינמי של Brave מספיק.
"""

import asyncio
import datetime
import html
import json
import logging
import re
import urllib.parse

import httpx

from app.config import settings

log = logging.getLogger("gever")

BRAVE = "https://api.search.brave.com/res/v1/web/search"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
_PAGE = re.compile(r"ontopo\.com/[a-z]{2}/[a-z]{2}/page/(\d+)")
_TABIT = re.compile(r"tabitisrael\.co\.il/site/([^/?&\"#]+)")
# דיפ-לינק ההזמנות של טאביט (orgId) — נצפה חי (גרקו הרצליה, 16.7): דף הטאביט היחיד
# בתוצאות החיפוש היה online-reservations/create-reservation?orgId=..., והרגקס של
# /site/ פספס אותו → אחרי פסילת דף-הרפאים של Ontopo נשאר none במקום טאביט חי.
_TABIT_ORG = re.compile(
    r"tabitisrael\.co\.il/online-reservations/[^\s\"'<>]*?orgId=([0-9a-fA-F]{6,})"
)
_TAG = re.compile(r"<[^>]+>")

# דיפ-לינק ההזמנות הקנוני של טאביט לפי orgId — משותף ל-regex של Brave ולחיפוש הפנימי.
_TABIT_ORG_URL = (
    "https://www.tabitisrael.co.il/online-reservations/create-reservation?step=search&orgId={}"
)

# סדר = תיעדוף: שתיהן קיימות → Ontopo. ה-regex לוכד מזהה קנוני (page id / slug / orgId)
# ל-dedup. אותה פלטפורמה יכולה להופיע עם כמה תבניות URL.
_PLATFORMS: list[tuple[str, re.Pattern, str]] = [
    ("ontopo", _PAGE, "https://ontopo.com/he/il/page/{}"),
    ("tabit", _TABIT, "https://www.tabitisrael.co.il/site/{}"),
    ("tabit", _TABIT_ORG, _TABIT_ORG_URL),
]
# סדר התיעדוף בין פלטפורמות (בלי כפילויות) — ל-_select, שעובר פלטפורמה-פלטפורמה.
_PLATFORM_ORDER = tuple(dict.fromkeys(p for p, _, _ in _PLATFORMS))

# קולנוע (סדר = תיעדוף): פלאנט ורב-חן חולקות פלטפורמה (אותם movie ids, נבדק חי 14.07.26),
# ולכן רב-חן היא ה-fallback הטבעי כשבעיר אין פלאנט. yesplanet באלטרנציה — Brave עלול
# עוד להחזיר את הדומיין הישן (redirect 302); הקנוני תמיד planetcinema.
_PLANET_FILM = re.compile(r"(?:planetcinema|yesplanet)\.co\.il/films/([a-z0-9-]+/\d+s\d+r)")
_RAVHEN_CANON = "https://www.rav-hen.co.il/films/{}"
_CINEMA_PLATFORMS: list[tuple[str, re.Pattern, str]] = [
    (
        "planet",
        _PLANET_FILM,
        "https://www.planetcinema.co.il/films/{}",
    ),
    (
        "rav-hen",
        re.compile(r"rav-hen\.co\.il/films/([a-z0-9-]+/\d+s\d+r)"),
        _RAVHEN_CANON,
    ),
    (
        "cinema-city",
        re.compile(r"cinema-city\.co\.il/movie/(\d+)"),
        "https://www.cinema-city.co.il/movie/{}",
    ),
    # הוט סינמה — אחרונה בכוונה: לא משנה את התיעדוף הקיים. URL בלי slug עושה 302
    # לדף הקנוני (אומת חי 17.7).
    (
        "hot-cinema",
        re.compile(r"hotcinema\.co\.il/movie/(\d+)"),
        "https://www.hotcinema.co.il/movie/{}",
    ),
]


_CC_TITLE_SUFFIX = re.compile(r"\s*[-–|]\s*סינמה סיטי\s*$")

# הופעות (סדר = תיעדוף): לאן ראשית (זרימת רכישה מלאה בעמוד האירוע, נגיש מ-IP זר —
# אומת 15.07.26); קופת ת"א גיבוי (עמוד /show/, הרכישה ב-tickets.kupat.co.il מגיעה
# מכפתור בעמוד). איוונטים בחוץ (403 Akamai ל-IP לא-ישראלי) — יעד שלב-ב עם פרוקסי IL.
# ה-regex של לאן תופס /events/ בלבד — לא את הסאב-אתר הישן /eco99/.../shows/.
_EVENT_PLATFORMS: list[tuple[str, re.Pattern, str]] = [
    (
        "leaan",
        re.compile(r"leaan\.co\.il/events/([^/?#]+/\d+)"),
        "https://www.leaan.co.il/events/{}",
    ),
    (
        "kupat",
        re.compile(r"(?:www\.)?kupat\.co\.il/show/([A-Za-z0-9_-]+)"),
        "https://www.kupat.co.il/show/{}",
    ),
]

# חיתוך זנבות כותרת של לאן — רק שם-האתר ("| כרטיסים רשמיים בלאן" / "| כרטיסים
# רשמיים | לאן" / "| כרטיסים בלאן"). התאריך וההיכל נשארים בכוונה: many עם
# תאריך+מקום לכל מועמד = רשימת הבחירה של הלקוח היא המועדים האמיתיים.
_LEAAN_TITLE_SUFFIX = re.compile(r"(\s*\|\s*כרטיסים[^|]*)?(\s*\|\s*ב?לאן)?\s*$")
# קופת: "עומר אדם הופעות 2026 - הזמנת כרטיסים ישירה להופעה של עומר אדם"
_KUPAT_TITLE_SUFFIX = re.compile(r"\s*[-–]\s*(?:הזמנת\s+)?כרטיסים.*$")


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


# מילות-רעש שאינן מבחינות בין סניפים (שם האתר, ז'רגון הזמנות) — מותר בכותרת "נקייה".
_NOISE_WORDS = {"ontopo", "אונטופו", "tabit", "טאביט", "הזמנת", "מקום", "הזמנתמקום", "book", "now"}

# מילים גנריות שאינן מזהות מסעדה לבדן — "איזקאיה" ניצחה את "אסה" בבנצ' 17.7 כשמועמד
# אחר ("גייג'ין איזקאיה") חלק אותן עם הבקשה. רשימה קטנה בכוונה.
_GENERIC_WORDS = {
    "מסעדה",
    "מסעדת",
    "בר",
    "ביסטרו",
    "קפה",
    "סושי",
    "איזקאיה",
    "איזאקיה",
    "izakaya",
    "restaurant",
    "bar",
    "cafe",
}

# גישור עברית↔אנגלית (אסה↔ASA, הדסון↔Hudson, מסא↔MAZA — כולם נצפו בבנצ'): שלד
# עיצורים משותף. אמות קריאה (א/ה/ו/י/ע) נשמטות כמו התנועות הלטיניות; עיצורים
# מקבילים מקופלים לצורה אחת (c/q→k, z→s).
_HE2LAT = {
    "ב": "b",
    "ג": "g",
    "ד": "d",
    "ז": "s",
    "ח": "h",
    "ט": "t",
    "כ": "k",
    "ך": "k",
    "ל": "l",
    "מ": "m",
    "ם": "m",
    "נ": "n",
    "ן": "n",
    "ס": "s",
    "פ": "p",
    "ף": "p",
    "צ": "ts",
    "ץ": "ts",
    "ק": "k",
    "ר": "r",
    "ש": "s",
    "ת": "t",
    "א": "",
    "ה": "",
    "ו": "",
    "י": "",
    "ע": "",
}
_LAT_FOLD = str.maketrans({"c": "k", "q": "k", "z": "s", "w": "v", "f": "p"})


def _skeleton(word: str) -> str:
    """שלד עיצורים להשוואת מילה עברית מול לטינית: אסה→as, ASA→as; הדסון→dsn, Hudson→dsn.
    תנועת פתיחה נשמרת כ-a כדי ש"אסה" לא יתמזג עם כל מילה שמכילה s."""
    w = word.lower()
    lead = "a" if w and (w[0] in "אע" or w[0] in "aeiou") else ""
    body = "".join(_HE2LAT.get(ch, ch) for ch in w).translate(_LAT_FOLD)
    return lead + "".join(ch for ch in body if ch not in "aeiouh")


def _has_token(word: str, ntitle: str) -> bool:
    """האם טוקן מהבקשה מופיע בכותרת מנורמלת — כטוקן שלם, כתחילית (בזל↔בזל'ה, אבל לא
    מסא↔מסאלה: תוספת של יותר מאות אחת דורשת טוקן ארוך), או בגישור תעתיק."""
    sk = _skeleton(word)
    for t in ntitle.split():
        if t == word or (t.startswith(word) and (len(word) >= 4 or len(t) <= len(word) + 1)):
            return True
        if len(sk) >= 2 and _skeleton(t) == sk:
            return True
    return False


def _brand_token(nreq: str) -> str | None:
    """הטוקן המזהה של הבקשה: המילה הלא-גנרית הראשונה ("אסה איזקאיה תל אביב" → אסה)."""
    return next(
        (w for w in nreq.split() if len(w) >= 2 and w not in _GENERIC_WORDS),
        None,
    )


def _is_clean_name(req: str, title: str) -> bool:
    """True אם הכותרת היא השם המבוקש ללא מילים מבחינות — כלומר דף ההזמנה הראשי
    ("טאיזו תל אביב-יפו: הזמנת מקום | אונטופו"), להבדיל מסניף/וריאציה אמיתיים
    ("קפה טאיזו", "הדסון לילינבלום") שמוסיפים מילה. מילת-כותרת מכוסה אם היא רעש
    מוכר או חופפת מילת-בקשה (אביב↔אביביפו). req ו-title מנורמלים (_norm)."""
    req_words = set(req.split())
    extra = [w for w in title.split() if w not in req_words]
    return all(w in _NOISE_WORDS or any(rw in w or w in rw for rw in req_words) for w in extra)


def _brand_first(requested: str, pool: list[dict]) -> list[dict]:
    """סדר כנות לרשימת ה-many החלשה (אף מועמד לא עבר match חזק): קודם מי שמכיל את
    מילת המותג, ואז לפי חפיפת שאר המילים. נצפה חי (הדסון ראשון לציון, 16.7):
    "דדה ראשון לציון" עמדה ראשונה רק כי חלקה את שם העיר עם הבקשה."""
    words = [w for w in _norm(requested).split() if len(w) >= 2]
    brand = _brand_token(_norm(requested)) or (words[0] if words else None)
    if not brand:
        return pool
    rest = [w for w in words if w != brand]

    def _key(c: dict) -> tuple[bool, int]:
        nc = _norm(c["title"])
        return (_has_token(brand, nc), sum(w in nc for w in rest))

    return sorted(pool, key=_key, reverse=True)  # יציב: שוויון שומר את סדר Brave


def _match_restaurant(requested: str, candidates: list[str]) -> tuple[str, str | None, list[str]]:
    """דיסאמביגואציה (שם->URL). status: one|many|none.

    חוקי הבנצ' 17.7: (א) התאמה דורשת את מילת המותג — מילים גנריות משותפות אינן
    מספיקות (אסה↛גייג'ין). (ב) בין כמה מועמדים מאותו מותג מכריע טוקן סניף מהבקשה
    (בזל→רוסטיקו בזל); טוקן סניף שאינו מופיע באף מועמד חוסם בחירה שקטה בסניף אחר
    (רוסטיקו בזל ↛ רוטשילד) — הנחת סדר-מילים: <מותג> <סניף> <עיר>, כך שטוקן עיר
    חסר אחרי שסניף כבר פגע (בזל'ה בלי עיר בכותרת) לא חוסם."""
    req = _norm(requested)
    req_words = [w for w in req.split() if len(w) >= 2]
    brand = _brand_token(req)
    if not brand:
        # בקשה שכולה מילים גנריות — נשארת רק התאמת הכלה מלאה, בלי ניחושים.
        good = [c for c in candidates if req and req in _norm(c)]
        if len(good) == 1:
            return "one", good[0], good
        return ("many", None, good) if good else ("none", None, good)
    good = [c for c in candidates if _has_token(brand, _norm(c))]
    if not good:
        return "none", None, good
    qualifiers = [w for w in req_words if w != brand and w not in _GENERIC_WORDS]
    pool, hit_any, blocked = good, False, False
    for q in qualifiers:
        hit = [c for c in pool if _has_token(q, _norm(c))]
        if hit:
            hit_any = True
            if len(hit) < len(pool):
                pool = hit
        elif not hit_any:
            blocked = True
            break
    if blocked:
        return "many", None, pool
    if len(pool) == 1:
        return "one", pool[0], pool
    # מעדיפים את דף ההזמנה הראשי: כותרת "נקייה" (השם + רעש בלבד). כפילויות של
    # אותה כותרת (אותו דף בשני מזהים) אינן עמימות אמיתית.
    clean = [c for c in pool if _is_clean_name(req, _norm(c))]
    if clean and len(set(clean)) == 1:
        return "one", clean[0], clean
    return "many", None, pool


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


# דף Ontopo "רפאים": קיים, כותרת מושלמת, אבל המקום מסומן בו כלא-פעיל (אירוע שפג/
# עסק שירד). ניצח את ה-resolve פעמיים (גרקו 07.2026, גרקו הרצליה 15.7) ושלח את
# הריצה לדף מת בזמן שהמסעדה חיה ובועטת בטאביט.
# תיקון 17.7: המרקר הישן "לא פעיל" הוסר — הוא יושב ב-i18n של *כל* דף אונטופו
# ("nonActive":"לא פעיל") ופסל דפים חיים ברגע שההתאמה החזקה התחילה להגיע לבדיקה.
# המרקרים החדשים אומתו על גרקו הרצליה + MAZA (רפאים: מופיעים) ומול רוסטיקו בזל,
# טאיזו וקלארו (חיים: אפס מופעים): מפתח out_of_business המבני + נוסח ההודעה
# "מסעדה זו אינה זמינה להזמנות דרך מערכת אונטופו".
_DEAD_MARKS = ("out_of_business", "האירוע הסתיים", "אינה זמינה להזמנות")


def _looks_dead(body: str) -> bool:
    return any(m in body for m in _DEAD_MARKS)


async def _ontopo_dead(url: str) -> bool:
    """האם דף ה-Ontopo מסומן מת. כשל רשת → False (ספק-חי עדיף על פסילת שווא)."""
    try:
        async with httpx.AsyncClient(
            timeout=8, headers={"User-Agent": UA}, follow_redirects=True
        ) as http:
            return _looks_dead((await http.get(url)).text)
    except Exception:  # noqa: BLE001
        return False


# --- שלב 1: חיפוש פנימי בפלטפורמות (מחקר 17.7) -------------------------------
# endpoints לא רשמיים שנחשפו מה-bundles של האתרים ואומתו חי; כל כשל/שינוי עתידי
# נופל בשקט למסלול Brave (שלב 2), אז אין תלות קשיחה בהם.
#
# Ontopo (אומת: רוסטיקו בזל page 37905695, og:title תואם):
#   GET https://ontopo.com/api/unified_search?slug=<אתר>&terms=<שאילתה>&locale=he&limit=20
#     → {"found": bool, "suggestions": [{"type": "venue", "label", "secondary": עיר, "slug"}]}
#   GET https://ontopo.com/api/venue_profile?slug=<venue_slug>&locale=he
#     → {"title", "phone", "pages": [{"slug": <page_slug>, "content_type": "reservation"}]}
#   דף ההזמנה: https://ontopo.com/he/il/page/<page_slug>
# Tabit (אומת: "גרקו הרצליה" מחזיר בדיוק את ה-orgId שנצפה חי 16.7):
#   GET https://bridge.tabit.cloud/organizations/search?q=<שאילתה>
#     → {"organizations": [{"_id", "name", "city", "aliases", "services": {"book": bool}}]}
#   החיפוש fuzzy מאוד ("אסה" מחזיר CASA TUA) — סינון מותג על התוצאות הוא חובה.
_ONTOPO_API = "https://ontopo.com/api"
_ONTOPO_SITE = "15171493"  # slug של אתר ontopo-il (ה-distributor ב-HTML של דף הבית)
_TABIT_BRIDGE = "https://bridge.tabit.cloud/organizations/search"
_INTERNAL_GAP_S = 0.4  # נימוס בין קריאות לאותה פלטפורמה


def _queries(name: str) -> list[str]:
    """שאילתות לחיפוש פנימי: השם המלא, ואם שונה — גם טוקן המותג לבד ("רוסטיקו בזל
    תל אביב" לא נמצא מילולית, "רוסטיקו" מחזיר את שני הסניפים)."""
    req = _norm(name)
    brand = _brand_token(req)
    out = [name.strip()]
    if brand and brand != req:
        out.append(brand)
    return out


async def _ontopo_internal(name: str) -> list[dict]:
    """מועמדי {title, url, platform} מהחיפוש הפנימי של Ontopo; [] → אין (ממשיכים הלאה)."""
    brand = _brand_token(_norm(name))
    if not brand:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as http:
        venues: list[dict] = []
        for q in _queries(name):
            resp = await http.get(
                f"{_ONTOPO_API}/unified_search",
                params={"slug": _ONTOPO_SITE, "terms": q, "locale": "he", "limit": 20},
            )
            resp.raise_for_status()
            suggestions = resp.json().get("suggestions") or []
            venues = [
                s
                for s in suggestions
                if s.get("type") == "venue"
                and s.get("slug")
                and _has_token(brand, _norm(s.get("label") or ""))
            ]
            if venues:
                break
            await asyncio.sleep(_INTERNAL_GAP_S)
        # venue slug ≠ page slug (אומת: page/<venue_slug> הוא 404) — דף ההזמנה יושב
        # ב-venue_profile.pages עם content_type=reservation. venue בלי דף כזה אינו
        # בר-הזמנה ב-Ontopo ונשמט (אולי Tabit/האתר העצמי יחזיקו אותו).
        for v in venues[:5]:
            await asyncio.sleep(_INTERNAL_GAP_S)
            try:
                prof = (
                    await http.get(
                        f"{_ONTOPO_API}/venue_profile",
                        params={"slug": v["slug"], "locale": "he"},
                    )
                ).json()
            except Exception:  # noqa: BLE001 — פרופיל שנפל משמיט מועמד, לא את המסלול
                continue
            pages = prof.get("pages") or []
            page = next((p for p in pages if p.get("content_type") == "reservation"), None)
            if not page or not page.get("slug"):
                continue
            title = " ".join(x for x in (v.get("label"), v.get("secondary")) if x)
            out.append(
                {
                    "title": title,
                    "url": f"https://ontopo.com/he/il/page/{page['slug']}",
                    "platform": "ontopo",
                }
            )
    return out


async def _tabit_internal(name: str) -> list[dict]:
    """מועמדי {title, url, platform} מה-bridge של Tabit; [] → אין. ה-aliases של הרשומה
    (עברית+אנגלית) פותרים את גישור השפות במקור."""
    brand = _brand_token(_norm(name))
    if not brand:
        return []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as http:
        for q in _queries(name):
            resp = await http.get(_TABIT_BRIDGE, params={"q": q})
            resp.raise_for_status()
            orgs = resp.json().get("organizations") or []
            good = []
            for o in orgs:
                if not o.get("_id") or not (o.get("services") or {}).get("book"):
                    continue
                names = [o.get("name") or ""] + list(o.get("aliases") or [])
                if not any(_has_token(brand, _norm(n)) for n in names if n):
                    continue
                title = " ".join(x for x in (o.get("name"), o.get("city")) if x)
                good.append(
                    {"title": title, "url": _TABIT_ORG_URL.format(o["_id"]), "platform": "tabit"}
                )
            if good:
                return good
            await asyncio.sleep(_INTERNAL_GAP_S)
    return []


# מקורות שלב 1 לפי סדר התיעדוף הקיים (Ontopo › Tabit); הטסטים מאפסים את זה.
_INTERNAL_SOURCES = (_ontopo_internal, _tabit_internal)


def _candidate(url: str, raw_title: str, seen: set, platforms=_PLATFORMS) -> dict | None:
    """URL+כותרת של תוצאת חיפוש → מועמד {title, url קנוני, platform}, או None
    אם זה לא דף של פלטפורמה מוכרת (או כפול). dedup לפי (platform, id) — אותו id
    בפלאנט וברב-חן = שתי רשומות בכוונה (רב-חן היא fallback)."""
    for platform, pattern, canon in platforms:
        m = pattern.search(url)
        if not m or (platform, m.group(1)) in seen:
            continue
        seen.add((platform, m.group(1)))
        title = _clean(raw_title)
        if platform == "cinema-city":
            # כותרות סינמה סיטי חיות: "<סרט> - סינמה סיטי" — שם האתר אינו מילה
            # מבחינה בין גרסאות (מדובב/לרוסית), והוא שובר את _is_clean_name.
            title = _CC_TITLE_SUFFIX.sub("", title)
        if platform == "leaan":
            # חותכים רק את זנב שם-האתר; תאריך+היכל נשארים (הם הדיסאמביגואציה)
            title = _LEAAN_TITLE_SUFFIX.sub("", title).strip()
        if platform == "kupat":
            title = _KUPAT_TITLE_SUFFIX.sub("", title).strip()
        if pattern is _TABIT:
            # כותרות Tabit בתוצאות חיפוש גנריות ("הזמנת מקום - טאביט") — שם המסעדה
            # יושב ב-slug של ה-URL. מוסיפים אותו לכותרת כדי שהדיסאמביגואציה תעבוד.
            # (רק לתבנית /site/ — ב-orgId המזהה הוא hex חסר-משמעות, לא שם.)
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
    """שאילתת Brave אחת → תוצאות web גולמיות ([{url, title, description}, ...]).
    משותף לכל הוורטיקלים (מסעדות/קולנוע/הופעות)."""
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


async def search_cinema(movie: str) -> list[dict]:
    """[{title, url, platform}] של דפי סרט (פלאנט/רב-חן/סינמה סיטי) לשאילתה (deduped).
    שאילתה רחבה אחת — נבדק חי (14.07.26): מחזירה את דפי הסרט של כל הרשתות."""
    raw = await _brave_raw(f"{movie} כרטיסים קולנוע")
    return _from_brave({"web": {"results": raw}}, _CINEMA_PLATFORMS)


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


def _select(name: str, pool: list[dict]) -> tuple[str | None, dict | None, dict | None]:
    """בחירה פלטפורמה-פלטפורמה לפי סדר התיעדוף. (kind, picked, fallback):
    kind=many → picked מוכן לשאלת הבהרה; kind=one → picked + fallback מהפלטפורמה
    הבאה (לניסיון שני); kind=None → אין match חזק בשום פלטפורמה."""
    primary, fallback = None, None
    for platform in _PLATFORM_ORDER:
        plat = [c for c in pool if c["platform"] == platform]
        if not plat:
            continue
        # סינון דילים/שוברים/חבילות לפני הדיסאמביגואציה — אלה מבלבלים את הלקוח.
        # אם הסינון מרוקן הכל, נשארים עם הסט המקורי (fallback).
        plat = [c for c in plat if not _is_listing(c["title"])] or plat
        status, chosen_title, good = _match_restaurant(name, [c["title"] for c in plat])
        if status == "one":
            url = next(c["url"] for c in plat if c["title"] == chosen_title)
            if primary is None:
                primary = {
                    "status": "one",
                    "url": url,
                    "platform": platform,
                    "candidates": plat,
                }
            else:
                fallback = {"url": url, "platform": platform}
                break
        elif status == "many" and primary is None:
            return (
                "many",
                {
                    "status": "many",
                    "url": None,
                    "platform": platform,
                    "candidates": [c for c in plat if c["title"] in good],
                    "fallback": None,
                },
                None,
            )
        # אין match חזק בפלטפורמה הזו → מנסים את הבאה בתור.
    return ("one", primary, fallback) if primary else (None, None, None)


async def _pick(name: str, pool: list[dict]) -> tuple[dict | None, bool, list[dict]]:
    """בחירה + מלכודת דף-הרפאים של Ontopo (גרקו): מנצח עם כותרת מושלמת אבל מת —
    נפסל, ובוחרים מחדש מהשאר. מחזיר (תוצאה או None, dead_hit, ה-pool שנותר):
    dead_hit=True פירושו שהמותג המבוקש זוהה ונפסל כדף רפאים."""
    pool, dead_hit = list(pool), False
    while True:
        kind, picked, fallback = _select(name, pool)
        if kind == "many":
            return picked, dead_hit, pool
        if kind is None:
            return None, dead_hit, pool
        if picked["platform"] == "ontopo" and await _ontopo_dead(picked["url"]):
            log.info("resolve: dead ontopo page dropped for '%s': %s", name, picked["url"])
            dead_hit = True
            pool = [c for c in pool if c["url"] != picked["url"]]
            continue
        return {**picked, "fallback": fallback}, dead_hit, pool


async def search_events(artist: str, venue: str = "") -> list[dict]:
    """[{title, url, platform}] של דפי אירוע (לאן/קופת ת"א) לשאילתה (deduped).
    venue מחדד את השאילתה לאמן רב-ערים — ה-steering היחיד (אין פרמטר chain)."""
    q = " ".join(p for p in (artist, venue, "כרטיסים הופעה") if p)
    raw = await _brave_raw(q)
    return _from_brave({"web": {"results": raw}}, _EVENT_PLATFORMS)


async def resolve_reservation_url(name: str) -> dict:
    """
    מחזיר {'status': one|many|none, 'url', 'platform', 'candidates', 'fallback',
    'via': internal|brave}. one → url מוכן, ו-fallback = match חזק מהפלטפורמה הבאה
    בתור (לניסיון שני אם ההזמנה נכשלת בפועל — תרחיש גרקו); many → לשאול את המשתמש;
    none → לא נמצא (ואז 'phone_hint' = טלפון המסעדה אם נמצא).
    שלב 1: החיפוש הפנימי של הפלטפורמות (מדויק: סניפים אמיתיים, aliases דו-לשוניים);
    כל כשל בו — שקט, ושלב 2 (Brave) ממשיך כרגיל. הפלטפורמה הראשונה שמכריעה קובעת.
    """
    for source in _INTERNAL_SOURCES:
        try:
            internal = await source(name)
            if not internal:
                continue
            picked, _dead, _rest = await _pick(name, internal)
        except Exception:  # noqa: BLE001 — endpoint לא רשמי: כל כשל נופל בשקט ל-Brave
            log.info("resolve: internal search failed for '%s'", name, exc_info=True)
            continue
        if picked:
            return {**picked, "via": "internal"}
        # המקור הפנימי לא הכריע (אין מותג תואם / דף רפאים) → המקור/השלב הבא.

    candidates, raw = await search_reservation(name)
    await _real_titles(candidates)  # כותרות-URL → השם האמיתי מהדף, לפני כל התאמה
    picked, dead_hit, pool = await _pick(name, candidates)
    if picked:
        return {**picked, "via": "brave"}
    # אף פלטפורמה לא נתנה match חזק → לעולם לא לבחור לבד: לשאול את הלקוח (many) או none.
    # חריג: המותג זוהה ונפסל כדף רפאים (מסא→MAZA) — שאר ה-pool הוא רעש, ורשימת
    # many ממנו רק תטעה; ממשיכים לנתיב none (אתר-המסעדה/טלפון) שיגיד את האמת.
    if pool and not dead_hit:
        return {
            "status": "many",
            "url": None,
            "platform": None,
            "candidates": _brand_first(name, pool),
            "fallback": None,
            "via": "brave",
        }
    # אפס דפי פלטפורמה בחיפוש — לפני שמוותרים: לינק פלטפורמה מהאתר של המסעדה עצמה
    # (Phase 4-lite), ואם גם זה אין — לפחות טלפון במקום מבוי סתום.
    from_site = await _platform_link_from_site(name, raw)
    if from_site:
        return {**from_site, "via": "brave"}
    return {
        "status": "none",
        "url": None,
        "platform": None,
        "candidates": [],
        "fallback": None,
        "phone_hint": await _phone_hint(name, raw),
        "via": "brave",
    }


async def _ravhen_from_planet(candidates: list[dict]) -> list[dict]:
    """רב-חן כמעט לא מאונדקסת ב-Brave (נצפה חי 16.07.26: אפס תוצאות rav-hen לסרט
    שרץ בפועל ברב-חן) — אבל היא חולקת פלטפורמה ומזהי סרטים עם פלאנט, ולכן דף הסרט
    נגזר ישירות מה-match של פלאנט (אותו נתיב /films/<slug>/<id>). GET *בלי* redirects
    מאמת שהסרט באמת מוקרן ברב-חן: 200 = דף סרט חי, 302 = לא קיים שם (נבדק חי
    16.07.26 מול סרטי planet-only). best-effort — כשל רשת מדלג, לא מפיל."""
    out = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": UA}) as http:
        for c in [c for c in candidates if c["platform"] == "planet"][:3]:
            m = _PLANET_FILM.search(c["url"])
            if not m:
                continue
            url = _RAVHEN_CANON.format(m.group(1))
            try:
                if (await http.get(url)).status_code == 200:
                    out.append({"title": c["title"], "url": url, "platform": "rav-hen"})
            except Exception:  # noqa: BLE001
                pass
    return out


# הוט סינמה: הקטלוג המלא מוטמע בדף הבית — app.movies = [{ID, Name, PageUrl}, ...]
# (~100 רשומות, שמות בעברית כולל וריאנטים מדובבים; אומת חי 17.7). שלב-1 פנימי לרשת,
# באותו עיקרון של המסעדות: חיפוש פנימי ממוקד, וכל כשל נופל בשקט ל-Brave.
_HOT_HOME = "https://www.hotcinema.co.il"
_HOT_MOVIES = re.compile(r"app\.movies\s*=\s*(\[.*?\])\s*;", re.S)


async def _hot_internal() -> list[dict]:
    """מועמדי {title, url, platform} מקטלוג דף הבית של הוט סינמה; [] → כשל שקט
    (ממשיכים ל-Brave). הדיסאמביגואציה נשארת ב-_pick_cinema — וריאנטים מדובבים
    שיוצרים many הם התנהגות רצויה (הלקוח בוחר גרסה)."""
    try:
        async with httpx.AsyncClient(
            timeout=10, headers={"User-Agent": UA}, follow_redirects=True
        ) as http:
            body = (await http.get(_HOT_HOME)).text
        m = _HOT_MOVIES.search(body)
        if not m:
            return []
        return [
            {"title": mv["Name"], "url": _HOT_HOME + mv["PageUrl"], "platform": "hot-cinema"}
            for mv in json.loads(m.group(1))
            if mv.get("Name") and mv.get("PageUrl")
        ]
    except Exception:  # noqa: BLE001 — קטלוג לא רשמי: כל כשל/שינוי נופל בשקט ל-Brave
        log.info("resolve: hot-cinema catalog failed", exc_info=True)
        return []


async def resolve_cinema_url(movie: str, chain: str | None = None) -> dict:
    """כמו resolve_reservation_url, לסרטים: אותו חוזה החזרה בדיוק, על _CINEMA_PLATFORMS.
    בלי סינון _is_listing (ה-regex כבר משאיר רק דפי רשתות); כלל הברזל נשמר — אין
    match חזק → many/none, לעולם לא בוחרים סרט לבד (שם דו-משמעי / גרסה מחודשת).
    העיר לא משתתפת כאן — דף הסרט ארצי, בחירת הסניף קורית בתוך זרימת הרכישה.
    chain (למשל "cinema-city"): הלקוח ביקש רשת ספציפית → מתעלמים מהאחרות
    (בלעדיהם פלאנט תמיד מנצחת, כי היא ראשונה בסדר התיעדוף). chain="rav-hen"
    בלי תוצאת rav-hen מ-Brave → גזירה מפלאנט (_ravhen_from_planet).
    chain="hot-cinema" → שלב 1 מקטלוג דף הבית (Brave כמעט לא מאנדקס את הדומיין);
    'via' מדווח internal/brave כמו במסעדות."""
    if chain == "hot-cinema":
        picked = _pick_cinema(
            movie,
            await _hot_internal(),
            [p for p in _CINEMA_PLATFORMS if p[0] == "hot-cinema"],
            drop_listings=False,
        )
        # מכריע רק כשהמותג באמת זוהה: one, או many של הפלטפורמה (וריאנטים מדובבים).
        # ה-many הגנרי של "אין match חזק" (platform=None) לא עוצר — Brave ימשיך.
        if picked["status"] == "one" or (picked["status"] == "many" and picked["platform"]):
            return {**picked, "via": "internal"}
    candidates = await search_cinema(movie)
    await _real_titles(candidates)  # כותרות-URL קורות גם כאן
    if chain == "rav-hen" and not any(c["platform"] == "rav-hen" for c in candidates):
        candidates += await _ravhen_from_planet(candidates)
    platforms = [p for p in _CINEMA_PLATFORMS if p[0] == chain] if chain else _CINEMA_PLATFORMS
    return {**_pick_cinema(movie, candidates, platforms, drop_listings=False), "via": "brave"}


# דף אירוע "רפאים" (QA חי הופעות #2 — עומר אדם בקופת): הדף קיים, הכותרת מושלמת,
# אבל אין בו אף מועד לרכישה — מידע על מופע שעבר + "הרשמו לעדכונים" בלבד. בלי בדיקת
# חיות הריצה נשלחה לדף מת והלקוח קיבל sold_out כוזב. המרקרים אומתו חי (19.7):
# דפי show/event חיים בקופת ("לרכישת כרטיסים") ובלאן ("רכישת כרטיסים"/"הזמנת
# כרטיסים") מציגים כפתור רכישה; דף הרפאים של עומר אדם — אפס מופעים לכולם.
_EVENT_ALIVE_MARKS = ("רכישת כרטיסים", "הזמנת כרטיסים", "בחירת מושבים")

_TITLE_YEAR = re.compile(r"\b(20\d{2})\b")


def _demote_stale_years(candidates: list[dict]) -> list[dict]:
    """מועמד שכל השנים בכותרתו כבר עברו ("עדן חסון 2024" — QA חי הופעות #4) הוא
    כמעט תמיד דף אירוע ישן; לא נזרק (ליתר ביטחון) אלא יורד לתחתית — מועמד עדכני
    גובר עליו, וברשימת many הלקוח רואה קודם את העדכני. מיון יציב — סדר Brave
    נשמר בתוך כל קבוצה."""
    this_year = datetime.date.today().year

    def _stale(c: dict) -> bool:
        years = [int(y) for y in _TITLE_YEAR.findall(c["title"])]
        return bool(years) and max(years) < this_year

    return sorted(candidates, key=_stale)


def _event_looks_dead(body: str) -> bool:
    return not any(m in body for m in _EVENT_ALIVE_MARKS)


async def _event_dead(url: str) -> bool:
    """דף אירוע (לאן/קופת) בלי שום סימן רכישה — רפאים. כשל רשת → False
    (ספק-חי עדיף על פסילת שווא, כמו _ontopo_dead)."""
    try:
        async with httpx.AsyncClient(
            timeout=8, headers={"User-Agent": UA}, follow_redirects=True
        ) as http:
            return _event_looks_dead((await http.get(url)).text)
    except Exception:  # noqa: BLE001
        return False


async def resolve_event_url(artist: str, venue: str = "") -> dict:
    """כמו resolve_cinema_url, להופעות: אותו חוזה החזרה בדיוק, על _EVENT_PLATFORMS.
    many הוא פיצ'ר — שני מועדים לאותו אמן בלאן = שתי רשומות עם תאריך+היכל בכותרת,
    והרשימה שהלקוח מקבל היא המועדים האמיתיים. drop_listings=False — ה-regex כבר
    משאיר רק דפי אירוע. אין fallbackים של Phase 4-lite (מסעדות בלבד).
    מנצח 'one' עובר בדיקת חיות (_event_dead) — דף רפאים נפסל ובוחרים מחדש מהשאר,
    באותו דפוס של לולאת דף-הרפאים של המסעדות (_pick)."""
    candidates = await search_events(artist, venue)
    await _real_titles(candidates)
    pool = _demote_stale_years(candidates)
    while True:
        picked = _pick_cinema(artist, pool, _EVENT_PLATFORMS, drop_listings=False)
        if picked["status"] != "one" or not await _event_dead(picked["url"]):
            return picked
        log.info("resolve: dead event page dropped for '%s': %s", artist, picked["url"])
        pool = [c for c in pool if c["url"] != picked["url"]]


def _pick_cinema(name: str, candidates: list[dict], platforms, *, drop_listings: bool) -> dict:
    """דיסאמביגואציה פלטפורמה-פלטפורמה לפי סדר התיעדוף — ליבת ה-resolver של
    קולנוע והופעות. (המסעדות גדלו למסלול דו-שלבי משלהן — _select + לולאת
    דף-הרפאים ב-_pick — ולא עוברות כאן; העולמות מופרדים בכוונה עד ריצה חיה
    על ליבה משותפת.) drop_listings: סינון דילים/שוברים (רלוונטי למסעדות בלבד)."""
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
