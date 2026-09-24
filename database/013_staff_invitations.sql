-- Staff invitation flow. Run after 012_auth_sessions_and_audit.sql.

alter table public.user_invitations add column if not exists full_name text;
alter table public.user_invitations add column if not exists username text;
alter table public.user_invitations add column if not exists accepted_user_profile_id uuid references public.user_profiles(id) on delete set null;

create index if not exists idx_user_invitations_active on public.user_invitations(email, expires_at)
where accepted_at is null and revoked_at is null;