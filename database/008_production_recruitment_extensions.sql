alter type public.user_role add value if not exists 'employee';

alter table public.user_profiles add column if not exists job_title text;
alter table public.user_profiles add column if not exists avatar_url text;
alter table public.user_profiles add column if not exists timezone text not null default 'Asia/Karachi';
alter table public.user_profiles add column if not exists last_login_at timestamptz;

create table if not exists public.departments (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  name text not null unique,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.designations (
  id uuid primary key default gen_random_uuid(),
  code text not null unique,
  title text not null unique,
  department_id uuid references public.departments(id) on delete set null,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.user_roles (
  id uuid primary key default gen_random_uuid(),
  user_profile_id uuid not null references public.user_profiles(id) on delete cascade,
  role public.user_role not null,
  assigned_by uuid references public.user_profiles(id) on delete set null,
  assigned_at timestamptz not null default now(),
  unique (user_profile_id, role)
);

insert into public.user_roles (user_profile_id, role)
select id, role from public.user_profiles
on conflict (user_profile_id, role) do nothing;

create table if not exists public.interviewer_profiles (
  user_profile_id uuid primary key references public.user_profiles(id) on delete cascade,
  specialties jsonb not null default '[]'::jsonb,
  interview_types jsonb not null default '["Screening","Technical","HR","Managerial","Final"]'::jsonb,
  max_interviews_per_day integer not null default 4 check (max_interviews_per_day between 1 and 12),
  available boolean not null default true,
  notes text,
  updated_at timestamptz not null default now()
);

alter table public.interviews add column if not exists assignment_status text not null default 'PENDING_APPROVAL';
alter table public.interviews add column if not exists interview_type text not null default 'Technical';
alter table public.interviews add column if not exists round_number integer not null default 1;
alter table public.interviews add column if not exists duration_minutes integer not null default 60;
alter table public.interviews add column if not exists assignment_score numeric(5,2);
alter table public.interviews add column if not exists assignment_reason text;
alter table public.interviews add column if not exists assignment_approved_by uuid references public.user_profiles(id) on delete set null;
alter table public.interviews add column if not exists assignment_approved_at timestamptz;
alter table public.interviews add column if not exists interviewer_response text;
alter table public.interviews add column if not exists interviewer_responded_at timestamptz;

create table if not exists public.interview_assignments (
  id uuid primary key default gen_random_uuid(),
  interview_id uuid not null references public.interviews(id) on delete cascade,
  interviewer_id uuid not null references public.user_profiles(id) on delete restrict,
  assignment_role text not null default 'INTERVIEWER' check (assignment_role in ('LEAD','INTERVIEWER','OBSERVER')),
  status text not null default 'PENDING_APPROVAL' check (status in ('PENDING_APPROVAL','APPROVED','ACCEPTED','DECLINED','REPLACED')),
  auto_suggested boolean not null default true,
  match_score numeric(5,2),
  match_reason text,
  approved_by uuid references public.user_profiles(id) on delete set null,
  approved_at timestamptz,
  responded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (interview_id, interviewer_id)
);

create table if not exists public.internal_notes (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('APPLICATION','INTERVIEW','OFFER','EMPLOYEE')),
  entity_id uuid not null,
  note text not null,
  visibility text not null default 'HIRING_TEAM' check (visibility in ('HIRING_TEAM','HR_ONLY','ADMIN_ONLY')),
  created_by uuid references public.user_profiles(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_profile_id uuid not null references public.user_profiles(id) on delete cascade,
  title text not null,
  message text not null,
  category text not null default 'INFO',
  action_url text,
  read_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references public.user_profiles(id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id text,
  previous_data jsonb,
  new_data jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

insert into public.departments (code, name) values
  ('HR', 'Human Resources'), ('TA', 'Talent Acquisition'),
  ('ENG', 'Engineering'), ('PRODUCT', 'Product'), ('DESIGN', 'Design'),
  ('SALES', 'Sales'), ('MARKETING', 'Marketing'), ('FIN', 'Finance'),
  ('OPS', 'Operations'), ('ADMIN', 'Administration')
on conflict (code) do update set name = excluded.name;

insert into public.designations (code, title, department_id)
select valueset.code, valueset.title, departments.id
from (values
  ('HR-MGR','HR Manager','HR'), ('HR-OFFICER','HR Officer','HR'),
  ('TA-MGR','Talent Acquisition Manager','TA'), ('RECRUITER','Recruiter','TA'),
  ('SR-RECRUITER','Senior Recruiter','TA'), ('HIRING-MGR','Hiring Manager','ENG'),
  ('TECH-INT','Technical Interviewer','ENG'), ('HR-INT','HR Interviewer','HR'),
  ('LEAD-INT','Lead Interviewer','ENG'), ('OPS-MGR','Operations Manager','OPS'),
  ('SYS-ADMIN','System Administrator','ADMIN')
) as valueset(code, title, department_code)
join public.departments on departments.code = valueset.department_code
on conflict (code) do update set title = excluded.title, department_id = excluded.department_id;

create index if not exists idx_interview_assignments_interview on public.interview_assignments(interview_id, status);
create index if not exists idx_interview_assignments_interviewer on public.interview_assignments(interviewer_id, status);
create index if not exists idx_notifications_user_unread on public.notifications(user_profile_id, created_at desc) where read_at is null;
create index if not exists idx_audit_entity on public.audit_logs(entity_type, entity_id, created_at desc);
create index if not exists idx_internal_notes_entity on public.internal_notes(entity_type, entity_id, created_at desc);

-- Automatically propose the least-loaded active interviewer when WF-04 creates
-- an interview. The proposal remains PENDING_APPROVAL until Admin, HR or the
-- Hiring Manager approves or replaces it in the application.
create or replace function public.suggest_interviewer_for_new_interview()
returns trigger language plpgsql security definer set search_path = public as $$
declare
  selected_user uuid;
  job_department text;
begin
  if new.interviewer_id is not null then return new; end if;
  select jp.department into job_department
  from public.applications a join public.job_positions jp on jp.id = a.job_position_id
  where a.id = new.application_id;

  select up.id into selected_user
  from public.user_profiles up
  left join public.interviewer_profiles ip on ip.user_profile_id = up.id
  left join public.interview_assignments ia on ia.interviewer_id = up.id and ia.status in ('PENDING_APPROVAL','APPROVED','ACCEPTED')
  left join public.interviews scheduled on scheduled.id = ia.interview_id and scheduled.scheduled_start >= now()
  where up.active = true
    and up.role in ('interviewer','hiring_manager','hr','admin')
    and coalesce(ip.available, true) = true
  group by up.id, up.department, up.created_at
  order by (up.department = job_department) desc, count(scheduled.id) asc, up.created_at asc
  limit 1;

  if selected_user is not null then
    new.interviewer_id := selected_user;
    new.assignment_status := 'PENDING_APPROVAL';
    new.assignment_reason := 'Automatically suggested by department match and active workload.';
    new.assignment_score := case when exists(select 1 from public.user_profiles where id = selected_user and department = job_department) then 90 else 70 end;
  end if;
  return new;
end $$;

drop trigger if exists trg_suggest_interviewer on public.interviews;
create trigger trg_suggest_interviewer before insert on public.interviews
for each row execute function public.suggest_interviewer_for_new_interview();

alter table public.departments enable row level security;
alter table public.designations enable row level security;
alter table public.user_roles enable row level security;
alter table public.interviewer_profiles enable row level security;
alter table public.interview_assignments enable row level security;
alter table public.internal_notes enable row level security;
alter table public.notifications enable row level security;
alter table public.audit_logs enable row level security;

-- Server-side service-role calls remain authoritative. Authenticated staff can
-- read safe reference data; user-specific records are restricted.
create policy "authenticated read departments" on public.departments for select to authenticated using (true);
create policy "authenticated read designations" on public.designations for select to authenticated using (true);
create policy "users read own roles" on public.user_roles for select to authenticated
using (user_profile_id = (select id from public.user_profiles where auth_user_id = auth.uid()));
create policy "users read own notifications" on public.notifications for select to authenticated
using (user_profile_id = (select id from public.user_profiles where auth_user_id = auth.uid()));
