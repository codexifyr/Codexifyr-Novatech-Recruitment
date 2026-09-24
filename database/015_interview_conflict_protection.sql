-- Interview conflict protection. Run after 014_candidate_document_security.sql.

create extension if not exists btree_gist;

do $$
begin
  alter table public.interviews
    add constraint interviews_no_active_overlap
    exclude using gist (
      interviewer_id with =,
      tstzrange(scheduled_start, scheduled_end, '[)') with &&
    )
    where (
      interviewer_id is not null
      and scheduled_start is not null
      and scheduled_end is not null
      and status not in ('CANCELLED', 'COMPLETED')
    );
exception
  when duplicate_object then null;
end $$;

create index if not exists idx_interviews_interviewer_schedule
on public.interviews(interviewer_id, scheduled_start, scheduled_end)
where scheduled_start is not null and scheduled_end is not null;