-- Final interview lifecycle, candidate rescheduling and strict staff assignment.
-- Run once after 021_google_meet_interview_lifecycle.sql.

alter table public.interviews
  add column if not exists confirmation_expires_at timestamptz,
  add column if not exists confirmed_at timestamptz,
  add column if not exists reschedule_requested_at timestamptz,
  add column if not exists reschedule_requested_start timestamptz,
  add column if not exists reschedule_previous_status public.interview_status,
  add column if not exists candidate_response_note text,
  add column if not exists reschedule_decision_status text
    check (reschedule_decision_status in ('ACCEPTED', 'REJECTED')),
  add column if not exists reschedule_decided_by uuid
    references public.user_profiles(id) on delete set null,
  add column if not exists reschedule_decided_at timestamptz,
  add column if not exists reschedule_decision_note text,
  add column if not exists day_reminder_sent_at timestamptz;

create index if not exists idx_interviews_pending_reschedule
  on public.interviews(reschedule_requested_at)
  where reschedule_requested_at is not null
    and reschedule_decision_status is null;

create index if not exists idx_interviews_day_reminder
  on public.interviews(scheduled_start)
  where scheduled_start is not null
    and day_reminder_sent_at is null
    and status not in ('CANCELLED', 'COMPLETED', 'NO_SHOW');


-- Automatically select an eligible interviewer for a newly created interview.
-- Priority:
-- 1. Interviewer from the same department
-- 2. Hiring Manager from the same department
-- 3. HR fallback
--
-- Admin, recruiter and operator accounts are never selected.
create or replace function public.suggest_interviewer_for_new_interview()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  selected_user uuid;
  selected_role public.user_role;
  selected_department text;
  job_department text;
begin
  -- Keep a manually supplied interviewer only when that user is eligible.
  if new.interviewer_id is not null then
    if exists (
      select 1
      from public.user_profiles
      where id = new.interviewer_id
        and active = true
        and role in ('interviewer', 'hiring_manager', 'hr')
    ) then
      return new;
    end if;

    new.interviewer_id := null;
  end if;

  select jp.department
  into job_department
  from public.applications a
  join public.job_positions jp
    on jp.id = a.job_position_id
  where a.id = new.application_id;

  select
    up.id,
    up.role,
    up.department
  into
    selected_user,
    selected_role,
    selected_department
  from public.user_profiles up
  left join public.interviewer_profiles ip
    on ip.user_profile_id = up.id
  left join public.interviews active_interview
    on active_interview.interviewer_id = up.id
   and active_interview.status not in (
     'CANCELLED',
     'COMPLETED',
     'NO_SHOW'
   )
  where up.active = true
    and coalesce(ip.available, true) = true

    -- Do not assign a staff member who already has an overlapping interview.
    and (
      new.scheduled_start is null
      or new.scheduled_end is null
      or not exists (
        select 1
        from public.interviews booked
        where booked.interviewer_id = up.id
          and booked.status not in (
            'CANCELLED',
            'COMPLETED',
            'NO_SHOW'
          )
          and booked.scheduled_start is not null
          and booked.scheduled_end is not null
          and tstzrange(
            booked.scheduled_start - interval '15 minutes',
            booked.scheduled_end + interval '15 minutes',
            '[)'
          ) && tstzrange(
            new.scheduled_start,
            new.scheduled_end,
            '[)'
          )
      )
    )

    and (
      (
        up.role = 'interviewer'
        and lower(coalesce(up.department, '')) =
            lower(coalesce(job_department, ''))
      )
      or
      (
        up.role = 'hiring_manager'
        and lower(coalesce(up.department, '')) =
            lower(coalesce(job_department, ''))
      )
      or up.role = 'hr'
    )
  group by
    up.id,
    up.role,
    up.department,
    up.created_at
  order by
    case
      when up.role = 'interviewer'
       and lower(coalesce(up.department, '')) =
           lower(coalesce(job_department, ''))
        then 0
      when up.role = 'hiring_manager'
       and lower(coalesce(up.department, '')) =
           lower(coalesce(job_department, ''))
        then 1
      when up.role = 'hr'
        then 2
      else 99
    end,
    count(active_interview.id),
    up.created_at
  limit 1;

  if selected_user is not null then
    new.interviewer_id := selected_user;
    new.assignment_status := 'PENDING_APPROVAL';

    new.assignment_reason := format(
      'Automatically suggested %s for %s using department fit, availability and active workload.',
      replace(selected_role::text, '_', ' '),
      coalesce(job_department, 'the role')
    );

    new.assignment_score := case
      when selected_role = 'interviewer'
       and lower(coalesce(selected_department, '')) =
           lower(coalesce(job_department, ''))
        then 95
      when selected_role = 'hiring_manager'
        then 90
      else 80
    end;
  else
    new.assignment_status := 'PENDING_APPROVAL';

    new.assignment_reason := format(
      'No available interviewer, hiring manager or HR reviewer for %s.',
      coalesce(job_department, 'the job department')
    );

    new.assignment_score := null;
  end if;

  return new;
end;
$$;


drop trigger if exists trg_suggest_interviewer
  on public.interviews;

create trigger trg_suggest_interviewer
before insert on public.interviews
for each row
execute function public.suggest_interviewer_for_new_interview();


