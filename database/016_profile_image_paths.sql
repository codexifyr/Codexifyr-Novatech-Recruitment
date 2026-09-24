-- Durable profile-image references. Run after 015_interview_conflict_protection.sql.

alter table public.user_profiles add column if not exists avatar_storage_path text;
create index if not exists idx_user_profiles_avatar_path on public.user_profiles(avatar_storage_path) where avatar_storage_path is not null;