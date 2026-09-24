-- Initial Supabase Row Level Security policies.
-- The n8n service-role key bypasses RLS; frontend users do not.

create or replace function public.current_user_has_role(required_role public.user_role)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.user_profiles p
    where p.auth_user_id = auth.uid()
      and p.role = required_role
      and p.active = true
  );
$$;

alter table public.user_profiles enable row level security;
alter table public.candidates enable row level security;
alter table public.applications enable row level security;
alter table public.interviews enable row level security;
alter table public.interview_feedback enable row level security;
alter table public.offers enable row level security;
alter table public.offer_approvals enable row level security;
alter table public.employees enable row level security;
alter table public.onboarding_tasks enable row level security;
alter table public.automation_logs enable row level security;
alter table public.automation_errors enable row level security;

drop policy if exists user_profiles_self_or_admin on public.user_profiles;
create policy user_profiles_self_or_admin on public.user_profiles
for select using (
  auth_user_id = auth.uid()
  or public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
);

drop policy if exists candidates_self_or_staff on public.candidates;
create policy candidates_self_or_staff on public.candidates
for select using (
  email = (select email from public.user_profiles where auth_user_id = auth.uid())
  or public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
  or public.current_user_has_role('hiring_manager')
  or public.current_user_has_role('interviewer')
);

drop policy if exists applications_candidate_or_staff on public.applications;
create policy applications_candidate_or_staff on public.applications
for select using (
  candidate_id in (
    select c.id from public.candidates c
    where c.email = (select email from public.user_profiles where auth_user_id = auth.uid())
  )
  or public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
  or public.current_user_has_role('hiring_manager')
  or public.current_user_has_role('interviewer')
);

drop policy if exists interviews_assigned_or_staff on public.interviews;
create policy interviews_assigned_or_staff on public.interviews
for select using (
  interviewer_id in (select id from public.user_profiles where auth_user_id = auth.uid())
  or application_id in (select a.id from public.applications a join public.candidates c on c.id = a.candidate_id where c.email = (select email from public.user_profiles where auth_user_id = auth.uid()))
  or public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
  or public.current_user_has_role('hiring_manager')
);

drop policy if exists staff_operational_logs on public.automation_logs;
create policy staff_operational_logs on public.automation_logs
for select using (
  public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
);

drop policy if exists staff_operational_errors on public.automation_errors;
create policy staff_operational_errors on public.automation_errors
for select using (
  public.current_user_has_role('admin')
  or public.current_user_has_role('operator')
);

