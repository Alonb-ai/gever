# Conversation Memory — plan

> Alon: "גבר לא זוכר הודעה אחורה / על מה דיברנו." This plan diagnoses *why*, gives
> the 1-line interim fix, then the minimal robust persistence upgrade.

---

## Goal

גבר must remember the conversation **within a session** — at minimum the last
message and the thread of the current booking — so a follow-up like "כן" / "8
אנשים" / "תזמין" lands in context instead of starting from zero. Context must
survive: a container restart/redeploy, more than one uvicorn worker (if we ever
add them), and the 3h session gap if it's firing too early. The fix must hold the
existing behavior intact when Supabase is off (the no-keys path stays a no-op).

---

## Diagnosis (the real cause — read this before designing)

I read `pipeline.py`, `main.py`, `Dockerfile`, `config.py`, `db/memory.py`,
`db/schema.sql`. The "doesn't remember" symptom has **three independent causes**,
ranked by how likely they are to be what Alon is hitting:

1. **In-memory state lost on every restart/redeploy (the dominant cause).**
   `_chats`, `_last_seen`, `_reset_next`, `_booking` are all module-level dicts
   (`pipeline.py:53-62`). `_chats[phone]` holds a **live Gemini `Chat` object**
   whose history lives only in that process's RAM. Every Coolify redeploy, crash,
   or OOM wipes all of it → the very next user message opens a fresh chat with no
   history. Since the project is actively deploying (Stage 1→2, swapping tokens,
   moving to Coolify), restarts are frequent right now. **This alone fully
   explains "doesn't remember what we talked about."**

2. **Multiple workers — NOT the active cause, but a latent landmine.** The
   `Dockerfile` CMD is `uvicorn app.main:app --host 0.0.0.0 --port 8000` with
   **no `--workers` flag → uvicorn runs a single worker.** So today every message
   for a phone hits the same process and shares one `_chats`. *However:* the
   moment anyone adds `--workers N` (or a `gunicorn -w N` for throughput) each
   worker gets its **own** `_chats`, and consecutive WhatsApp messages — which
   Meta delivers as independent POSTs with no sticky routing — scatter across
   workers. A "כן" then lands on a worker that never saw the question. This is the
   classic per-worker-dict bug; it's just not armed yet. The persistence upgrade
   below disarms it permanently.

3. **`SESSION_GAP_S = 3h` + the just-fixed `_reset_next` bug.** `_chat_for`
   (`pipeline.py:116-139`) opens a "fresh page" when `now - last_seen > 3h` or
   when the phone is in `_reset_next`. 3h is a *deliberate* "new day" reset, not a
   bug — but note it only ever fires when `_last_seen` survived (same process), so
   in practice cause #1 masks it. The `_reset_next` bug (already fixed) was making
   chats reset one turn too eagerly. With persistence in place, the gap logic
   should be re-evaluated against a **persisted** `last_seen` (see Open questions).

**Conclusion:** the headline cause is **#1 (ephemeral in-process memory)**, not
multiple workers. There is no 1-line "just fix workers" answer here because
workers aren't the problem yet. The honest 1-line interim is: pin single worker
*and* don't redeploy mid-conversation — but that only papers over restarts. The
real fix is to **persist the conversation to Supabase per phone and rebuild the
Gemini chat from it each turn.** That one change fixes #1, pre-empts #2, and makes
#3 well-defined.

---

## Design and interfaces

### The shape of the fix

Stop treating the live `Chat` object as the source of truth. Make Supabase the
source of truth for conversation turns, and rebuild a *stateless-per-request*
Gemini chat from stored history on every inbound message:

```
inbound → load history(phone) from Supabase
        → chats.create(model, config, history=<stored turns>)   # replay
        → send_message(text) → reply
        → append (user turn, model turn) back to Supabase
```

The Gemini SDK supports exactly this: `chats.create(..., history=[...])` takes a
`list[types.Content]` (verified against the installed `google-genai`:
`Chats.create(*, model, config=None, history=None)`; `Content` = `{role, parts}`).
So we don't need to keep the chat alive between requests at all — we reconstruct
it each turn from the transcript. That kills the process-bound state.

