-- CV storage metadata and deterministic prompt-injection screening audit.
-- Run once after 018_final_production_extensions.sql.

alter table public.applications
  add column if not exists cv_storage_path text,
  add column if not exists cv_security_status text not null default 'NOT_SCANNED',
  add column if not exists cv_security_flags jsonb not null default '[]'::jsonb;

do $$ begin
  alter table public.applications add constraint applications_cv_security_status_check
    check (cv_security_status in ('NOT_SCANNED','CLEAN','SUSPICIOUS','UNSCANNABLE'));
exception when duplicate_object then null;
end $$;

create table if not exists public.cv_security_assessments (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  file_sha256 text not null check (file_sha256 ~ '^[0-9a-f]{64}$'),
  mime_type text not null,
  status text not null check (status in ('CLEAN','SUSPICIOUS','UNSCANNABLE')),
  flags jsonb not null default '[]'::jsonb,
  extracted_characters integer not null default 0 check (extracted_characters >= 0),
  scanner_version text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_cv_security_application_created
  on public.cv_security_assessments(application_id, created_at desc);
create index if not exists idx_cv_security_review_queue
  on public.applications(cv_security_status, created_at desc)
  where cv_security_status in ('SUSPICIOUS','UNSCANNABLE');

alter table public.cv_security_assessments enable row level security;
drop policy if exists "hiring staff read cv security assessments" on public.cv_security_assessments;
create policy "hiring staff read cv security assessments" on public.cv_security_assessments
for select to authenticated using (
  exists (
    select 1 from public.user_profiles
    where auth_user_id = auth.uid()
      and active = true
      and role in ('admin','hr','recruiter','hiring_manager')
  )
);

-- CVs arrive before a candidate account exists. Only the backend service role
-- writes this folder; no public/authenticated insert policy is intentionally added.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('candidate-documents', 'candidate-documents', false, 10485760,
  array['application/pdf','image/jpeg','image/png','application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
