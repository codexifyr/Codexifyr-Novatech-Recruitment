-- NovaTech Solutions Recruitment Automation
-- Phase 2: relational database foundation

create extension if not exists pgcrypto;

create type public.user_role as enum (
  'candidate', 'admin', 'hiring_manager', 'interviewer', 'operator'
);

create type public.application_status as enum (
  'NEW', 'VALIDATING', 'VALIDATED', 'SCORED', 'SHORTLISTED',
  'MANUAL_REVIEW', 'REJECTED', 'INTERVIEW_SCHEDULED', 'INTERVIEWED',
  'SELECTED', 'OFFER_PENDING_APPROVAL', 'OFFERED', 'ACCEPTED',
  'DECLINED', 'NEGOTIATION', 'ONBOARDING', 'ONBOARDED'
);

create type public.interview_status as enum (
  'PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED', 'COMPLETED', 'NO_SHOW'
);

create type public.offer_status as enum (
  'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'OFFERED',
  'ACCEPTED', 'DECLINED', 'NEGOTIATION', 'EXPIRED', 'CANCELLED'
);

create type public.approval_status as enum ('PENDING', 'APPROVED', 'REJECTED');
create type public.task_status as enum ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'OVERDUE', 'CANCELLED');
create type public.error_status as enum ('OPEN', 'RETRYING', 'DEAD', 'RESOLVED', 'IGNORED');

