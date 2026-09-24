-- Production authentication support. Run after 011_storage_security_and_analytics.sql.

create table if not exists public.auth_sessions (
  id uuid primary key default gen_random_uuid(),
  user_profile_id uuid not null references public.user_profiles(id) on delete cascade,
  access_token_hash text not null unique,
  refresh_token_hash text,
  ip_address inet,
  user_agent text,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz
);

create table if not exists public.login_history (
  id uuid primary key default gen_random_uuid(),
  user_profile_id uuid references public.user_profiles(id) on delete set null,
  identifier_hash text not null,
  successful boolean not null,
  ip_address inet,
  user_agent text,
  created_at timestamptz not null default now()
);

create index if not exists idx_auth_sessions_user on public.auth_sessions(user_profile_id, revoked_at);
create index if not exists idx_auth_sessions_expiry on public.auth_sessions(expires_at);
create index if not exists idx_login_history_user on public.login_history(user_profile_id, created_at desc);

alter table public.auth_sessions enable row level security;
alter table public.login_history enable row level security;

drop policy if exists "users read own sessions" on public.auth_sessions;
create policy "users read own sessions" on public.auth_sessions
for select to authenticated using (user_profile_id = (select id from public.user_profiles where auth_user_id = auth.uid()));