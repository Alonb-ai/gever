# Real Booking — confirm-to-commit (beyond DRY_RUN)

Status today: a booking reaches the Ontopo confirmation screen and `_booking[phone]`
is set to `state: "pending"`, but `book_table` is always called with `dry_run=True`,
so nothing is ever actually booked and we never say "סגור". This plan adds the
final commit — truthfully — gated behind a real user "מאשר".

## Goal

Turn the existing `pending` gate into a real two-step booking:

1. Gever reaches the Ontopo confirmation screen (already works) and asks "מאשר?".
2. On the user's next "מאשר"/"כן סגור", we run the **actual** final commit
   (`book_table(..., dry_run=False)` → the act on "אשר את ההזמנה סופית"), and
   **only then** say "סגור ✅" — truthfully, with a confirmation number.
3. The booking uses the user's **WhatsApp phone** (the `phone` argument) and a
   required booker **name** (asked for if not already in the profile).
4. When really confirmed, Gever sends a clean **summary** to WhatsApp
   (restaurant, date, time, party, confirmation number).

Hard rule preserved: never say "סגור"/"בוצע"/"אושר" before a real confirmation
from `book_table(dry_run=False)`. A `settings.dry_run` flag (default `True`)
keeps the safe behavior until Alon flips it.

## Design and interfaces

### The lazy state machine — one per-phone pending dict

Today `_booking[phone] = {"state": ..., "info": ...}` already tracks ground truth.
The DRY_RUN run leaves `state="pending"`. The only thing missing is **the booked
fields to replay on commit**. So: keep `_booking` exactly as-is for the truth-note,
and add one sibling dict that holds the resolved booking ready to commit.

```python
# pipeline.py — sibling of _booking, same in-memory-per-process model
_pending_commit: dict = {}   # phone -> {restaurant, page_url, date, time, party_size, name}
```

This is the whole "framework": one dict, set when we reach `pending`, popped on
commit or cancel. No new table, no class, no abstraction. (Same lifetime caveat
as `_chats`/`_booking`: in-memory per process, lost on restart — acceptable, see
"How it fits".)

### `settings.dry_run` flag

```python
# config.py
dry_run: bool = True   # ponytail: real booking off by default; flip via .env / Coolify
```

- When `dry_run=True` (default): behaves exactly like today — reach the
  confirmation screen, set `pending`, ask "מאשר?", and on "מאשר" we DO NOT commit;
  Gever stays honest ("הכל מוכן אבל אני במצב בדיקה, עוד לא סגרתי בפועל" — the
  existing `pending` truth-note already says this).
- When `dry_run=False`: the "מאשר" after the gate runs the real commit.

