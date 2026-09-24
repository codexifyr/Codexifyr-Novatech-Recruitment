-- Public careers portal, account aliases, OTP challenges, and application settings.

alter type public.user_role add value if not exists 'hr';
alter type public.user_role add value if not exists 'recruiter';

alter table public.user_profiles add column if not exists username text;
alter table public.user_profiles add column if not exists candidate_id uuid references public.candidates(id) on delete set null;
alter table public.user_profiles add column if not exists must_change_password boolean not null default true;
create unique index if not exists idx_user_profiles_username_lower
  on public.user_profiles (lower(username)) where username is not null;

alter table public.job_positions add column if not exists slug text;
alter table public.job_positions add column if not exists location text not null default 'Islamabad, Pakistan';
alter table public.job_positions add column if not exists employment_type text not null default 'Full-time';
alter table public.job_positions add column if not exists workplace_type text not null default 'Hybrid';
alter table public.job_positions add column if not exists experience_level text not null default 'Mid-level';
alter table public.job_positions add column if not exists salary_min numeric(12,2);
alter table public.job_positions add column if not exists salary_max numeric(12,2);
alter table public.job_positions add column if not exists currency text not null default 'PKR';
alter table public.job_positions add column if not exists responsibilities jsonb not null default '[]'::jsonb;
alter table public.job_positions add column if not exists requirements jsonb not null default '[]'::jsonb;
alter table public.job_positions add column if not exists benefits jsonb not null default '[]'::jsonb;
alter table public.job_positions add column if not exists closes_at timestamptz;

update public.job_positions
set slug = lower(regexp_replace(regexp_replace(title, '[^a-zA-Z0-9]+', '-', 'g'), '(^-|-$)', '', 'g'))
where slug is null;

alter table public.job_positions alter column slug set not null;
create unique index if not exists idx_job_positions_slug on public.job_positions(slug);
create index if not exists idx_job_positions_public on public.job_positions(active, closes_at);

create table if not exists public.otp_challenges (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  purpose text not null check (purpose in ('CANDIDATE_REGISTRATION', 'PASSWORD_RESET', 'EMAIL_VERIFICATION')),
  otp_hash text not null,
  attempts integer not null default 0,
  max_attempts integer not null default 5,
  expires_at timestamptz not null,
  used_at timestamptz,
  requested_ip inet,
  created_at timestamptz not null default now()
);
create index if not exists idx_otp_lookup on public.otp_challenges(lower(email), purpose, created_at desc);

create table if not exists public.app_settings (
  key text primary key,
  value jsonb not null,
  public boolean not null default false,
  updated_by uuid references public.user_profiles(id) on delete set null,
  updated_at timestamptz not null default now()
);

alter table public.job_positions enable row level security;
alter table public.otp_challenges enable row level security;
alter table public.app_settings enable row level security;

drop policy if exists public_read_active_jobs on public.job_positions;
create policy public_read_active_jobs on public.job_positions for select
using (active = true and (closes_at is null or closes_at > now()));

drop policy if exists staff_manage_jobs on public.job_positions;
create policy staff_manage_jobs on public.job_positions for all
using (
  public.current_user_has_role('admin') or
  public.current_user_has_role('operator') or
  public.current_user_has_role('hiring_manager')
)
with check (
  public.current_user_has_role('admin') or
  public.current_user_has_role('operator') or
  public.current_user_has_role('hiring_manager')
);

drop policy if exists public_read_settings on public.app_settings;
create policy public_read_settings on public.app_settings for select using (public = true);

insert into public.app_settings (key, value, public) values
  ('company', '{"name":"NovaTech Solutions","email":"careers@novatech.example","location":"Islamabad, Pakistan"}'::jsonb, true),
  ('hiring', '{"candidate_registration":"after_selection","otp_expiry_minutes":10}'::jsonb, false)
on conflict (key) do nothing;

update public.job_positions set
  location = 'Islamabad, Pakistan', workplace_type = 'Hybrid', employment_type = 'Full-time',
  experience_level = 'Mid-level', salary_min = 180000, salary_max = 300000,
  responsibilities = '["Build reliable APIs and backend services","Write tested, maintainable Python code","Collaborate with product and frontend teams"]'::jsonb,
  requirements = '["Strong Python fundamentals","FastAPI or Django experience","SQL and Git proficiency"]'::jsonb,
  benefits = '["Hybrid work","Learning budget","Health coverage"]'::jsonb
where code = 'PY-DEV';

update public.job_positions set
  location = 'Islamabad, Pakistan', workplace_type = 'On-site', employment_type = 'Full-time',
  experience_level = 'Mid-level', salary_min = 120000, salary_max = 220000,
  responsibilities = '["Build qualified sales pipelines","Manage client relationships","Maintain accurate CRM records"]'::jsonb,
  requirements = '["B2B communication skills","CRM experience","Strong negotiation ability"]'::jsonb,
  benefits = '["Performance bonus","Learning budget","Health coverage"]'::jsonb
where code = 'BD-EXEC';

update public.job_positions set
  location = 'Islamabad, Pakistan', workplace_type = 'Hybrid', employment_type = 'Full-time',
  experience_level = 'Mid-level', salary_min = 140000, salary_max = 240000,
  responsibilities = '["Design and execute test plans","Build regression automation","Partner with engineering on quality"]'::jsonb,
  requirements = '["Manual and API testing","Automation fundamentals","SQL and issue tracking"]'::jsonb,
  benefits = '["Hybrid work","Learning budget","Health coverage"]'::jsonb
where code = 'QA-ENG';
