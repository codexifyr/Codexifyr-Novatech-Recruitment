-- CV evidence review metadata and optional shared staff demonstration personas.
-- Run after 019_cv_prompt_injection_protection.sql.

alter table public.applications
  add column if not exists cv_original_filename text,
  add column if not exists cv_mime_type text,
  add column if not exists reviewed_at timestamptz,
  add column if not exists review_version text;

alter table public.user_profiles
  add column if not exists shared_staff_account boolean not null default false,
  add column if not exists shared_staff_selectable boolean not null default false;

create index if not exists idx_applications_review_queue
  on public.applications(status, final_score desc, created_at desc)
  where archived_at is null;
create index if not exists idx_user_profiles_shared_staff
  on public.user_profiles(department, role)
  where shared_staff_selectable = true and active = true;

insert into public.user_profiles (full_name, email, username, role, department, job_title, active, shared_staff_selectable)
values
  ('Ayesha Khan', 'demo.hr@novatech.local', 'demo_hr', 'hr', 'Human Resources', 'HR Manager', true, true),
  ('Bilal Ahmed', 'demo.recruiter@novatech.local', 'demo_recruiter', 'recruiter', 'Talent Acquisition', 'Senior Recruiter', true, true),
  ('Sara Malik', 'demo.manager.engineering@novatech.local', 'demo_eng_manager', 'hiring_manager', 'Engineering', 'Engineering Hiring Manager', true, true),
  ('Hamza Ali', 'demo.interviewer.python@novatech.local', 'demo_python_interviewer', 'interviewer', 'Engineering', 'Python Interviewer', true, true),
  ('Mariam Noor', 'demo.interviewer.qa@novatech.local', 'demo_qa_interviewer', 'interviewer', 'Quality Assurance', 'QA Interviewer', true, true),
  ('Usman Raza', 'demo.manager.sales@novatech.local', 'demo_sales_manager', 'hiring_manager', 'Sales', 'Sales Hiring Manager', true, true),
  ('Zoya Shah', 'demo.interviewer.sales@novatech.local', 'demo_sales_interviewer', 'interviewer', 'Sales', 'Sales Interviewer', true, true),
  ('Omar Farooq', 'demo.operator@novatech.local', 'demo_operator', 'operator', 'Operations', 'Recruitment Operator', true, true)
on conflict (email) do update set
  full_name = excluded.full_name, username = excluded.username, role = excluded.role,
  department = excluded.department, job_title = excluded.job_title,
  active = true, shared_staff_selectable = true;

insert into public.user_roles (user_profile_id, role)
select id, role from public.user_profiles where shared_staff_selectable = true
on conflict (user_profile_id, role) do nothing;

insert into public.interviewer_profiles (user_profile_id, specialties, interview_types, max_interviews_per_day, available)
select id,
  case
    when job_title ilike '%python%' then '["Python","FastAPI","SQL","Backend"]'::jsonb
    when job_title ilike '%qa%' then '["QA","Automation","Testing"]'::jsonb
    when department = 'Sales' then '["Sales","CRM","Communication"]'::jsonb
    else '["General","Behavioural"]'::jsonb
  end,
  case when role = 'interviewer' then '["Screening","Technical","Final"]'::jsonb else '["Screening","Managerial","Final"]'::jsonb end,
  4, true
from public.user_profiles
where shared_staff_selectable = true and role in ('interviewer','hiring_manager','hr')
on conflict (user_profile_id) do update set specialties = excluded.specialties, available = true;

insert into public.notification_preferences (user_profile_id, email_enabled, in_app_enabled, interview_alerts, approval_alerts, digest_frequency)
select id, false, true, true, true, 'IMMEDIATE'
from public.user_profiles where shared_staff_selectable = true
on conflict (user_profile_id) do nothing;

-- Existing rows receive a review marker without changing their current decision.
update public.applications
set review_version = coalesce(review_version, 'LEGACY'), reviewed_at = coalesce(reviewed_at, updated_at)
where ai_review is not null and reviewed_at is null;
