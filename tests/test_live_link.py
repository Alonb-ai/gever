"""דפדפן גבר שלב א' — לינק ממותג: token בדומיין שלנו במקום URL של browserbase,
עמוד עטיפה עם iframe, תוקף, ו-404 ידידותי על token מת."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import live_link  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

BB_URL = "https://www.browserbase.com/devtools-fullscreen/inspector.html?wss=connect.browserbase.com/debug/s1/devtools/page/P1?debug=true"


def test_wrap_returns_branded_url_and_resolves():
    link = live_link.wrap(BB_URL)
    assert link.startswith(f"{settings.public_base_url}/b/")
    assert "browserbase" not in link
    token = link.rsplit("/", 1)[1]
    assert live_link.resolve(token) == BB_URL


def test_wrap_none_stays_none():
    """אין live view (סשן מת) → אין לינק — הקורא נופל ללינק דף רגיל."""
    assert live_link.wrap(None) is None
    assert live_link.wrap("") is None


def test_resolve_unknown_and_expired(monkeypatch):
    assert live_link.resolve("no-such-token") is None
    link = live_link.wrap(BB_URL)
    token = link.rsplit("/", 1)[1]
    monkeypatch.setattr(live_link.time, "time", lambda: 9e12)  # הרחק אחרי ה-TTL
    assert live_link.resolve(token) is None
    assert token not in live_link._links  # פג-תוקף גם נמחק


def test_page_embeds_live_view_with_navbar_off():
    token = live_link.wrap(BB_URL).rsplit("/", 1)[1]
    html = live_link.page_for(token)
    assert f"{BB_URL}&navbar=false" in html
    assert 'dir="rtl"' in html


def test_route_serves_wrapper_and_404s_dead_token():
    client = TestClient(app)
    token = live_link.wrap(BB_URL).rsplit("/", 1)[1]
    ok = client.get(f"/b/{token}")
    assert ok.status_code == 200
    assert "<iframe" in ok.text and BB_URL in ok.text
    dead = client.get("/b/xxxxxxxx")
    assert dead.status_code == 404
    assert "לא בתוקף" in dead.text


def test_cdp_ws_extracted_from_fullscreen_url():
    """שלב ב': ה-endpoint ל-CDP נחלץ מפרמטר ה-wss של ה-live view (כולל ?debug פנימי)."""
    from app import live_link

    url = (
        "https://www.browserbase.com/devtools-fullscreen/inspector.html"
        "?wss=connect.browserbase.com/debug/0d354159-ab/devtools/page/4E7B?debug=true"
    )
    assert live_link._cdp_ws(url).startswith("wss://connect.browserbase.com/debug/0d354159-ab")
    assert live_link._cdp_ws("https://x.com/no-wss-here") == ""


def test_page_embeds_keyboard_bar_with_cdp():
    """העמוד מכיל את פס ההקלדה וה-CDP מוזרק; בלי wss — הפלייסהולדר לא נשאר בעמוד."""
    from app import live_link

    tok = live_link.wrap(
        "https://www.browserbase.com/devtools-fullscreen/inspector.html"
        "?wss=connect.browserbase.com/debug/s1/devtools/page/P1?debug=true"
    ).split("/b/")[1]
    html = live_link.page_for(tok)
    assert 'id="kb-in"' in html and "Input.insertText" in html
    assert "wss://connect.browserbase.com/debug/s1" in html
    assert "__CDP__" not in html and "__LIVE__" not in html

    tok2 = live_link.wrap("https://somewhere.example/live-no-wss").split("/b/")[1]
    html2 = live_link.page_for(tok2)
    assert "__CDP__" not in html2  # ריק → הפס מוסתר ב-JS, אין שאריות תבנית
