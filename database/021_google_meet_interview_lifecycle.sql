-- Google Calendar/Meet scheduling, delivery and reminder state.
-- Run after 020_cv_review_and_shared_staff.sql.

alter table public.interviews
  add column if not exists meeting_code text,
  add column if not exists google_event_id text,
  add column if not exists google_event_url text,
  add column if not exists schedule_timezone text not null default 'Asia/Karachi',
  add column if not exists schedule_email_sent_at timestamptz,
  add column if not exists reminder_sent_at timestamptz,
  add column if not exists start_alert_sent_at timestamptz;

alter table public.applications
  add column if not exists candidate_portal_invited_at timestamptz;

create unique index if not exists idx_interviews_google_event_id
  on public.interviews(google_event_id) where google_event_id is not null;
create index if not exists idx_interviews_due_reminders
  on public.interviews(scheduled_start)
  where scheduled_start is not null and status not in ('CANCELLED','COMPLETED');
