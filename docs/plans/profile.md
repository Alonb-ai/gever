# Plan — USER PROFILE expansion (Supabase memory)

## Goal

גבר should remember the durable, reuse-worthy facts a user mentions over time, so he
stops re-asking them. Today he persists `name` + `email` (encrypted) and `prefs` jsonb
(`party_size` / `dietary` / `areas`), and `_profile_block` injects name + those three
prefs into every fresh chat seed.

Expand this so גבר:
- (a) **stores** more facts in the existing `prefs` jsonb — no migration.
- (b) **extracts** them: the Gemini turn returns a small `profile` object whenever the
  user states such a fact, which we save via `upsert_profile`.
- (c) **loads** them: `_profile_block` injects every known fact on every fresh chat seed.
- (d) is verified end-to-end against the live Supabase round-trip.

Facts in scope (all durable, reuse-worthy — the kind worth not re-asking):
`email`, relationship status `זוגיות`, city of residence `עיר מגורים`, favorite
restaurant `מסעדה מועדפת`, dietary `מגבלות אוכל`, default party size `כמות סועדים`,
preferred areas `אזורים מועדפים`.

**Do not over-capture.** Only stable facts the user actually *stated about himself*.
No mood, no one-off booking details (those already live in `bookings`), no guesses.

## Design and interfaces

### Storage — reuse `prefs` jsonb, no migration

The `users.prefs` column is already `jsonb not null default '{}'`. We add keys to it;
the schema does not change. `name` stays its own encrypted column. `email` is interesting:
it is **already its own encrypted column** in `users` and `upsert_profile` already handles
it — so `email` keeps living there (encrypted), NOT in `prefs`. Everything else goes into
`prefs` as plain keys.

Final `prefs` shape (all keys optional; absent = unknown):

```jsonc
{
  "party_size": 4,                 // existing — default party size (int)
  "dietary": "צמחוני",             // existing — dietary limits (free text)
  "areas": "צפון תל אביב",         // existing — preferred areas (free text)
  "relationship": "בזוגיות",       // new — relationship status (free text)
  "city": "תל אביב",               // new — city of residence (free text)
  "fav_restaurant": "טייזו"        // new — favorite restaurant (free text)
}
```

Free text (not enums) on purpose: the user phrases these however he likes, and גבר only
needs them as context to echo back — not to parse. `party_size` stays an int (it already is,
and the booking path reads it as a number).

### `memory.upsert_profile` — merge prefs instead of overwriting

This is the one real code change in the memory layer, and it is required for correctness.

Today `upsert_profile(prefs=...)` sets `payload["prefs"] = prefs` and relies on PostgREST
`resolution=merge-duplicates`. That merge is **row-level**: it replaces the whole `prefs`
column with the new object. So if a turn sends `{"city": "תל אביב"}`, it would wipe a
previously-stored `party_size`. We must merge at the **key** level.

Minimal fix: `upsert_profile` reads the current row, shallow-merges the new prefs keys into
the existing prefs, and writes the merged object back. Concretely, when `prefs` is given:

```python
if prefs is not None:
    existing = await get_profile(phone)          # already exists, decrypts name/email
    merged = {**((existing or {}).get("prefs") or {}), **prefs}
    payload["prefs"] = merged
```

This keeps the single-call interface (one `upsert_profile` per turn) and stays ponytail —
no new function, no new table. The extra `get_profile` read is one cheap indexed lookup on
the same phone; acceptable given turns are conversational, not high-QPS. (Note: not
atomic — last writer wins on concurrent turns for the same phone. For a single user texting
one WhatsApp thread this cannot happen in practice; flagged in open questions only for
honesty, not as a blocker.)

`None` values inside `prefs` should be dropped before merging so the model can't null out a
known fact by accident — we only ever *add/replace* keys it actually filled.

### Extraction — extend `_SCHEMA` + `_EXTRACT`

Add one optional `profile` object to the JSON contract. The model fills it **only** when the
user states a durable fact this turn; otherwise it omits it (or sends `{}`).

`_SCHEMA` gains:

```python
"profile": {
    "type": "object",
    "properties": {
        "email":          {"type": "string"},
        "relationship":   {"type": "string"},
        "city":           {"type": "string"},
        "fav_restaurant": {"type": "string"},
        "dietary":        {"type": "string"},
        "party_size":     {"type": "integer"},
        "areas":          {"type": "string"},
    },
},
```

`required` stays `["reply", "ready"]` — `profile` is optional. `name`/`email` stay as
top-level fields too (the booking path already reads `fields["name"]`/`fields["email"]`),
so `email` is accepted in *either* place; we normalize on the way to storage.

