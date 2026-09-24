-- Final production indexes for filtered operations and ownership checks.
-- Run after 017_offer_document_storage.sql.

create index if not exists idx_hiring_requisitions_status_created on public.hiring_requisitions(status, created_at desc);
create index if not exists idx_job_hiring_team_role on public.job_hiring_team(job_position_id, team_role);
create index if not exists idx_notifications_unread_user on public.notifications(user_profile_id, created_at desc) where read_at is null;
create index if not exists idx_onboarding_tasks_employee_status on public.onboarding_tasks(employee_id, status, due_date);
create index if not exists idx_offers_candidate_status on public.offers(status, expiry_date);
