-- Human hiring decisions, offer-ready candidates and employee activation metadata.
-- Run once after 022_final_interview_workflow.sql.

alter table public.interview_scorecards
  add column if not exists technical_score integer check (technical_score between 1 and 10),
  add column if not exists communication_score integer check (communication_score between 1 and 10),
  add column if not exists problem_solving_score integer check (problem_solving_score between 1 and 10),
  add column if not exists experience_score integer check (experience_score between 1 and 10),
  add column if not exists team_fit_score integer check (team_fit_score between 1 and 10);

create table if not exists public.hiring_decisions (
  id uuid primary key default gen_random_uuid(),
  application_id uuid not null unique references public.applications(id) on delete cascade,
  interview_id uuid references public.interviews(id) on delete set null,
  status text not null default 'PENDING_MANAGER'
    check (status in ('PENDING_MANAGER','PENDING_HR','APPROVED','REJECTED','SECOND_INTERVIEW','RETURNED_TO_REVIEW')),
  manager_status text not null default 'PENDING' check (manager_status in ('PENDING','APPROVED','REJECTED')),
  manager_id uuid references public.user_profiles(id) on delete set null,
  manager_reason text,
  manager_decided_at timestamptz,
  hr_status text not null default 'PENDING' check (hr_status in ('PENDING','APPROVED','REJECTED')),
  hr_id uuid references public.user_profiles(id) on delete set null,
  hr_reason text,
  hr_decided_at timestamptz,
  final_decided_by uuid references public.user_profiles(id) on delete set null,
  final_decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_hiring_decisions_status on public.hiring_decisions(status, updated_at desc);
alter table public.hiring_decisions enable row level security;

alter table public.offers
  add column if not exists employment_title text,
  add column if not exists employment_level text,
  add column if not exists employment_type text,
  add column if not exists department text;

alter table public.employees
  add column if not exists employment_title text,
  add column if not exists employment_level text,
  add column if not exists employment_type text,
  add column if not exists offer_id uuid references public.offers(id) on delete set null;

insert into public.hiring_decisions (application_id, interview_id, status)
select a.id, i.id, 'PENDING_MANAGER'
from public.applications a
join lateral (
  select id from public.interviews
  where application_id = a.id and status = 'COMPLETED'
  order by created_at desc limit 1
) i on true
where not exists (select 1 from public.hiring_decisions hd where hd.application_id = a.id)
on conflict (application_id) do nothing;

notify pgrst, 'reload schema';