`_EXTRACT` gains a short Hebrew instruction, in the existing "internal mechanism" voice:

> אם המשתמש מסר עובדה קבועה על עצמו שכדאי לזכור — מייל, מצב זוגי, עיר מגורים, מסעדה
> מועדפת, מגבלות אוכל, כמות סועדים שהוא בדרך כלל מזמין, או אזורים שהוא אוהב — מלא אותה
> תחת 'profile' (רק את מה שנאמר במפורש, אל תנחש ואל תכתוב מצב רגעי). אם לא נמסרה עובדה
> כזו השאר 'profile' ריק.

Naming the exact keys + "explicitly stated, don't guess" is what keeps it from
over-capturing. Gemini already reliably fills the existing `restaurant`/`name`/`email`
fields under the same contract, so this is the same mechanism, one object wider.

### Persisting the extracted profile — new tiny hook in the pipeline

Today the only `upsert_profile` call is inside `run_booking`, and it only fires after a
booking reaches the `pending` gate (saving name/email). That misses every conversational
fact mentioned outside a booking. We add a save on **every turn** that returns profile facts.

In `converse` (or right after it in `handle_inbound`), after we have `result`:

```python
prof = result.get("profile") or {}
# email can arrive top-level too; fold it in
if result.get("email"):
    prof.setdefault("email", result["email"])
name = result.get("name") or None
email = prof.pop("email", None)          # email → its own encrypted column
prof = {k: v for k, v in prof.items() if v not in (None, "", 0)}
if name or email or prof:
    await memory.upsert_profile(phone, name=name, email=email or None,
                                prefs=prof or None)
```

Placed in `handle_inbound` after `converse` returns and before/after `send_text` (order
doesn't matter; saving is fire-and-forget-safe since `upsert_profile` never raises). This is
~6 lines and reuses the existing function. The existing `run_booking` name/email save stays
as-is (harmless redundancy — same merge), so the booking path is untouched.

Guard against the empty-prefs overwrite: only pass `prefs=` when `prof` is non-empty
(otherwise `None`, which `upsert_profile` skips entirely).

### Loading — expand `_profile_block`

Append the new keys to the injected block, same pattern as today. The block already says
"you know him, don't re-ask name/email". Add `email`, relationship, city, favorite restaurant:

```python
if profile.get("email"):
    lines.append(f"מייל: {profile['email']}")
if prefs.get("relationship"):
    lines.append(f"מצב זוגי: {prefs['relationship']}")
if prefs.get("city"):
    lines.append(f"עיר מגורים: {prefs['city']}")
if prefs.get("fav_restaurant"):
    lines.append(f"מסעדה מועדפת: {prefs['fav_restaurant']}")
```

(`email` reads from the decrypted top-level column, not `prefs`.) The header line already
tells גבר not to re-ask — these just give him more not to re-ask. Every key is guarded, so
an empty profile still yields `""` exactly as today.

## How it fits the existing code

- **`prefs` jsonb** was designed for exactly this — the schema comment already reads
  `{party_size, dietary, areas} — defaults גבר reuses`. We extend that set. No migration,
  no new column, no new table. (ponytail satisfied.)
- **`_seed_instruction` → `_profile_block` / `_EXTRACT` / `_SCHEMA`** is the existing seam
  for "inject what we know" and "ask the model to fill what's new". We widen all three by a
  few lines; no structural change. The seed is built once per fresh chat (first contact /
  3h gap / post-booking reset), so newly-learned facts surface on the *next* fresh session —
  consistent with how name/email already behave today.
- **`upsert_profile`** already accepts `prefs`; the only change is making its prefs merge
  key-level instead of column-level. That is a latent bug the moment anyone writes prefs
  from two different turns, so fixing it now is correct regardless.
- **Encryption boundary unchanged:** only `name`/`email` are Fernet-encrypted (PII). The new
  prefs (city, relationship, fav restaurant, dietary, areas, party_size) are low-sensitivity
  preference data and stay plaintext in `prefs`, matching how `dietary`/`areas` already work.
  If Alon wants city/relationship encrypted too, that's a deliberate change (see open
  questions) — default plan keeps them plaintext for simplicity and so `_profile_block` can
  read them directly without per-key decrypt.
- **Memory GATING preserved:** with no Supabase keys, `get_profile` returns `None`,
  `upsert_profile` is a no-op, the new save hook does nothing, and `_profile_block` returns
  `""`. Behavior with keys absent is byte-identical to today.