The flag also lets us keep the `pending` truth-note honest: when `dry_run=True`
the note must keep saying "מצב בדיקה ולא סגרת"; when `dry_run=False` and we're at
`pending`, the note should say "אתה ממש על סף הסגירה, מחכה לאישור שלו" (so the
model asks for the go-ahead, not pretends it's done). Small branch in `_truth_note`.

### The flow (dry_run=False)

```
user: "סגור לי הדסון מחר 8 בערב 4 אנשים"
  → converse → ready=True → run_booking()
  → resolve + book_table(dry_run=True)  [reaches confirm screen]
  → _booking[phone] = "pending", _pending_commit[phone] = {fields...}
  → "כמעט סגור — הדסון, מחר 20:00, 4 סועדים. מאשר?"   (from ontopo dry_run notify)

user: "מאשר"  /  "כן"  /  "סגור"
  → handle_inbound sees _pending_commit[phone] exists  → COMMIT PATH (not converse-for-new-booking)
  → confirm intent?  yes → run_commit(phone)
       → book_table(dry_run=False) → act "אשר את ההזמנה סופית" → confirmation number
       → _booking[phone] = "done", log_booking(status="confirmed")
       → send WhatsApp summary "סגור ✅ ..."
       → pop _pending_commit[phone]
  → no / "בטל" → pop _pending_commit, _booking → "סבבה ביטלתי לא סגרתי כלום"
```

### Routing the "מאשר" turn — where it hooks in `handle_inbound`

The confirm/cancel decision must be made by the model (the user won't always type
exactly "מאשר" — could be "יאללה", "סגור את זה", "כן בוא נלך על זה", "רגע לא").
We already call `converse()` every turn and it returns JSON. The lightest hook:

- In `handle_inbound`, **before** the normal `ready`-spawns-booking path, check
  `if phone in _pending_commit:`. If so, this turn is an answer to "מאשר?".
- Add one boolean to the Gemini `_SCHEMA`/`_EXTRACT`: `confirm` — "true רק כשהמשתמש
  מאשר במפורש לסגור את ההזמנה שמחכה לאישור". The `pending` truth-note already tells
  the model a booking is waiting at the confirmation screen, so it has the context
  to set `confirm` correctly.
- So: when `phone in _pending_commit` and `result.get("confirm")` → `_spawn(run_commit(phone))`.
  When `phone in _pending_commit` and the model reads it as a cancel/change →
  drop `_pending_commit` and let the normal flow continue (a changed detail starts
  a fresh resolve via the usual `ready` path).

This reuses the existing single `converse()` call and JSON contract — no second
LLM call, no parallel router. `confirm` simply joins `ready` as an output field.

### `run_commit(phone)` — the real commit (mirror of `run_booking`)

```python
async def run_commit(phone: str) -> None:
    job = _pending_commit.get(phone)
    if not job:
        return
    if not job.get("name"):                 # safety: never book nameless
        await send_text(phone, "רגע על איזה שם לסגור")   # asks; stays pending
        return
    _booking[phone] = {"state": "working", "info": ""}
    try:
        res = await asyncio.wait_for(
            book_table(
                restaurant=job["restaurant"],
                page_url=job["page_url"],
                date=job["date"],
                time=job["time"],
                party_size=job["party_size"],
                name=job["name"],
                phone=phone,                 # ← the WhatsApp number, as the booking phone
                dry_run=False,               # ← THE REAL COMMIT
                notify=lambda m: send_text(phone, m),
            ),
            timeout=BOOKING_TIMEOUT_S,
        )
        if res.success:
            d = res.details or {}
            _booking[phone] = {"state": "done", "info": d.get("confirmation") or ""}
            await memory.log_booking(
                phone, d.get("restaurant", job["restaurant"]),
                d.get("date", job["date"]), d.get("time", job["time"]),
                job["party_size"], status="confirmed",
            )
            await send_text(phone, _summary(d, job))   # the clean WhatsApp summary
            _reset_next.add(phone)                      # next msg = fresh page (booking done)
        else:
            _booking[phone] = {"state": "failed", "info": res.summary}
            await send_text(phone, res.summary + engine.error_detail(...))
    except (asyncio.TimeoutError, Exception) as e:
        # same honest-failure handling as run_booking
        ...
    finally:
        _pending_commit.pop(phone, None)
```

Note: `book_table(dry_run=False)` already does the whole second half — it
re-navigates, re-selects party/date/time, fills name+phone, then acts
"אשר את ההזמנה סופית" and extracts the confirmation number (ontopo.py lines
275-285). It also already calls `notify("סגור ✅ ...")` itself on success. So our
`_summary` is the **WhatsApp-facing** recap; we can either rely on ontopo's own
`notify("סגור ✅")` and add a second tidy summary line, or pass `notify=_noop` for
the commit run and send only our `_summary`. Recommend the latter (one clean
"סגור" message, fully controlled here) — see Open Questions.

Important truth point: `book_table(dry_run=False)` **re-runs the whole playbook
from `page_url`** (new Browserbase session). It does not resume the dry-run
session. That is fine and actually safer (stateless), but it means we re-verify
availability at commit time — if the slot vanished between gate and confirm,
`book_table` returns `success=False` honestly and we say so. Good.

### The booker NAME — required, asked if missing

`book_table` already accepts `name` and only fills it when truthy (ontopo.py
line 225). Source of name, in order:
1. `result["name"]` from the conversation (the user said it), else
2. the Supabase profile `name` (decrypted; `get_profile`), else
3. **ask**: Gever asks "על איזה שם לסגור" and does NOT proceed until he has it.

Where to enforce: capture `name` into `_pending_commit[phone]["name"]` when we set
up the pending job in `run_booking`, resolving it via profile if the conversation
didn't carry it. If still empty at commit time, `run_commit` asks and stays
pending (the dict survives, the user answers, the next "מאשר" carries the name —
or simpler: the name answer goes through `converse`, fills `result["name"]`, we
update `_pending_commit[phone]["name"]`, and re-ask "מאשר?"). The phone is never
asked — it is always the WhatsApp `phone` argument.

### The phone — use the WhatsApp number

`phone` (the `handle_inbound` argument, = `msg["from"]`) is passed straight into
`book_table(phone=phone)`. Ontopo's widget fills it via the existing
`if phone: act("מלא טלפון: {phone}")` line. No new plumbing, no asking the user.
(Format note in Open Questions — Ontopo may want a local `0`-prefixed Israeli
number, while WhatsApp gives `9725...`.)

### The WhatsApp summary

```python
def _summary(d: dict, job: dict) -> str:
    conf = d.get("confirmation")
    parts = [
        f"סגור ✅ {d.get('restaurant') or job['restaurant']}",
        f"{d.get('date') or job['date']} {d.get('time') or job['time']}",
        f"{job['party_size']} סועדים",
    ]
    line = "  ".join(parts)
    if conf:
        line += f"\nמספר אישור {conf}"
    return line
```

No-punctuation persona, only the allowed ✅. Sent exactly once, only after a real
confirmation. If `book_table` returns success but no confirmation number was
extractable, we still say "סגור" (the act succeeded) but omit the number — and
this is the one place to double-check during live testing (see Open Questions:
"what counts as proof").

## How it fits the existing code

- **Single process = the dicts are safe.** The Dockerfile runs
  `uvicorn app.main:app` with **no `--workers`** flag → one worker, one process.
  So `_chats`, `_booking`, and the new `_pending_commit` all live in the same
  process and stay coherent across the "ask → מאשר" turns. (If Alon ever adds
  `--workers N` or gunicorn, these in-memory dicts break across workers — that is
  the known memory diagnosis and is out of scope here; flag it, don't solve it.)
- **`_booking` stays the single source of truth** for `_truth_note`; we only add
  `_pending_commit` to hold the replay fields. Existing `pending` handling in
  `_truth_note` is reused (with the small dry_run-aware wording tweak).
- **`book_table` is already commit-ready**: it takes `name`/`phone`, has the
  `dry_run` gate, and the real act + confirmation-number extraction already exist
  (lines 275-285). We are flipping a flag and wiring the second turn — not writing
  new automation.
- **`log_booking`** already exists and writes to the live `bookings` table with a
  `status` — we call it with `status="confirmed"` only on real success. No schema
  change (status is free text; "confirmed" already named in schema.sql comments).
- **Persona / truth rule** untouched — the model never declares success; the
  "סגור" line is sent by `run_commit` after real proof, exactly as the iron rule
  in `intent.py` requires.

## Files and changes (minimal)

- **`app/config.py`** — add `dry_run: bool = True`.
- **`app/pipeline.py`** —
  - add `_pending_commit: dict = {}`;
  - in `run_booking`, after the DRY_RUN success sets `pending`, also populate
    `_pending_commit[phone]` with `{restaurant=name, page_url=found["url"], date,
    time(resolved), party_size, name(resolved via convo→profile)}`;
  - add `confirm` to `_SCHEMA` + a line to `_EXTRACT`;
  - in `_truth_note`, branch the `pending` text on `settings.dry_run`;
  - add `run_commit(phone)` and `_summary(...)`;
  - in `handle_inbound`, add the pending-commit branch (confirm → `_spawn(run_commit)`;
    cancel → drop `_pending_commit`).
- **`.env.example`** — add `DRY_RUN=true` with a comment.
- No DB/schema changes. No new table, no new column (`prefs` jsonb untouched).

Net: ~one new flag, one new dict, one new function, two small edits to existing
functions. Surgical.

## Open questions / info needed from Alon

1. **Ontopo login / OTP.** Does committing a real Ontopo booking require an
   account login (phone → SMS OTP) before "אשר את ההזמנה סופית"? The current
   `book_table` flow does **not** log in — it fills name+phone on the widget and
   confirms. If Ontopo gates the final confirm behind OTP, we need an **Alon-in-
   the-loop OTP step**: `book_table` would have to pause at the OTP screen, send
   the code request, and we'd relay the SMS code back in. **This needs live
   testing to even know if it's required.** Plan flags it; does not build it until
   we see the real screen. (If OTP is required, the minimal approach: detect the
   OTP field, `notify` Alon "צריך קוד מ-Ontopo", read his next WhatsApp reply as
   the code, `act` it in — a small extension of the same per-phone pending dict.)
2. **Phone format.** WhatsApp gives `972XXXXXXXXX`. Ontopo's form likely wants
   `0XXXXXXXXX` (Israeli local). Do we normalize `972...` → `0...` before filling?
   (One-liner if yes; confirm during live test.)
3. **Confirmation proof.** What does Ontopo actually show after a real confirm — a
   numeric code, an email-sent message, a "ההזמנה אושרה" banner? The extractor
   asks for "confirmation number"; we need to see the real screen to know whether
   we get a number or just a success state. If only a success state, the summary
   omits the number (still truthful "סגור").
4. **One "סגור" message or two?** ontopo.py's commit path already calls
   `notify("סגור ✅ ...")`. Recommend passing `notify=_noop` to the commit
   `book_table` and sending only our controlled `_summary`, so the user gets
   exactly one clean confirmation. Confirm.
5. **Default really stays True?** Confirm `dry_run` ships `True` and Alon flips it
   in `.env`/Coolify for the first real booking (his own number, his own card-free
   Ontopo flow), with him watching.

## Build steps (ordered)

1. **Flag.** Add `dry_run: bool = True` to `config.py`; add `DRY_RUN=true` to
   `.env.example`. (No behavior change yet — `run_booking` still hardcodes
   `dry_run=True`; that's fine for step 1.)
2. **Pending-commit dict + capture.** Add `_pending_commit`. In `run_booking`,
   when the DRY_RUN run returns success and we set `pending`, also resolve the
   booker name (convo `name` → else profile `name`) and store the replay job in
   `_pending_commit[phone]` (incl. resolved `time`/`date` from `res.details`).
3. **Schema.** Add `confirm` to `_SCHEMA` and one sentence to `_EXTRACT`
   ("`confirm`=true רק כשהמשתמש מאשר במפורש לסגור הזמנה שמחכה לאישור").
4. **Truth-note tweak.** In `_truth_note`, branch the `pending` text on
   `settings.dry_run` (test-mode wording vs. "מחכה לאישור שלו לסגירה").
5. **`run_commit` + `_summary`.** Implement the real commit (mirror
   `run_booking`'s try/timeout/except), name guard, `book_table(dry_run=False,
   phone=phone)`, `log_booking(status="confirmed")`, WhatsApp summary, `pop`.
6. **Route the confirm turn.** In `handle_inbound`, before the `ready` path:
   `if phone in _pending_commit:` → if `result.get("confirm")` →
   `_spawn(run_commit(phone))`; elif user changed/cancelled → drop
   `_pending_commit` and fall through to normal flow.
7. **Local dry-run smoke test.** With `DRY_RUN=true`, confirm nothing changed:
   booking reaches "מאשר?", "מאשר" does NOT book, Gever stays honest. Run
   `ruff check . && ruff format --check . && pytest`.
8. **Live commit test (Alon in the loop).** Set `DRY_RUN=false` on Alon's number
   only. Run one real booking end-to-end and **watch for**: (a) whether Ontopo
   demands OTP/login at the final confirm (→ resolve Open Q1), (b) phone-format
   acceptance (Open Q2), (c) what the confirmation proof looks like (Open Q3).
   Feed findings back; only widen beyond Alon's number once a real "סגור" with a
   verifiable booking has happened.


---

## Ponytail review (over-engineering)

I've now verified every load-bearing claim in the plan against the actual code. The plan's factual claims are accurate: `book_table` already has `name`/`phone`/`dry_run` params (lines 106-116), the dry_run gate returns `details` with resolved `date`/`time`/`party_size` (lines 245-273), the real commit + confirmation extraction exist (275-285), `log_booking(status=...)` takes free-text status, and `_booking`/`_chats`/`_pending` dicts work as described. The plan is genuinely lean in its core. Now I'll apply the ponytail ladder to find the over-build spots.

A few things I can pin down precisely from the code:

1. The plan proposes capturing `page_url`, `restaurant`, resolved `date`/`time`/`party_size`, `name` into `_pending_commit`. But `_booking[phone]["info"]` already holds `res.summary`, and `res.details` (from the dry_run) already contains restaurant/date/time/party_size. The plan stores a *parallel* copy. The only field not already recoverable is `page_url` and the resolved `name`.

2. The plan's `run_commit` re-derives `notify=_noop` debate (Open Q4) — but the code shows `book_table(dry_run=False)` already sends its own `notify("סגור ✅ ...")` with restaurant/date/time/party (line 282-284). The plan's separate `_summary()` function duplicates this almost exactly.

3. The plan adds a `confirm` boolean to the schema AND a `_pending_commit` membership gate AND keeps `ready` — three signals where the existing `ready` field plus the pending state may suffice.

Let me give the final review.

---

PONYTAIL REVIEW — Real Booking plan (`/Users/alonb/Desktop/GeverAI/docs/plans/realbooking.md`)

Verified against the real code. The plan's core is honest and lean — it correctly identifies that `book_table` is already commit-ready (ontopo.py:106-285) and that the work is "flip a flag + wire the second turn." That part is right. But there are three real over-builds and one duplicated function.

PRIORITIZED FINDINGS

1. `_summary()` reinvents the notify line `book_table` already sends · The commit path in ontopo.py:282-284 already does `notify("סגור ✅ {restaurant}, {date} {time}, {party} סועדים.")` — restaurant, date, time, party, the ✅, no punctuation, persona-correct. The plan's `_summary()` rebuilds the identical string and then Open-Q4 agonizes over suppressing the real one with `notify=_noop`. **Leaner:** delete `_summary()`. Keep `book_table`'s own notify as the single "סגור" message. The only thing it lacks is the confirmation number line — and that's a 2-line addition *inside* ontopo's existing notify (it already has `details["confirmation"]` in scope at line 281), not a new pipeline function plus a `_noop` plumbing decision. Net: -1 function, -1 open question.

2. `_pending_commit` largely duplicates data already in `_booking` + dry-run `res.details` · `res.details` from the dry_run already carries `restaurant`, `date`(resolved `actual_date`), `time`(`chosen_time`), `party_size` (ontopo.py:245-256). The *only* fields not already recoverable for a replay are `page_url` (from `found["url"]`) and the resolved `name`. **Leaner:** don't store a 6-field parallel job dict. Store the two missing pieces — `_pending_commit[phone] = {"url": found["url"], "name": resolved_name}` — and read restaurant/date/time/party back from `res.details` (or stash the whole `details` you already built, untouched, instead of hand-copying 6 keys into a new shape). This also kills the date/time "resolve from res.details" step the plan calls out separately in build-step 2. The dict-as-state-machine instinct is correct; just don't re-key data you already have.

3. The `confirm` schema field may be redundant with `ready` · The plan adds a new `confirm` boolean to `_SCHEMA`/`_EXTRACT` *and* gates on `phone in _pending_commit`. But the existing `ready` field already means "user confirmed, go" (intent.py contract: `'ready'=true רק כש... המשתמש אישר לסגור`). When `phone in _pending_commit`, a `ready=true`/affirmative turn IS the confirm; a changed-detail turn re-resolves anyway. **Leaner:** try reusing `ready` as the confirm signal inside the pending branch before adding a second boolean the model has to learn to set correctly. If live testing shows `ready` is too sticky (model keeps it true across the gate), *then* add `confirm`. Don't pre-add a field to dodge a problem you haven't observed. (Low confidence — this one is worth a quick test, not a blind cut; flag, don't delete.)

4. The OTP sub-design in Open-Q1 is speculative scaffolding for a screen nobody has seen · The plan correctly defers building it, but it still spends a paragraph designing the "detect OTP field → notify Alon → relay code → act it in → extend the per-phone dict" mechanism. That's premature design for an unconfirmed requirement. **Leaner:** keep Open-Q1 to one line — "does the final confirm gate behind OTP? find out in the live test" — and design the relay only if the real screen demands it. Same for Q2 (phone-format normalization): it's already correctly scoped as "one-liner if the live test shows it's needed" — good, leave it as a question, don't pre-write it.

Not over-built (correctly lean, don't touch): the single `dry_run` flag defaulting True; reusing `book_table`'s `dry_run=False` branch instead of new automation; no new table/column (`bookings` + free-text status already exist, verified memory.py:129-146); the stateless re-run at commit (genuinely safer, re-verifies availability); the `_truth_note` wording branch; passing the WhatsApp `phone` straight through. All correct YAGNI calls.

VERDICT
Essential and already lean: the `dry_run` flag, flipping `book_table(dry_run=False)` on the second turn, the `pending`→commit gate, and `log_booking(status="confirmed")` on real success — all reuse existing infra with no new tables, classes, or dependencies. Cut for the minimum that works: (a) delete the standalone `_summary()` and let `book_table`'s existing `notify("סגור ✅…")` be the one confirmation message, adding the conf-number inline there — this also dissolves Open-Q4; (b) shrink `_pending_commit` to just `{url, name}` and read the rest back from the dry-run `res.details` you already computed, instead of a 6-field hand-copied parallel dict; (c) hold off on the `confirm` schema field — try the existing `ready` as the go-signal first, add `confirm` only if a live test shows `ready` misfires across the gate; (d) trim the OTP design in Open-Q1 to a question, not a mini-spec. The two riskiest over-build spots are the duplicated `_summary` (a true reinvention of code that already runs) and the parallel `_pending_commit` shape (re-keying data that already exists in `res.details`) — both are cheap to collapse now and annoying to unwind later.