### What to store: rolling transcript, capped (not a summary — yet)

Store the **raw turn list**, capped to the last **N turns** (proposal: N=20, i.e.
~10 exchanges). This is the minimal robust choice:

- **Full history** = perfect fidelity, but unbounded token growth → latency + cost
  creep on long threads, and Gemini context ceiling eventually. Rejected as the
  default.
- **Rolling summary** (LLM-compress old turns into a paragraph) = cheapest tokens
  long-term, but adds a second LLM call per turn (latency + cost + a place to get
  the persona wrong) and loses verbatim detail mid-booking. **Over-engineered for
  a WhatsApp booking thread**, which is naturally short. Rejected for v1.
- **Capped rolling window (chosen)** = keep last N turns verbatim, drop the oldest.
  A booking conversation almost never exceeds a handful of turns before it closes
  or resets, so N=20 means "effectively never truncates in practice" while still
  bounding the worst case. Zero extra LLM calls. This is the ponytail answer.

We already inject a **profile block + recent-bookings recap** into the system
instruction (`_seed_instruction`), so long-term cross-session memory is *already*
handled separately. The transcript only needs to cover the **live session**, which
makes the cap a non-issue. (Summary path stays documented as the upgrade if real
threads ever get long — see Build steps, optional.)

### Storage: reuse the `users` row, no new table

`users.prefs` is `jsonb` and the brief explicitly says "add keys with NO
migration." We store the live transcript on the user's own row. **No new table,
no schema change, no migration.** Two options inside the row:

- **(A) a dedicated `chat` jsonb column** — cleaner, but needs `alter table`.
- **(B) under `prefs`, e.g. `prefs["_chat"] = {"turns": [...], "last_seen": <ts>}`**
  — zero migration, fits the "prefs is flexible" rule exactly.

**Choose (B)** for the ponytail minimum: it ships with no SQL run against the live
DB. The transcript is conversational text (restaurant names, dates) — same
sensitivity tier as the booking rows we already store in cleartext, so we do **not**
Fernet it (we only encrypt name/email, per the established rule). If Alon wants it
encrypted or in its own column later, that's a one-line swap of the read/write
helpers.

> ponytail note: storing transcript inside `prefs` slightly overloads a column
> meant for preferences. Acceptable for v1 (no migration, ships today). If it
> bothers us, promote to a `chat` column or `conversations` table later —
> tracked, not done now.

### New memory helpers (in `db/memory.py`, mirroring the existing ones)

```python
async def get_chat(phone: str) -> dict | None
    # returns {"turns": [{"role","text"}...], "last_seen": float} or None.
    # no-op-safe: returns None when memory disabled / on any failure.

async def save_chat(phone: str, turns: list[dict], last_seen: float) -> None
    # writes prefs._chat via the SAME merge-duplicates upsert path.
    # READ-MODIFY-WRITE hazard: upsert_profile replaces the whole prefs blob.
    # So save_chat must merge into existing prefs (fetch-or-cache prefs, set
    # _chat, write back) — see Open questions on the merge approach.
```

Turns are stored as a compact `[{"role": "user"|"model", "text": "..."}]` list,
**not** raw `types.Content`, so the JSON is small and SDK-version-independent. We
rehydrate to `types.Content` only at chat-build time.

### Pipeline changes (`pipeline.py`)

`_chat_for(phone)` becomes: load stored `{turns, last_seen}` from Supabase →
apply the same fresh-page logic (gap / first-contact / reset) against the
**persisted** `last_seen` → build `chats.create(..., history=rehydrate(turns))`.
We no longer cache the live `Chat` in `_chats` across requests (it's rebuilt each
turn), so `_chats` can go away or shrink to a per-request local.

