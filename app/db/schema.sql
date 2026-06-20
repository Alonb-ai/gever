-- gever — cross-conversation memory schema (Supabase / Postgres).
-- Run once in the Supabase SQL editor. name + email live encrypted at rest
-- (Fernet, ENCRYPTION_KEY) — the DB only ever sees ciphertext for those columns.

-- users: one row per WhatsApp number. phone is the natural primary key (text).
create table if not exists users (
    phone       text primary key,           -- WhatsApp number, e.g. "972501234567"
    name        text,                        -- Fernet-encrypted at rest
    email       text,                        -- Fernet-encrypted at rest
    prefs       jsonb not null default '{}', -- {party_size, dietary, areas, _chat} — defaults+תמלול גבר reuses
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- bookings: append-only history of what גבר closed for the user.
-- recent rows feed the light recap injected at the start of a fresh chat.
create table if not exists bookings (
    id          bigint generated always as identity primary key,
    phone       text not null references users(phone),
    restaurant  text not null,
    date        text,                        -- booking date as captured (free text / ISO)
    time        text,                        -- booking time as captured
    party_size  integer,
    status      text not null,               -- e.g. "confirmed", "pending", "failed"
    created_at  timestamptz not null default now()
);

-- recent_bookings(phone) is ordered by created_at desc — index keeps it cheap.
create index if not exists bookings_phone_created_idx
    on bookings (phone, created_at desc);