## Files and changes (minimal)

1. **`app/db/memory.py`** — `upsert_profile`: key-level merge of `prefs` (read existing,
   shallow-merge, write back; drop `None` values). ~4 lines. No other function changes.
2. **`app/pipeline.py`**
   - `_SCHEMA`: add optional `profile` object (7 keys). 
   - `_EXTRACT`: add the one-sentence Hebrew "fill durable facts under profile" instruction.
   - `_profile_block`: add `email` + `relationship` + `city` + `fav_restaurant` lines (each
     guarded). 
   - `handle_inbound` (or `converse`): add the ~6-line save hook that persists
     `result["profile"]` (+ top-level email) via `upsert_profile`.
3. **`app/db/schema.sql`** — comment-only: update the `prefs` comment to list the new keys.
   No DDL change (column already `jsonb`). Optional but keeps the schema self-documenting.

No new files, no new dependencies, no new tables/columns.

## Open questions / info needed from Alon

1. **Encrypt city/relationship?** Default plan stores them plaintext in `prefs` (like
   dietary/areas today). City + relationship status are mildly personal — want them
   Fernet-encrypted instead? That costs a per-key decrypt in `_profile_block` and a bit
   more code. My default: plaintext (simplest, low sensitivity). Confirm or override.
2. **When does a freshly-learned fact take effect?** With the current seed design it surfaces
   on the *next* fresh chat (new contact / 3h gap / post-booking), because the seed is built
   once per session — same as name/email today. Good enough? Or do you want known facts also
   re-injected mid-session (would need a per-turn inject, more invasive)? My default: next
   fresh session, matching today.
3. **Trust the model on `party_size` as a "default"?** A user saying "we're 4 tonight" is a
   booking detail, not a standing default. The prompt says "כמות סועדים שהוא בדרך כלל מזמין"
   to bias toward standing defaults, but the line is fuzzy. Fine to let it occasionally
   capture, since the booking flow still confirms party size each time? My default: yes,
   accept it as a soft default; booking confirmation is the safety net.
4. **Anything to NOT capture that you'd expect the list above to include?** (e.g. phone is
   already the key, gender is handled separately via `gender_line`.) Confirm the 7-fact set
   is the intended scope.

## Build steps (ordered)

1. **`memory.upsert_profile` key-level merge.** Read existing prefs, shallow-merge, drop
   `None`s, write back. This is the correctness foundation — do it first so no later write
   can clobber prior prefs.
2. **`_SCHEMA` + `_EXTRACT`.** Add the optional `profile` object and the Hebrew extraction
   instruction. Keep `required` = `["reply","ready"]`.
3. **Save hook in `handle_inbound`.** After `converse`, fold top-level `email` into
   `profile`, split `name`/`email` out to their columns, strip empties, and
   `upsert_profile(...)` only when there is something to save.
4. **Expand `_profile_block`.** Add the guarded lines for email / relationship / city /
   favorite restaurant.
5. **Update `schema.sql` comment** to list the new prefs keys (doc only).
6. **Verify the live Supabase round-trip.** With real Supabase keys + `ENCRYPTION_KEY` set:
   - Send a message stating facts, e.g. `אני גר בתל אביב בזוגיות והמסעדה האהובה עליי טייזו`.
     Confirm the turn's JSON carries a `profile` object with `city` / `relationship` /
     `fav_restaurant`.
   - Query the `users` row (Supabase SQL editor or PostgREST) and confirm `prefs` now holds
     those keys, and that a *second* message stating a different fact (e.g. `אני צמחוני`)
     **adds** `dietary` without dropping the earlier keys (proves key-level merge).
   - Open a fresh session (or wait past the 3h gap / trigger a post-booking reset) and confirm
     `_profile_block` now injects all known facts (inspect the seed instruction, or observe
     גבר not re-asking and referencing the favorite restaurant naturally).
   - Toggle Supabase keys off and confirm the whole path is a clean no-op (no errors, behaves
     exactly like today).

   Practical harness: a tiny async REPL/script that calls
   `memory.upsert_profile(phone, prefs={...})` then `memory.get_profile(phone)` and prints
   the round-tripped `prefs` is the fastest way to prove the merge before wiring the LLM —
   reuse the gating/encryption already in `memory.py`.


---

## Ponytail review (over-engineering)

## FINDINGS (prioritized — biggest cut first)

