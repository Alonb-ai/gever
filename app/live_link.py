"""דפדפן גבר, שלב א' — לינק ממותג לקיר-כרטיס.

הבעיה: לינק Live View גולמי חושף browserbase.com (מסגיר אוטומציה — חוק ברזל של
הדמות). הפתרון: token אקראי קצר בדומיין שלנו (https://geverai.duckdns.org/b/xxx)
שמגיש עמוד עטיפה ממותג עם ה-Live View ב-iframe — הלקוח לא רואה browserbase בכלל.

in-memory בכוונה: restart משחרר את כל סשני ה-Browserbase (sweep בעליית השרת),
אז token שנשמר היה מצביע על סשן מת ממילא. TTL מיושר לתקרת הסשן (1800s).

הזרקת פרטי אשראי (שלב ג', מובייל) תיבנה על אותו עמוד — ראה
docs/plans/gever-browser.md. כאן רק העטיפה.
"""

import secrets
import time

from app.config import settings

TTL_S = 1800  # תקרת סשן Browserbase — אחרי זה ה-Live View מת ממילא

_links: dict[str, tuple[str, float]] = {}  # token -> (live_view_url, expires_at)


def wrap(live_url: str | None) -> str | None:
    """live-view URL → לינק ממותג בדומיין שלנו. None נשאר None (אין סשן = אין לינק)."""
    if not live_url:
        return None
    now = time.time()
    for t in [t for t, (_, exp) in _links.items() if exp < now]:  # ניקוי פגי-תוקף אגבי
        _links.pop(t, None)
    token = secrets.token_urlsafe(6)  # 48 ביט — לא ניתן לניחוש בחלון של 30 דק'
    _links[token] = (live_url, now + TTL_S)
    return f"{settings.public_base_url}/b/{token}"


def resolve(token: str) -> str | None:
    """token → live-view URL, או None אם לא קיים / פג תוקף."""
    item = _links.get(token)
    if not item:
        return None
    url, exp = item
    if time.time() > exp:
        _links.pop(token, None)
        return None
    return url


# עמוד העטיפה: iframe במסך מלא + מיתוג בפלטה של דף הנחיתה (web/index.html —
# הטוקנים מרוכזים ב-docs/marketing/design-tokens.md): רקע #16140f, משטח #211e17,
# טקסט #F3ECDD, משני #c4bcad, accent #FF6B35, פונטים IBM Plex Sans Hebrew + Alef.
# ה-iframe אושר רשמית ע"י Browserbase (sandbox + clipboard per docs), ואומת ב-PoC
# שאין X-Frame-Options/frame-ancestors. navbar=false מוריד את סרגל ה-live view.
PAGE_HTML = """<!doctype html>
<html dir="rtl" lang="he">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>גבר — משלימים את ההזמנה</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alef:wght@700&family=IBM+Plex+Sans+Hebrew:wght@400;600&display=swap" rel="stylesheet">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{display:flex;flex-direction:column;background:#16140f;color:#F3ECDD;
    font-family:'IBM Plex Sans Hebrew',sans-serif;-webkit-font-smoothing:antialiased}
  ::selection{background:#FF6B35;color:#16140f}
  :focus-visible{outline:3px solid #54c9c9;outline-offset:2px;border-radius:6px}
  header{padding:10px 12px}
  .bar{display:flex;align-items:center;justify-content:space-between;gap:12px;
    background:#211e17;border-radius:18px;padding:10px 18px;box-shadow:0 8px 26px rgba(0,0,0,.3)}
  .logo{font-family:'Alef',sans-serif;font-weight:700;font-size:24px;letter-spacing:-.01em}
  .logo b{color:#FF6B35}
  #st{font-weight:400;font-size:13px;color:#c4bcad}
  main{flex:1;display:flex;padding:0 12px 12px}
  iframe{flex:1;border:0;width:100%;background:#211e17;border-radius:18px}
</style>
</head>
<body>
<header><div class="bar"><span class="logo">גבר<b>.</b></span>
  <span id="st">נשאר רק להשלים את הפרטים</span></div></header>
<main><iframe src="__LIVE__" sandbox="allow-same-origin allow-scripts"
        allow="clipboard-read; clipboard-write"></iframe></main>
<script>
window.addEventListener("message", function (ev) {
  if (ev.data === "browserbase-disconnected") {
    var st = document.getElementById("st");
    st.textContent = "סיימנו כאן — אפשר לחזור לוואטסאפ";
    st.style.color = "#FF6B35";
  }
});
</script>
</body>
</html>"""

EXPIRED_HTML = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>גבר</title>
<link href="https://fonts.googleapis.com/css2?family=Alef:wght@700&family=IBM+Plex+Sans+Hebrew:wght@400;600&display=swap" rel="stylesheet">
<style>body{font-family:'IBM Plex Sans Hebrew',sans-serif;background:#16140f;color:#F3ECDD;
  display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{font-family:'Alef',sans-serif;font-weight:700}
  p{color:#c4bcad;margin-top:10px}
</style></head>
<body><div><h2>הלינק כבר לא בתוקף 🫠</h2><p>תכתוב לגבר בוואטסאפ והוא יפתח לך אחד חדש.</p></div>
</body></html>"""


def page_for(token: str) -> str | None:
    """ה-HTML המלא ללינק, או None אם ה-token מת."""
    url = resolve(token)
    if not url:
        return None
    sep = "&" if "?" in url else "?"
    return PAGE_HTML.replace("__LIVE__", f"{url}{sep}navbar=false")
