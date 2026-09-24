-- NovaTech Solutions operational dashboard metrics for WF-08.
-- Returns exactly one row calculated from persisted database records.

create or replace view public.operational_dashboard_metrics
with (security_invoker = true)
as
with application_status_counts as (
  select status::text as status, count(*)::integer as total
  from public.applications
  group by status
),
status_json as (
  select coalesce(jsonb_object_agg(status, total), '{}'::jsonb) as breakdown
  from application_status_counts
)
select
  now() as generated_at,

  (select count(*)::integer from public.candidates) as candidates_total,
  (select count(*)::integer from public.applications) as applications_total,
  (select count(*)::integer from public.applications where created_at >= current_date) as applications_today,
  (select breakdown from status_json) as application_status_breakdown,

  (select count(*)::integer from public.applications where status = 'MANUAL_REVIEW') as manual_review_count,
  (select count(*)::integer from public.applications where status = 'SHORTLISTED') as shortlisted_count,
  (select count(*)::integer from public.interviews where status = 'PENDING_CONFIRMATION') as pending_interview_confirmations,
  (
    select count(*)::integer
    from public.interviews i
    where i.status = 'COMPLETED'
      and not exists (
        select 1 from public.interview_feedback f where f.interview_id = i.id
      )
  ) as pending_interview_feedback,

  (select count(*)::integer from public.offer_approvals where status = 'PENDING') as pending_offer_approvals,
  (select count(*)::integer from public.offers where status in ('APPROVED', 'OFFERED')) as pending_candidate_offers,
  (select count(*)::integer from public.offers where status = 'EXPIRED' or (status = 'OFFERED' and expiry_date < current_date)) as expired_offers,

  (select count(*)::integer from public.employees where status = 'ONBOARDING') as employees_onboarding,
  (select count(*)::integer from public.onboarding_tasks where status = 'OVERDUE' or (status in ('PENDING', 'IN_PROGRESS') and due_date < current_date)) as overdue_onboarding_tasks,

  (select count(*)::integer from public.automation_errors where status = 'OPEN') as open_errors,
  (select count(*)::integer from public.automation_errors where status = 'RETRYING') as retrying_errors,
  (select count(*)::integer from public.automation_errors where status = 'DEAD') as dead_queue_count,
  (select count(*)::integer from public.automation_errors where status = 'RESOLVED' and resolved_at >= current_date) as errors_resolved_today,

  (select count(*)::integer from public.workflow_executions where started_at >= current_date) as executions_today,
  (select count(*)::integer from public.workflow_executions where started_at >= current_date and status = 'SUCCESS') as successful_executions_today,
  (select count(*)::integer from public.workflow_executions where started_at >= current_date and status in ('FAILED', 'DEAD')) as failed_executions_today,
  (select coalesce(sum(retry_count), 0)::integer from public.workflow_executions where started_at >= current_date) as retries_today,

  (
    select coalesce(round(avg(extract(epoch from (updated_at - created_at)))::numeric, 2), 0)
    from public.applications
    where status in ('REJECTED', 'DECLINED', 'ONBOARDED')
  ) as average_application_processing_seconds;

grant select on public.operational_dashboard_metrics to authenticated;
grant select on public.operational_dashboard_metrics to service_role;

select * from public.operational_dashboard_metrics;