`converse(phone, text)`: after `send_message`, append the user turn and the model
turn (the persona `reply` text, not the raw JSON — we replay what גבר *said*) to
the turn list and `save_chat(...)`. The `_truth_note` prefix stays a per-request
injection and is **not** persisted (it's system ground-truth, not conversation).

`_booking`, `_reset_next`: `_booking` is short-lived ground-truth for an
in-flight booking; persisting it is out of scope for "remember the conversation"
and would need its own state machine — **leave in memory for v1** (documented
limitation: a restart mid-booking still loses the booking's working/pending
state, but the *conversation* survives, which is what Alon reported). `_reset_next`
becomes a persisted flag inside `_chat` (`{"reset_next": true}`) so a post-booking
reset survives a restart too — cheap, same write.

---

## How it fits the existing code

- **Same Supabase REST + gating pattern.** `get_chat`/`save_chat` live next to
  `get_profile`/`upsert_profile` in `db/memory.py`, use the same `_enabled()`
  gate, the same `httpx.AsyncClient`, the same swallow-and-log error handling. When
  keys are absent, `get_chat` returns `None` and the pipeline behaves **exactly as
  today** (in-memory only) — no regression on the no-keys/dev path.
- **No new table, no migration.** Lives in `users.prefs` jsonb. `schema.sql`
  unchanged.
- **Reuses the verified SDK history API** — `chats.create(history=...)` — so the
  persona, JSON schema, temperature, and `_EXTRACT`/`_seed_instruction` injection
  all stay identical; only the chat's starting history changes.
- **Profile + recap injection untouched.** Long-term memory already works; this
  adds the *short-term* session transcript that was missing.
- **Single-worker today stays correct**, and the design is **worker-count
  agnostic** going forward because state is external.

---

## Files and changes (minimal)

| File | Change |
|---|---|
| `app/db/memory.py` | **Add** `get_chat(phone)` and `save_chat(phone, turns, last_seen, reset_next=...)`. `save_chat` must read-modify-write `prefs` so it doesn't clobber other prefs keys. ~40 lines, mirrors existing helpers. |
| `app/pipeline.py` | `_chat_for`: load persisted `{turns,last_seen,reset_next}`, apply fresh-page logic on persisted `last_seen`, build chat via `history=`. `converse`: append both turns + `save_chat` after each reply. Add a `_rehydrate(turns) -> list[types.Content]` helper. Drop the cross-request `_chats` cache (becomes per-request). Persist `_reset_next` into `_chat`. |
| `Dockerfile` | **No change needed today** (already single-worker). Optional hardening: leave the comment but do NOT add `--workers`; if throughput later forces multiple workers, persistence already covers it. |
| `schema.sql` | **No change** (uses existing `prefs` jsonb). |

That's **two files**. No SQL, no new dependency, no new table.

---

## Open questions / info needed from Alon

1. **Is the 3h `SESSION_GAP_S` the felt problem, or just restarts?** If Alon is
   hitting "doesn't remember" within minutes, it's restarts (#1) and the gap is
   fine. If he means "I came back after lunch and it forgot," that's the gap doing
   its job — do we want to **raise it** (e.g. 12–24h) now that history is cheap to
   keep, or keep the "fresh page" reset? My default: keep 3h, since profile+recap
   still carry the important facts across the gap.
2. **Persist the transcript verbatim, or skip the `_truth_note`/system lines?**
   Plan persists **only** user text + the persona reply (clean transcript). Confirm
   that's the intent (vs. also persisting the booking ground-truth, which I'm
   deliberately leaving in-memory).
3. **`prefs._chat` vs. a dedicated `chat` column.** I chose `prefs._chat` for
   zero-migration. If Alon prefers a clean `chat jsonb` column, that's one
   `alter table` + a 2-line change to the helpers. Your call on cleanliness vs.
   "no SQL on live DB."
4. **Cap N=20 turns OK?** Bigger = more context but more tokens/latency per turn.
   Booking threads are short, so 20 is generous. Confirm or pick a number.
5. **Concurrency on `save_chat`'s read-modify-write of `prefs`.** Two near-simultaneous
   messages from the same phone could race (last-write-wins, one turn lost).
   Acceptable for a single human texting? (Yes, realistically.) If we ever worry,
   a Postgres `jsonb` merge via an RPC removes the race — out of scope for v1.