-- Keep interview_assignments synchronized with the selected interviewer.
create or replace function public.sync_primary_interview_assignment()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.interviewer_id is null then
    return new;
  end if;

  update public.interview_assignments
  set
    status = 'REPLACED',
    responded_at = now(),
    updated_at = now()
  where interview_id = new.id
    and interviewer_id <> new.interviewer_id
    and status in (
      'PENDING_APPROVAL',
      'APPROVED',
      'ACCEPTED'
    );

  insert into public.interview_assignments (
    interview_id,
    interviewer_id,
    assignment_role,
    status,
    auto_suggested,
    match_score,
    match_reason,
    approved_by,
    approved_at
  )
  values (
    new.id,
    new.interviewer_id,
    'LEAD',
    case
      when new.assignment_status = 'APPROVED'
        then 'APPROVED'
      else 'PENDING_APPROVAL'
    end,
    new.assignment_approved_by is null,
    new.assignment_score,
    new.assignment_reason,
    new.assignment_approved_by,
    new.assignment_approved_at
  )
  on conflict (interview_id, interviewer_id)
  do update set
    assignment_role = excluded.assignment_role,
    status = excluded.status,
    match_score = excluded.match_score,
    match_reason = excluded.match_reason,
    approved_by = excluded.approved_by,
    approved_at = excluded.approved_at,
    updated_at = now();

  return new;
end;
$$;


drop trigger if exists trg_sync_primary_interview_assignment
  on public.interviews;

create trigger trg_sync_primary_interview_assignment
after insert or update of
  interviewer_id,
  assignment_status,
  assignment_approved_by,
  assignment_approved_at
on public.interviews
for each row
execute function public.sync_primary_interview_assignment();


-- Remove active legacy assignments where an administrator was selected
-- as the interviewer.
update public.interview_assignments ia
set
  status = 'REPLACED',
  responded_at = now(),
  updated_at = now()
from public.user_profiles up
where ia.interviewer_id = up.id
  and up.role = 'admin'
  and ia.status in (
    'PENDING_APPROVAL',
    'APPROVED',
    'ACCEPTED'
  );


update public.interviews i
set
  interviewer_id = null,
  assignment_status = 'PENDING_APPROVAL',
  assignment_reason =
    'Legacy administrator assignment removed; reassignment required.',
  assignment_score = null,
  assignment_approved_by = null,
  assignment_approved_at = null
from public.user_profiles up
where i.interviewer_id = up.id
  and up.role = 'admin';


-- Assign eligible staff to existing active interviews that do not currently
-- have an interviewer.
--
-- Scheduled interviews are checked for overlapping bookings and the
-- application-level 15-minute safety buffer.
do $$
declare
  target record;
  selected_id uuid;
  selected_role public.user_role;
  selected_department text;
  selected_score numeric(5,2);
begin
  for target in
    select
      i.id,
      jp.department,
      i.scheduled_start,
      i.scheduled_end
    from public.interviews i
    join public.applications a
      on a.id = i.application_id
    join public.job_positions jp
      on jp.id = a.job_position_id
    where i.interviewer_id is null
      and i.status not in (
        'CANCELLED',
        'COMPLETED',
        'NO_SHOW'
      )
  loop
    selected_id := null;
    selected_role := null;
    selected_department := null;
    selected_score := null;

    select
      up.id,
      up.role,
      up.department,
      case
        when up.role = 'interviewer' then 95
        when up.role = 'hiring_manager' then 90
        else 80
      end
    into
      selected_id,
      selected_role,
      selected_department,
      selected_score
    from public.user_profiles up
    left join public.interviewer_profiles ip
      on ip.user_profile_id = up.id
    left join public.interviews active_interview
      on active_interview.interviewer_id = up.id
     and active_interview.status not in (
       'CANCELLED',
       'COMPLETED',
       'NO_SHOW'
     )
    where up.active = true
      and coalesce(ip.available, true) = true

      -- Prevent database exclusion-constraint conflicts.
      and (
        target.scheduled_start is null
        or target.scheduled_end is null
        or not exists (
          select 1
          from public.interviews booked
          where booked.interviewer_id = up.id
            and booked.id <> target.id
            and booked.status not in (
              'CANCELLED',
              'COMPLETED',
              'NO_SHOW'
            )
            and booked.scheduled_start is not null
            and booked.scheduled_end is not null
            and tstzrange(
              booked.scheduled_start - interval '15 minutes',
              booked.scheduled_end + interval '15 minutes',
              '[)'
            ) && tstzrange(
              target.scheduled_start,
              target.scheduled_end,
              '[)'
            )
        )
      )

      and (
        (
          up.role = 'interviewer'
          and lower(coalesce(up.department, '')) =
              lower(coalesce(target.department, ''))
        )
        or
        (
          up.role = 'hiring_manager'
          and lower(coalesce(up.department, '')) =
              lower(coalesce(target.department, ''))
        )
        or up.role = 'hr'
      )
    group by
      up.id,
      up.role,
      up.department,
      up.created_at
    order by
      case
        when up.role = 'interviewer'
         and lower(coalesce(up.department, '')) =
             lower(coalesce(target.department, ''))
          then 0
        when up.role = 'hiring_manager'
         and lower(coalesce(up.department, '')) =
             lower(coalesce(target.department, ''))
          then 1
        when up.role = 'hr'
          then 2
        else 99
      end,
      count(active_interview.id),
      up.created_at
    limit 1;

    if selected_id is not null then
      update public.interviews
      set
        interviewer_id = selected_id,
        assignment_status = 'PENDING_APPROVAL',
        assignment_reason = format(
          'Automatically suggested %s for %s using department fit, availability and active workload.',
          replace(selected_role::text, '_', ' '),
          target.department
        ),
        assignment_score = selected_score,
        assignment_approved_by = null,
        assignment_approved_at = null
      where id = target.id;
    else
      update public.interviews
      set
        assignment_status = 'PENDING_APPROVAL',
        assignment_reason = format(
          'No conflict-free interviewer, hiring manager or HR reviewer is currently available for %s.',
          coalesce(target.department, 'this department')
        ),
        assignment_score = null,
        assignment_approved_by = null,
        assignment_approved_at = null
      where id = target.id;
    end if;
  end loop;
end;
$$;