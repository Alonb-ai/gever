# גבר — Design Tokens (חולץ מ-`web/index.html`)

מקור האמת הוויזואלי של המותג הוא דף הנחיתה החי. כל עמוד חדש — ובראשו **"דפדפן גבר"**
(עמוד השלמת האשראי) — משתמש בטוקנים האלה כמו שהם.

> הערה: הפלטה ב-`brand-voice.md` (קרם `#FAF3E8` / פחם `#222`) היא הגרסה הבהירה
> ההיסטורית. הדף החי הוא **dark** — זה מה שמחייב.

## צבעים

| טוקן | Hex | שימוש בדף |
|---|---|---|
| `--bg` | `#16140f` | רקע הדף; גם צבע טקסט על משטחי accent/קרם |
| `--surface` | `#211e17` | כרטיסים, nav, צ'יפים, כפתור משני |
| `--surface-raised` | `#26241d` | מסגרת הטלפון בהדגמה |
| `--accent` | `#FF6B35` | כתום המותג: CTA ראשי, הדגשות, נקודת הלוגו |
| `--accent-tint` | `rgba(255,107,53,.14)` | רקע לאייקונים על surface |
| `--accent-on-cream` | `#c2491b` | כתום כהה לטקסט על רקע קרם |
| `--cream` | `#F3ECDD` | טקסט ראשי; גם רקע הכרטיס הבהיר (versus) |
| `--text-muted` | `#c4bcad` | טקסט משני / פסקאות |
| `--text-dim` | `#8c8475` | מיקרו-קופי, תוויות |
| `--text-faint` | `#9c9485` / `#7a7367` | פוטר |
| `--ink` | `#16140f` / `#2b2620` | טקסט על רקעים בהירים/כתומים |
| `--ink-on-accent` | `#4a2a18` / `#5a3320` | טקסט משני על רקע כתום |
| `--teal` | `#1CA3A3` | משני רשמי (וי, badges) |
| `--teal-bright` | `#54c9c9` | kickers של סקשנים, focus ring |
| `--teal-soft` | `#5fcfc4` | kicker על רקע teal כהה |
| `--teal-deep` | `#103a3a` | רקע סקשן "איך זה עובד" |
| `--teal-deep-text` | `#eaf6f3` / `#bcdbd6` | טקסט על `--teal-deep` |
| `--teal-dark` | `#147878` | אייקוני וי על קרם |
| `--wa-green` | `#25D366` | אייקון וואטסאפ בלבד |
| `--error-tint` / `--error-text` | `rgba(194,64,42,.2)` / `#e59177` | סימוני ✕ |

צבעי ה-mockup של צ'אט וואטסאפ (`#0b141a`, `#1f2c34`, `#202c33`, `#2a3942`,
`#005c4b`, `#00a884`, `#8696a0`, `#8ad3c2`, `#53bdeb`, `#f7e9b0`) הם חיקוי UI של
WhatsApp — **לא** חלק מפלטת המותג. לא להשתמש בהם מחוץ להדגמת צ'אט.

## טיפוגרפיה

| טוקן | ערך |
|---|---|
| Display (כותרות) | `'Alef', sans-serif` — משקלים 700 / 900 (נטען דרך `var(--display,'Alef',sans-serif)`) |
| Body | `'IBM Plex Sans Hebrew', sans-serif` — משקלים 300–700 |
| H1 | `clamp(50px,7vw,92px)` · 900 · `line-height:.98` · `letter-spacing:-.01em` |
| H2 | `clamp(32px,4.6vw,54px)` · 900 · `line-height:1.04` · `letter-spacing:-.01em` |
| H3 (כרטיס) | 24–26px · 700 |
| גוף | 16px · `line-height:1.6` |
| kicker סקשן | 13px · 600 · `letter-spacing:.04em` · צבע teal |
| מיקרו-קופי | 13–14px · צבע `--text-dim` |