---

## Build steps (ordered)

1. **Confirm the diagnosis with Alon in one line:** the cause is ephemeral
   in-process memory wiped on redeploy/restart, **not** multiple workers (we're
   single-worker today). No emergency 1-liner needed beyond "don't redeploy
   mid-chat"; the persistence change is the real fix. Get answers to Open
   questions 1, 3, 4.
2. **`db/memory.py` — add `get_chat`:** PostgREST GET on `users` selecting
   `prefs`, return `prefs.get("_chat")`; no-op/`None` when disabled or on failure
   (copy the `get_profile` error pattern exactly).
3. **`db/memory.py` — add `save_chat`:** fetch current `prefs` (or accept it from
   the caller to avoid a second round-trip), set `prefs["_chat"] = {"turns",
   "last_seen", "reset_next"}`, upsert via the existing merge-duplicates path so
   other prefs keys survive.
4. **`pipeline.py` — `_rehydrate(turns)`:** map `[{role,text}]` →
   `[types.Content(role=..., parts=[types.Part(text=...)])]`.
5. **`pipeline.py` — rewrite `_chat_for`:** load `{turns,last_seen,reset_next}`;
   compute `fresh` from persisted `last_seen`/`reset_next`/first-contact; on fresh,
   start empty history (and clear `reset_next`); else build chat with
   `history=_rehydrate(turns)`. Keep `_seed_instruction` injection unchanged.
6. **`pipeline.py` — `converse`:** after the reply, append the user turn and the
   model's `reply` turn, truncate to last N=20, call `save_chat`. Persist
   `last_seen=now`. Keep `_truth_note` as a non-persisted per-request prefix.
7. **Post-booking reset:** where `_reset_next.add(phone)` happens, instead set
   `reset_next` in the persisted `_chat` (so the next-turn fresh page survives a
   restart). Keep the in-memory set as a same-process fast path if convenient.
8. **Manual verify (no keys):** with Supabase off, confirm pipeline behaves
   exactly as today (history in-process only, no crash). With keys on: send "תזמין
   ב-Taizu מחר ל-2", then a follow-up "כן" — confirm it remembers; then **restart
   the container** and send another follow-up — confirm it *still* remembers. This
   restart-survival test is the acceptance criterion for Alon's bug.
9. **(Optional, deferred — do NOT build now) Summary upgrade path:** if real
   threads ever exceed the cap meaningfully, add an LLM rollup of dropped turns
   into `prefs._chat["summary"]`, injected into `_seed_instruction`. One extra LLM
   call per overflow. Documented here so the path is known; YAGNI until threads
   actually get long.


---

## Ponytail review (over-engineering)

The plan matches the code I read. Now I have what I need to judge it against the real codebase.

A few things I verified that sharpen the findings:
- `_chats`, `_last_seen`, `_reset_next`, `_booking` are indeed plain module dicts (pipeline.py:53-62) — confirmed.
- `upsert_profile` already does merge-duplicates upsert and accepts a `prefs` dict (memory.py:100-126) — the plan's `save_chat` mostly reinvents it.
- The chat object is rebuilt fresh on every `fresh` branch already; the cross-request cache is the only thing that survives.

Here is my ponytail review.

---

## PRIORITIZED FINDINGS

**1. `save_chat` reinvents `upsert_profile` (cut the new write helper).**
The plan adds `save_chat(phone, turns, last_seen, reset_next)` with its own read-modify-write of `prefs`. But `upsert_profile` (memory.py:100) *already* takes `prefs: dict` and *already* does the merge-duplicates upsert. The only real work is "merge `_chat` into existing prefs without clobbering sibling keys." That is one read (you already have the profile in hand — `_seed_instruction` fetches it via `get_profile` every turn) plus `upsert_profile(phone, prefs={**prefs, "_chat": {...}})`. **Leaner:** no `save_chat`. The pipeline already holds the profile dict each turn; just write `prefs` back through the existing `upsert_profile`. Saves a whole helper and the documented read-modify-write hazard.

