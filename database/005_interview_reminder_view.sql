-- NovaTech interview reminder queue view
-- Safe to run more than once.

create or replace view public.interview_reminder_queue as
select
  i.id as interview_id,
  i.interview_code,
  i.application_id,
  i.scheduled_start,
  i.scheduled_end,
  i.meeting_url,
  i.status as interview_status,
  i.confirmation_token,
  i.reminder_count,
  i.last_reminder_at,
  c.id as candidate_id,
  c.full_name as candidate_name,
  c.email as candidate_email,
  c.phone as candidate_phone,
  jp.title as position_title,
  a.correlation_id,
  a.application_code
from public.interviews i
join public.applications a on a.id = i.application_id
join public.candidates c on c.id = a.candidate_id
join public.job_positions jp on jp.id = a.job_position_id
where i.status in ('PENDING_CONFIRMATION', 'CONFIRMED');

grant select on public.interview_reminder_queue to authenticated;
grant select on public.interview_reminder_queue to service_role;

select
  interview_code,
  candidate_name,
  candidate_email,
  scheduled_start,
  interview_status,
  reminder_count
from public.interview_reminder_queue
order by scheduled_start;
