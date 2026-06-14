-- סכמת Supabase לגבר (שלב 1)
-- הרצה: Supabase Studio → SQL Editor, או psql.
-- הערה: פרטי PII (ת"ז, טלפון, אמצעי תשלום) נשמרים מוצפנים בצד האפליקציה
-- (Fernet, ENCRYPTION_KEY) — לא טקסט גלוי. לעולם לא לאחסן כרטיס אשראי גולמי.

create table if not exists users (
    id           uuid primary key default gen_random_uuid(),
    wa_phone     text unique not null,          -- מזהה המשתמש ב-WhatsApp
    display_name text,
    -- שדות מוצפנים (bytea / text base64 מה-Fernet):
    id_number_enc  text,
    address_enc    text,
    preferences    jsonb default '{}'::jsonb,    -- דיאטה, מיקומים מועדפים
    plan         text default 'trial',           -- trial | basic | pro
    created_at   timestamptz default now()
);

create table if not exists sessions (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id) on delete cascade,
    state        jsonb default '{}'::jsonb,       -- הקשר שיחה פעיל (intent + שדות חסרים)
    last_inbound timestamptz,                     -- לחישוב חלון 24 השעות
    updated_at   timestamptz default now()
);

create table if not exists actions (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid references users(id) on delete cascade,
    action_type  text not null,                  -- restaurant | insurance | tickets
    status       text not null default 'pending',-- pending | success | failed
    details      jsonb default '{}'::jsonb,
    created_at   timestamptz default now()
);

create index if not exists idx_sessions_user on sessions(user_id);
create index if not exists idx_actions_user  on actions(user_id);