**2. `get_chat` reinvents `get_profile` (cut the new read helper).**
`get_profile` already does the PostgREST GET on `users` with `select=*` and returns the full row including `prefs`. `_seed_instruction` calls it every turn anyway. A separate `get_chat` is a second round-trip for data you already fetched. **Leaner:** read `profile["prefs"].get("_chat")` from the profile you already loaded. Zero new read function, zero extra HTTP call per turn.

**3. Persisting `_reset_next` into `_chat` is speculative — cut it.**
The plan persists `reset_next` "so a post-booking reset survives a restart." Think about what's actually lost: a restart between "booking closed" and "user's next message" means the next chat replays one extra closed-booking turn. The user says something new; גבר re-seeds from profile+recap anyway on the next gap. This is solving a sub-second race across a redeploy that the 3h gap and fresh profile injection already absorb. **Leaner:** drop persisted `reset_next` entirely. Keep the in-memory set as-is. If it ever matters, the staleness is self-healing on the next message.

**4. `last_seen` persistence + re-deriving the gap is more than the bug needs.**
The reported bug is "forgot what we talked about after a redeploy." That's solved purely by replaying `turns`. Persisting `last_seen` to re-evaluate the 3h gap against a stored timestamp is a *separate* feature (Open Question #1 admits Alon may not even have this problem). **Leaner for v1:** persist only `turns`. On load, if turns exist, replay them; the gap reset stays in-memory (`_last_seen`) exactly as today. After a restart, worst case is the gap doesn't fire and history replays — which is the desired behavior for the bug being fixed. Add persisted `last_seen` only if Alon confirms the "came back after lunch" complaint in OQ#1. Don't build both branches speculatively.

**5. `_rehydrate` helper for a 2-line map is borderline.**
`[{role,text}] → [types.Content(role=r, parts=[types.Part(text=t)])]` is a one-line comprehension inline in `_chat_for`. A named helper is fine if reused, but it's only called once. **Leaner:** inline the comprehension; name it later if a second caller appears. Minor.

**6. N=20 cap + truncation logic — keep, but it's near-dead code.**
The plan itself says booking threads "almost never exceed a handful of turns." A cap that, by the plan's own argument, "effectively never truncates in practice" is carrying a slice operation for a case that won't fire. It's one line (`turns[-20:]`), so keep it as cheap insurance — but don't dress it up as a design decision with three rejected alternatives. The summary-upgrade path (step 9) is correctly deferred; good.

---

## VERDICT

The plan's *diagnosis* is excellent and the core fix is genuinely lean: rebuild the Gemini chat each turn from a transcript stored in `users.prefs._chat`, no new table, no migration, no new dependency, no summary LLM. That spine is the right ponytail answer and should ship. **What to cut:** the two new memory helpers (`get_chat`/`save_chat`) largely reinvent `get_profile`/`upsert_profile`, which already fetch the row and already do a merge-duplicates `prefs` upsert — the pipeline holds the profile dict every turn, so read `prefs["_chat"]` off it and write it back through `upsert_profile(prefs=...)` with no new functions and no read-modify-write hazard to document. **Also cut from v1:** persisting `reset_next` (self-healing staleness, sub-second redeploy race) and persisting `last_seen` to re-derive the 3h gap (a separate feature Alon may not even need — gate it behind his answer to Open Question #1). The minimum that fixes the actual reported bug is: store `prefs._chat = {"turns": [...]}` capped at the tail, replay it via `chats.create(history=...)`, keep `_booking`/`_reset_next`/`_last_seen` in memory exactly as today. **Riskiest over-build spots to watch:** (1) the standalone `save_chat` with its own prefs read-modify-write — that's a second, parallel write path into `users` that can drift from `upsert_profile`'s encryption/merge behavior; fold it into the existing function instead. (2) Building both the `last_seen`-persistence and `reset_next`-persistence branches before Alon confirms either symptom — that's two speculative state-survival mechanisms bolted onto a bug that only requires turn replay.
