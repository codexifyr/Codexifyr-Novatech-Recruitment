-- Private storage, reusable analytics views, and production safeguards.
-- Run after 010_advanced_ats_modules.sql.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('candidate-documents', 'candidate-documents', false, 10485760,
   array['application/pdf','image/jpeg','image/png','application/vnd.openxmlformats-officedocument.wordprocessingml.document']),
  ('profile-images', 'profile-images', false, 5242880,
   array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "users upload own profile images" on storage.objects;
create policy "users upload own profile images" on storage.objects
for insert to authenticated
with check (bucket_id = 'profile-images' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "users read own profile images" on storage.objects;
create policy "users read own profile images" on storage.objects
for select to authenticated
using (bucket_id = 'profile-images' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "users update own profile images" on storage.objects;
create policy "users update own profile images" on storage.objects
for update to authenticated
using (bucket_id = 'profile-images' and (storage.foldername(name))[1] = auth.uid()::text)
with check (bucket_id = 'profile-images' and (storage.foldername(name))[1] = auth.uid()::text);

create or replace view public.recruitment_funnel_metrics as
select
  count(*) as applications_total,
  count(*) filter (where status = 'MANUAL_REVIEW') as manual_review_total,
  count(*) filter (where status in ('SHORTLISTED','INTERVIEW_SCHEDULED','INTERVIEWED')) as interview_pipeline_total,
  count(*) filter (where status in ('SELECTED','OFFER_PENDING_APPROVAL','OFFERED')) as offer_pipeline_total,
  count(*) filter (where status in ('ACCEPTED','ONBOARDING','ONBOARDED')) as hired_total,
  count(*) filter (where status = 'REJECTED') as rejected_total,
  round(avg(final_score), 2) as average_final_score
from public.applications
where archived_at is null;

create or replace view public.interviewer_workload as
select
  up.id as interviewer_id,
  up.full_name,
  up.department,
  up.job_title,
  count(i.id) filter (where i.scheduled_start >= now() and i.status not in ('CANCELLED','COMPLETED')) as upcoming_interviews,
  count(i.id) filter (where i.status = 'COMPLETED') as completed_interviews
from public.user_profiles up
left join public.interviews i on i.interviewer_id = up.id
where up.active = true and up.role in ('interviewer','hiring_manager','hr','admin')
group by up.id, up.full_name, up.department, up.job_title;

create or replace view public.hiring_velocity_metrics as
select
  jp.id as job_position_id,
  jp.title,
  jp.department,
  count(a.id) as applications,
  round(avg(extract(epoch from (a.updated_at - a.created_at)) / 86400.0), 2) as average_processing_days,
  count(a.id) filter (where a.status in ('ACCEPTED','ONBOARDING','ONBOARDED')) as hires
from public.job_positions jp
left join public.applications a on a.job_position_id = jp.id
group by jp.id, jp.title, jp.department;

create or replace function public.prevent_last_active_admin_deactivation()
returns trigger language plpgsql as $$
begin
  if old.role = 'admin' and old.active = true and new.active = false
     and (select count(*) from public.user_profiles where role = 'admin' and active = true) <= 1 then
    raise exception 'The last active administrator cannot be deactivated';
  end if;
  return new;
end $$;

drop trigger if exists trg_last_active_admin on public.user_profiles;
create trigger trg_last_active_admin before update of active on public.user_profiles
for each row execute function public.prevent_last_active_admin_deactivation();

create index if not exists idx_applications_active_created on public.applications(created_at desc) where archived_at is null;
create index if not exists idx_applications_recruiter on public.applications(assigned_recruiter_id, status);
create index if not exists idx_interviews_schedule_active on public.interviews(scheduled_start, scheduled_end) where status not in ('CANCELLED','COMPLETED');
create index if not exists idx_audit_actor_created on public.audit_logs(actor_id, created_at desc);
