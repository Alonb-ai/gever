"""דפדפן גבר — לינק ממותג + מקלדת מובייל לקיר-כרטיס.

שלב א': לינק Live View גולמי חושף browserbase.com (מסגיר אוטומציה — חוק ברזל של
הדמות). הפתרון: token אקראי קצר בדומיין שלנו (https://geverai.duckdns.org/b/xxx)
שמגיש עמוד עטיפה ממותג עם ה-Live View ב-iframe — הלקוח לא רואה browserbase בכלל.

שלב ב' (המקלדת): ה-Live View הוא שידור-מסך — טאפ על שדה לא פותח מקלדת במובייל
(אין input אמיתי בפוקוס; Browserbase: "mobile keyboards aren't officially
supported"). הפתרון: פס הקלדה שלנו בתחתית העמוד — input אמיתי שפותח מקלדת
native, וכל תו מוזרם ב-WebSocket *ישירות מהדפדפן של הלקוח* ל-endpoint ה-CDP
של הסשן (Input.insertText / dispatchKeyEvent). PCI: פרטי הכרטיס זורמים
לקוח→Browserbase בלבד — השרת שלנו מגיש HTML ולא רואה אף תו. הצנרת אומתה
ב-PoC על סשן אמיתי (14-15.7).

in-memory בכוונה: restart משחרר את כל סשני ה-Browserbase (sweep בעליית השרת),
אז token שנשמר היה מצביע על סשן מת ממילא. TTL מיושר לתקרת הסשן (1800s).
תוכנית מלאה: docs/plans/gever-browser.md.
"""

import secrets
import time
from urllib.parse import parse_qs, urlparse

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


def _cdp_ws(live_url: str) -> str:
    """ה-endpoint ה-page-scoped של הסשן מתוך ה-debuggerFullscreenUrl (פרמטר wss=).
    זה אותו endpoint שה-live view עצמו משתמש בו — פתוח למחזיק ה-URL בלבד, בלי
    API key (אומת ב-PoC). ריק אם הפורמט השתנה — הפס פשוט לא יופיע, הצפייה תעבוד."""
    try:
        wss = (parse_qs(urlparse(live_url).query).get("wss") or [""])[0]
    except ValueError:
        return ""
    return f"wss://{wss}" if wss else ""


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
  main{flex:1;display:flex;padding:0 12px 0}
  iframe{flex:1;border:0;width:100%;background:#211e17;border-radius:18px}
  footer{padding:10px 12px 12px}
  .kb{display:flex;gap:8px;background:#211e17;border-radius:18px;padding:10px;
    box-shadow:0 8px 26px rgba(0,0,0,.3)}
  .kb input{flex:1;min-width:0;background:#16140f;border:1px solid #3a352a;border-radius:12px;
    padding:12px 14px;color:#F3ECDD;font:inherit;font-size:16px}
  .kb input::placeholder{color:#c4bcad}
  .kb button{background:#FF6B35;border:0;border-radius:12px;padding:12px 16px;color:#16140f;
    font:inherit;font-weight:600;white-space:nowrap}
  .hint{font-size:12px;color:#c4bcad;text-align:center;margin-top:8px}
</style>
</head>
<body>
<header><div class="bar"><span class="logo">גבר<b>.</b></span>
  <span id="st">נשאר רק להשלים את הפרטים</span></div></header>
<main><iframe src="__LIVE__" sandbox="allow-same-origin allow-scripts"
        allow="clipboard-read; clipboard-write"></iframe></main>
<footer id="kb-wrap">
  <div class="kb">
    <input id="kb-in" type="text" inputmode="text" autocomplete="off" autocorrect="off"
           autocapitalize="off" spellcheck="false"
           placeholder="טאפ על שדה למעלה, ואז הקלד כאן">
    <button id="kb-next" type="button">⇥ שדה הבא</button>
  </div>
  <p class="hint">ההקלדה עוברת ישירות לדף המאובטח של בית העסק — לא נשמרת אצל גבר.</p>
</footer>
<script>
window.addEventListener("message", function (ev) {
  if (ev.data === "browserbase-disconnected") {
    var st = document.getElementById("st");
    st.textContent = "סיימנו כאן — אפשר לחזור לוואטסאפ";
    st.style.color = "#FF6B35";
  }
});
/* שלב ב' — פס ההקלדה: input אמיתי (פותח מקלדת native במובייל) שמזרים כל תו
   ב-CDP ישירות לסשן. הזרם: הדפדפן של הלקוח → Browserbase. לא עובר בשרת שלנו. */
(function () {
  var CDP = "__CDP__";
  var wrap = document.getElementById("kb-wrap");
  if (!CDP) { wrap.style.display = "none"; return; }
  var ws = null, msgId = 0;
  function connect() {
    ws = new WebSocket(CDP);
    ws.onclose = function () { ws = null; };
  }
  function send(method, params) {
    if (!ws || ws.readyState !== 1) return;
    ws.send(JSON.stringify({ id: ++msgId, method: method, params: params }));
  }
  function key(type, name, code, vk) {
    send("Input.dispatchKeyEvent", { type: type, key: name, code: code,
      windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
  }
  function backspace() { key("rawKeyDown", "Backspace", "Backspace", 8); key("keyUp", "Backspace", "Backspace", 8); }
  connect();
  var inp = document.getElementById("kb-in"), prev = "";
  inp.addEventListener("input", function () {
    var v = inp.value;
    if (v.length > prev.length && v.slice(0, prev.length) === prev) {
      send("Input.insertText", { text: v.slice(prev.length) });      // הקלדה רגילה
    } else if (v.length < prev.length && prev.slice(0, v.length) === v) {
      for (var i = 0; i < prev.length - v.length; i++) backspace();  // מחיקה
    } else {                                                          // עריכה באמצע
      for (var j = 0; j < prev.length; j++) backspace();
      if (v) send("Input.insertText", { text: v });
    }
    prev = v;
  });
  document.getElementById("kb-next").addEventListener("click", function () {
    key("rawKeyDown", "Tab", "Tab", 9); key("keyUp", "Tab", "Tab", 9);  // מעבר שדה
    inp.value = ""; prev = ""; inp.focus();                             // שדה חדש = פס נקי
  });
})();
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
    return PAGE_HTML.replace("__LIVE__", f"{url}{sep}navbar=false").replace("__CDP__", _cdp_ws(url))