(‏`Frank Ruhl Libre` נטען ב-`<link>` אבל לא בשימוש בפועל — לא לאמץ.)

## ספייסינג ולייאאוט

| טוקן | ערך |
|---|---|
| רוחב container | `max-width:1160px` · padding אופקי `26px` |
| ריווח אנכי סקשן | `84px` (סקשן צר: 78–80px) |
| padding כרטיס | `32px 28px` (כרטיס בולט: `34px 30px`) |
| gap בגריד | `22px` (hero: `50px`) |
| breakpoints | `900px` (גרידים → עמודה), `760px` (הסתרת קישורי nav) |

## פינות (radius)

| אלמנט | radius |
|---|---|
| כפתור | `12–14px` |
| כרטיס | `22–24px` |
| בלוק גדול (CTA, founder) | `30–32px` |
| צ'יפ / pill / badge | `999px` |
| nav bar | `18px` |

## כפתורים

| וריאנט | מתכון |
|---|---|
| ראשי | רקע `#FF6B35`, טקסט `#16140f`, 600, `padding:16px 30px`, radius `14px`, צל `0 12px 28px rgba(255,107,53,.26)` |
| משני | רקע `#211e17`, טקסט `#F3ECDD`, אותו padding/radius |
| outline | `border:1.5px solid rgba(243,236,221,.28)`, טקסט `#F3ECDD` |
| כהה (על רקע accent) | רקע `#16140f`, טקסט `#fff` |
| לבן (על רקע accent) | רקע `#fff`, טקסט `#16140f` |

## צללים, פוקוס ותנועה

- צל כרטיס/nav: `0 8px 26px rgba(0,0,0,.3)` · צל עמוק: `0 20px 44px rgba(0,0,0,.45)`
- זוהר accent: `0 24px 56px rgba(255,107,53,.3)`
- focus: `outline:3px solid #54c9c9; outline-offset:2px`
- selection: רקע `#FF6B35`, טקסט `#16140f`
- easing חתימה: `cubic-bezier(.2,.7,.2,1)` · משכים `.32s–.5s` · כניסות `translateY(9–12px)+fade`
- חובה לכבד `prefers-reduced-motion: reduce` (בדף: `*{animation:none!important}`)

## Snippet מוכן להעתקה (לדפדפן גבר)

```css
:root {
  /* colors */
  --bg: #16140f;
  --surface: #211e17;
  --surface-raised: #26241d;
  --accent: #FF6B35;
  --accent-tint: rgba(255, 107, 53, .14);
  --cream: #F3ECDD;
  --text-muted: #c4bcad;
  --text-dim: #8c8475;
  --ink: #16140f;
  --teal: #1CA3A3;
  --teal-bright: #54c9c9;
  --teal-deep: #103a3a;
  --wa-green: #25D366;
  /* type */
  --display: 'Alef', sans-serif;
  --body: 'IBM Plex Sans Hebrew', sans-serif;
  /* shape */
  --radius-btn: 14px;
  --radius-card: 24px;
  --radius-pill: 999px;
  /* motion */
  --ease: cubic-bezier(.2, .7, .2, 1);
}

html { direction: rtl; }
body {
  background: var(--bg);
  color: var(--cream);
  font-family: var(--body);
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3 { font-family: var(--display); font-weight: 900; letter-spacing: -.01em; }
::selection { background: var(--accent); color: var(--ink); }
:focus-visible { outline: 3px solid var(--teal-bright); outline-offset: 2px; border-radius: 6px; }

.btn-primary {
  background: var(--accent);
  color: var(--ink);
  font-weight: 600;
  padding: 16px 30px;
  border-radius: var(--radius-btn);
  box-shadow: 0 12px 28px rgba(255, 107, 53, .26);
}
.card {
  background: var(--surface);
  border-radius: var(--radius-card);
  padding: 32px 28px;
}
```

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Alef:wght@400;700&family=IBM+Plex+Sans+Hebrew:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```
