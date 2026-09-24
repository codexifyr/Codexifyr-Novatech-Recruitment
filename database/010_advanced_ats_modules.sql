-- Advanced ATS modules: granular permissions, hiring pipelines, availability,
-- invitations, documents, communications, privacy and configurable operations.

create table if not exists public.permissions (
  key text primary key,
  description text not null,
  category text not null
);

create table if not exists public.role_permissions (
  role public.user_role not null,
  permission_key text not null references public.permissions(key) on delete cascade,
  primary key (role, permission_key)
);

create table if not exists public.user_permission_overrides (
  user_profile_id uuid not null references public.user_profiles(id) on delete cascade,
  permission_key text not null references public.permissions(key) on delete cascade,
  allowed boolean not null,
  granted_by uuid references public.user_profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  primary key (user_profile_id, permission_key)
);

create table if not exists public.user_invitations (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  role public.user_role not null,
  token_hash text not null unique,
  invited_by uuid references public.user_profiles(id) on delete set null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.hiring_requisitions (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  title text not null,
  department_id uuid references public.departments(id) on delete set null,
  requested_by uuid references public.user_profiles(id) on delete set null,
  headcount integer not null default 1 check (headcount > 0),
  budget_min numeric(12,2),
  budget_max numeric(12,2),
  currency text not null default 'PKR',
  justification text,
  status text not null default 'PENDING' check (status in ('DRAFT','PENDING','APPROVED','REJECTED','CLOSED')),
  approved_by uuid references public.user_profiles(id) on delete set null,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.job_positions add column if not exists requisition_id uuid references public.hiring_requisitions(id) on delete set null;
alter table public.job_positions add column if not exists publication_status text not null default 'PUBLISHED';
alter table public.job_positions add column if not exists application_deadline timestamptz;
alter table public.job_positions add column if not exists vacancy_count integer not null default 1;

create table if not exists public.pipeline_stages (
  id uuid primary key default gen_random_uuid(),
  job_position_id uuid references public.job_positions(id) on delete cascade,
  stage_key text not null,
  name text not null,
  sequence integer not null,
  stage_type text not null default 'CUSTOM',
  active boolean not null default true,
  unique (job_position_id, stage_key)
);

alter table public.applications add column if not exists pipeline_stage_id uuid references public.pipeline_stages(id) on delete set null;
alter table public.applications add column if not exists assigned_recruiter_id uuid references public.user_profiles(id) on delete set null;
alter table public.applications add column if not exists tags jsonb not null default '[]'::jsonb;
alter table public.applications add column if not exists archived_at timestamptz;
alter table public.applications add column if not exists consent_version text default '1.0';
alter table public.applications add column if not exists retention_until date;

create table if not exists public.job_hiring_team (
  job_position_id uuid not null references public.job_positions(id) on delete cascade,
  user_profile_id uuid not null references public.user_profiles(id) on delete cascade,
  team_role text not null check (team_role in ('RECRUITER','HR_OWNER','HIRING_MANAGER','INTERVIEWER')),
  primary key (job_position_id, user_profile_id, team_role)
);

create table if not exists public.interviewer_availability (
  id uuid primary key default gen_random_uuid(),
  interviewer_id uuid not null references public.user_profiles(id) on delete cascade,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  recurrence_rule text,
  unavailable boolean not null default false,
  created_at timestamptz not null default now(),
  check (ends_at > starts_at)
);

create table if not exists public.interview_scorecards (
  id uuid primary key default gen_random_uuid(),
  interview_id uuid not null references public.interviews(id) on delete cascade,
  interviewer_id uuid not null references public.user_profiles(id) on delete restrict,
  criteria jsonb not null default '{}'::jsonb,
  overall_score numeric(5,2),
  recommendation text check (recommendation in ('STRONG_HIRE','HIRE','REVIEW','NO_HIRE','STRONG_NO_HIRE')),
  comments text,
  submitted_at timestamptz,
  visible_after_panel_complete boolean not null default true,
  unique (interview_id, interviewer_id)
);

create table if not exists public.candidate_documents (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid not null references public.candidates(id) on delete cascade,
  application_id uuid references public.applications(id) on delete cascade,
  document_type text not null,
  file_name text not null,
  storage_path text not null,
  mime_type text,
  size_bytes bigint,
  verification_status text not null default 'PENDING' check (verification_status in ('PENDING','VERIFIED','REJECTED')),
  verified_by uuid references public.user_profiles(id) on delete set null,
  verified_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.candidate_communications (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  direction text not null check (direction in ('OUTBOUND','INBOUND','INTERNAL')),
  channel text not null check (channel in ('EMAIL','PHONE','PORTAL','NOTE')),
  subject text,
  body text,
  delivery_status text,
  created_by uuid references public.user_profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.notification_preferences (
  user_profile_id uuid primary key references public.user_profiles(id) on delete cascade,
  email_enabled boolean not null default true,
  in_app_enabled boolean not null default true,
  interview_alerts boolean not null default true,
  approval_alerts boolean not null default true,
  digest_frequency text not null default 'DAILY' check (digest_frequency in ('IMMEDIATE','DAILY','WEEKLY','NONE')),
  updated_at timestamptz not null default now()
);

create table if not exists public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  candidate_id uuid references public.candidates(id) on delete set null,
  request_type text not null check (request_type in ('EXPORT','CORRECT','DELETE')),
  status text not null default 'OPEN' check (status in ('OPEN','IN_PROGRESS','COMPLETED','REJECTED')),
  notes text,
  requested_at timestamptz not null default now(),
  completed_at timestamptz
);

insert into public.permissions(key,description,category) values
 ('users.manage','Create and manage staff accounts','Administration'),
 ('jobs.manage','Create, publish and archive jobs','Recruitment'),
 ('applications.view','View candidate applications','Recruitment'),
 ('applications.manage','Move candidates and add decisions','Recruitment'),
 ('interviews.assign','Assign and approve interviewers','Interviews'),
 ('interviews.conduct','Conduct interviews and submit scorecards','Interviews'),
 ('offers.manage','Create and manage offers','Offers'),
 ('offers.approve','Approve or reject offers','Offers'),
 ('employees.manage','Manage employee onboarding','People'),
 ('reports.view','View operational analytics','Reporting'),
 ('audit.view','View audit history','Administration'),
 ('workflows.manage','Retry and monitor workflows','Automation')
on conflict (key) do nothing;

insert into public.role_permissions(role,permission_key)
select role::public.user_role, permission_key from (values
 ('admin','users.manage'),('admin','jobs.manage'),('admin','applications.view'),('admin','applications.manage'),('admin','interviews.assign'),('admin','interviews.conduct'),('admin','offers.manage'),('admin','offers.approve'),('admin','employees.manage'),('admin','reports.view'),('admin','audit.view'),('admin','workflows.manage'),
 ('hr','jobs.manage'),('hr','applications.view'),('hr','applications.manage'),('hr','interviews.assign'),('hr','interviews.conduct'),('hr','offers.manage'),('hr','employees.manage'),('hr','reports.view'),
 ('recruiter','jobs.manage'),('recruiter','applications.view'),('recruiter','applications.manage'),('recruiter','interviews.assign'),
 ('hiring_manager','applications.view'),('hiring_manager','applications.manage'),('hiring_manager','interviews.assign'),('hiring_manager','interviews.conduct'),('hiring_manager','offers.approve'),('hiring_manager','reports.view'),
 ('interviewer','applications.view'),('interviewer','interviews.conduct'),
 ('operator','applications.view'),('operator','reports.view'),('operator','workflows.manage')
) p(role,permission_key)
on conflict do nothing;

create index if not exists idx_applications_pipeline on public.applications(pipeline_stage_id, created_at desc);
create index if not exists idx_availability_interviewer on public.interviewer_availability(interviewer_id, starts_at, ends_at);
create index if not exists idx_documents_candidate on public.candidate_documents(candidate_id, created_at desc);
create index if not exists idx_communications_application on public.candidate_communications(application_id, created_at desc);

alter table public.permissions enable row level security;
alter table public.role_permissions enable row level security;
alter table public.user_permission_overrides enable row level security;
alter table public.user_invitations enable row level security;
alter table public.hiring_requisitions enable row level security;
alter table public.pipeline_stages enable row level security;
alter table public.job_hiring_team enable row level security;
alter table public.interviewer_availability enable row level security;
alter table public.interview_scorecards enable row level security;
alter table public.candidate_documents enable row level security;
alter table public.candidate_communications enable row level security;
alter table public.notification_preferences enable row level security;
alter table public.privacy_requests enable row level security;

create policy "authenticated read permissions" on public.permissions for select to authenticated using (true);
create policy "authenticated read role permissions" on public.role_permissions for select to authenticated using (true);
create policy "users manage own preferences" on public.notification_preferences for all to authenticated
using (user_profile_id=(select id from public.user_profiles where auth_user_id=auth.uid()))
with check (user_profile_id=(select id from public.user_profiles where auth_user_id=auth.uid()));