create table public.user_profiles (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid unique,
  full_name text not null,
  email text not null unique,
  role public.user_role not null,
  department text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.job_positions (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  title text not null unique,
  department text not null,
  description text,
  shortlist_threshold numeric(5,2) not null default 80,
  manual_review_threshold numeric(5,2) not null default 60,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (manual_review_threshold < shortlist_threshold)
);

create table public.candidates (
  id uuid primary key default gen_random_uuid(),
  candidate_code text not null unique,
  full_name text not null,
  normalized_name text not null,
  email text not null,
  normalized_email text not null,
  phone text not null,
  normalized_phone text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (normalized_email, normalized_phone)
);

create table public.scoring_rules (
  id uuid primary key default gen_random_uuid(),
  job_position_id uuid not null references public.job_positions(id) on delete cascade,
  rule_key text not null,
  description text not null,
  points numeric(6,2) not null,
  condition_type text not null,
  condition_value jsonb not null default '{}'::jsonb,
  version integer not null default 1,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (job_position_id, rule_key, version)
);

create table public.applications (
  id uuid primary key default gen_random_uuid(),
  application_code text not null unique,
  candidate_id uuid not null references public.candidates(id) on delete restrict,
  job_position_id uuid not null references public.job_positions(id) on delete restrict,
  correlation_id text not null unique,
  event_id text not null unique,
  name_at_application text not null,
  email_at_application text not null,
  phone_at_application text not null,
  experience_years numeric(5,2),
  skills jsonb not null default '[]'::jsonb,
  expected_salary numeric(12,2),
  currency text not null default 'PKR',
  joining_date date,
  cv_url text,
  cv_present boolean not null default false,
  source text not null default 'test_form',
  status public.application_status not null default 'NEW',
  status_reason text,
  rule_score numeric(6,2),
  ai_review jsonb,
  final_score numeric(6,2),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.candidate_status_history (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null references public.applications(id) on delete cascade,
  previous_status public.application_status,
  new_status public.application_status not null,
  reason text,
  workflow_name text not null,
  workflow_version text not null default '1.0.0',
  execution_id text,
  changed_by uuid references public.user_profiles(id) on delete set null,
  correlation_id text not null,
  changed_at timestamptz not null default now()
);

create table public.interviews (
  id uuid primary key default gen_random_uuid(),
  interview_code text not null unique,
  application_id uuid not null references public.applications(id) on delete restrict,
  interviewer_id uuid references public.user_profiles(id) on delete set null,
  scheduled_start timestamptz,
  scheduled_end timestamptz,
  meeting_url text,
  status public.interview_status not null default 'PENDING_CONFIRMATION',
  confirmation_token text unique,
  reminder_count integer not null default 0,
  last_reminder_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.interview_feedback (
  id uuid primary key default gen_random_uuid(),
  interview_id uuid not null unique references public.interviews(id) on delete cascade,
  technical_score integer check (technical_score between 1 and 10),
  communication_score integer check (communication_score between 1 and 10),
  problem_solving_score integer check (problem_solving_score between 1 and 10),
  experience_score integer check (experience_score between 1 and 10),
  team_fit_score integer check (team_fit_score between 1 and 10),
  comments text,
  recommendation text check (recommendation in ('SELECT', 'REJECT', 'REVIEW')),
  submitted_by uuid references public.user_profiles(id) on delete set null,
  submitted_at timestamptz
);

create table public.offers (
  id uuid primary key default gen_random_uuid(),
  offer_code text not null unique,
  application_id uuid not null unique references public.applications(id) on delete restrict,
  salary numeric(12,2) not null,
  currency text not null default 'PKR',
  joining_date date not null,
  probation_months integer not null default 3,
  reporting_manager_id uuid references public.user_profiles(id) on delete set null,
  expiry_date date not null,
  status public.offer_status not null default 'DRAFT',
  approval_required_levels integer not null default 1,
  document_url text,
  sent_at timestamptz,
  candidate_responded_at timestamptz,
  response_notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (approval_required_levels between 1 and 2)
);

create table public.offer_approvals (
  id uuid primary key default gen_random_uuid(),
  offer_id uuid not null references public.offers(id) on delete cascade,
  approval_level integer not null check (approval_level between 1 and 2),
  approver_id uuid references public.user_profiles(id) on delete set null,
  status public.approval_status not null default 'PENDING',
  comments text,
  decided_at timestamptz,
  unique (offer_id, approval_level)
);

create table public.employees (
  id uuid primary key default gen_random_uuid(),
  employee_code text not null unique,
  candidate_id uuid not null references public.candidates(id) on delete restrict,
  application_id uuid not null unique references public.applications(id) on delete restrict,
  department text not null,
  manager_id uuid references public.user_profiles(id) on delete set null,
  start_date date not null,
  status text not null default 'ONBOARDING' check (status in ('ONBOARDING', 'ACTIVE', 'COMPLETED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.onboarding_tasks (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references public.employees(id) on delete cascade,
  task_key text not null,
  title text not null,
  description text,
  owner_role public.user_role not null default 'admin',
  due_date date not null,
  status public.task_status not null default 'PENDING',
  completed_at timestamptz,
  completed_by uuid references public.user_profiles(id) on delete set null,
  unique (employee_id, task_key)
);

create table public.processed_events (
  id uuid primary key default gen_random_uuid(),
  event_key text not null unique,
  event_type text not null,
  correlation_id text not null,
  payload_hash text,
  entity_type text,
  entity_id uuid,
  result text not null default 'PROCESSED',
  first_processed_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table public.workflow_executions (
  id uuid primary key default gen_random_uuid(),
  execution_id text not null unique,
  workflow_name text not null,
  workflow_version text not null default '1.0.0',
  correlation_id text not null,
  status text not null check (status in ('RUNNING', 'SUCCESS', 'FAILED', 'RETRYING', 'DEAD')),
  retry_count integer not null default 0,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  error_id uuid
);

create table public.automation_logs (
  id uuid primary key default gen_random_uuid(),
  correlation_id text not null,
  workflow_name text not null,
  workflow_version text not null default '1.0.0',
  execution_id text,
  entity_type text,
  entity_id uuid,
  action text not null,
  outcome text not null check (outcome in ('SUCCESS', 'FAILURE', 'INFO')),
  retry_count integer not null default 0,
  actor_id uuid references public.user_profiles(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  error_code text,
  error_message text,
  created_at timestamptz not null default now()
);

create table public.automation_errors (
  id uuid primary key default gen_random_uuid(),
  correlation_id text not null,
  workflow_name text not null,
  execution_id text,
  entity_type text,
  entity_id uuid,
  error_code text not null,
  error_message text not null,
  original_payload jsonb not null default '{}'::jsonb,
  retryable boolean not null default false,
  retry_count integer not null default 0,
  status public.error_status not null default 'OPEN',
  next_retry_at timestamptz,
  resolved_at timestamptz,
  resolved_by uuid references public.user_profiles(id) on delete set null,
  resolution_notes text,
  created_at timestamptz not null default now()
);

create index idx_candidates_contact on public.candidates(normalized_email, normalized_phone);
create index idx_applications_status on public.applications(status);
create index idx_applications_position_status on public.applications(job_position_id, status);
create index idx_applications_correlation on public.applications(correlation_id);
create index idx_history_application_time on public.candidate_status_history(application_id, changed_at);
create index idx_interviews_pending on public.interviews(status, scheduled_start);
create index idx_offers_pending on public.offers(status, expiry_date);
create index idx_onboarding_due on public.onboarding_tasks(status, due_date);
create index idx_errors_queue on public.automation_errors(status, next_retry_at);
create index idx_logs_correlation_time on public.automation_logs(correlation_id, created_at);

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare
  t text;
begin
  foreach t in array array['user_profiles','job_positions','candidates','applications','interviews','offers','employees'] loop
    execute format('create trigger %I before update on public.%I for each row execute function public.set_updated_at()', 'trg_' || t || '_updated_at', t);
  end loop;
end $$;