**1. The `get_profile`-then-merge read in `upsert_profile` is over-built. Push the key-merge to Postgres instead.** · The plan adds an extra `get_profile` round-trip (network + Fernet-decrypt of name/email) on *every* turn that learns a fact, just to shallow-merge prefs in Python, and then admits in its own text that it's "not atomic — last writer wins." That's reinventing key-level jsonb merge that Postgres does natively and atomically. · Leaner: keep the single write, drop the read. Use a Postgres jsonb concat via an RPC or `prefs = prefs || :new` — or simplest of all, since the repo already does PostgREST writes, store the new keys with a `merge` resolution at the column granularity by issuing a `PATCH` with `prefs=prefs||'{...}'::jsonb` isn't expressible in pure PostgREST, so the genuinely lazy move is a tiny `supabase` SQL function `merge_prefs(phone, patch jsonb)` called once. One DB call, atomic, no decrypt. If Alon wants zero SQL, the Python read-merge is acceptable *only* because QPS is ~1/user — but then the plan should say "we accept a stale-read race and it's fine," not add atomicity caveats as if they were being handled. Pick one; don't pay for a read AND carry the race.

**2. The `name`/`email` dual-path normalization is speculative complexity born from the plan itself.** · The plan keeps `name`/`email` as top-level schema fields *and* adds them inside the new `profile` object, then writes ~4 lines to "fold top-level email in" (`prof.setdefault`, `prof.pop`, `setdefault`). That branching exists only because the plan chose to duplicate `email` in two schema locations. · Leaner: do NOT add `email` to the `profile` object at all. It already has a top-level field that `run_booking` reads. Let `profile` carry only the genuinely new plaintext keys (`relationship`, `city`, `fav_restaurant`, and the existing `dietary`/`areas`/`party_size`). Then the save hook has no fold/pop/setdefault dance — `email` and `name` come from `result["email"]`/`result["name"]` exactly as `run_booking` already reads them. Removing one schema key deletes the entire normalization paragraph.

**3. Putting `dietary`/`areas`/`party_size` back into the new `profile` object is redundant.** · These three are already captured and stored today (the plan says so). Re-declaring them inside `profile` means two places the model could emit the same fact, and more keys to strip/merge. · Leaner: scope `profile` to the *three new* facts only (`relationship`, `city`, `fav_restaurant`). The existing three keep flowing through whatever path already populates `prefs` today. Smaller schema, smaller prompt, no double-capture ambiguity. (If today nothing actually writes those three from conversation — worth a 30-second check — then add them, but then they're not "existing," and the plan's "same mechanism" framing is wrong.)

**4. `None`-stripping logic appears twice (in `upsert_profile` and in the save hook).** · The plan strips empties in the hook (`v not in (None, "", 0)`) *and* says `upsert_profile` should drop `None`s before merging. One of these is dead. · Leaner: strip once, in the hook, right before the call. `upsert_profile` stays dumb: it merges whatever dict it's handed. Note `0` is being filtered — that's correct for `party_size` (0 diners is nonsense) but make sure no future int key legitimately wants 0.

**5. Open-question #1 (encrypt city/relationship?) is a non-question — it's premature.** · `dietary`/`areas` are plaintext today and nobody flagged it; city/relationship are the same sensitivity class. Raising it invites scope creep (per-key decrypt in `_profile_block`). · Leaner: drop the question, default to plaintext to match the existing column, move on. One less decision to stall on.

## VERDICT

This plan is already 85% ponytail — it makes the right top-level calls (no migration, no new table/column, no state machine, reuses `prefs` jsonb + `upsert_profile` + the one Gemini JSON contract + `_profile_block`), and that's the hard part. **Essential and keep:** the three new plaintext `prefs` keys, the few guarded lines in `_profile_block`, the short Hebrew `_EXTRACT` instruction, and a save hook in `handle_inbound`. **Cut to reach minimum:** (a) the duplicate `email` field in the new `profile` object and the entire fold/pop/setdefault normalization it forces (finding #2) — this is the single biggest needless-complexity source and it's self-inflicted; (b) re-declaring the three existing prefs keys inside `profile` (#3); (c) the duplicated None-stripping (#4); (d) the encryption open-question (#5). **The one riskiest over-build** is finding #1: the read-modify-write merge in `upsert_profile` — it adds a network read + decrypt per turn *and* still carries a last-writer-wins race the plan hand-waves. Either do an atomic Postgres-side jsonb merge (correct and one call) or own the race explicitly and skip the read; doing both — paying for the read yet still racing — is the worst of both. For a single-user WhatsApp thread the Python read-merge genuinely won't bite, so the lazy-but-honest answer is: keep the Python merge, delete the atomicity caveats, ship it.
