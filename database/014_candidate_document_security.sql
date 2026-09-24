-- Candidate document storage access. Run after 013_staff_invitations.sql.

drop policy if exists "candidates upload own documents" on storage.objects;
create policy "candidates upload own documents" on storage.objects
for insert to authenticated
with check (
  bucket_id = 'candidate-documents'
  and (storage.foldername(name))[1] = (select candidate_id::text from public.user_profiles where auth_user_id = auth.uid())
);

drop policy if exists "candidates read own documents" on storage.objects;
create policy "candidates read own documents" on storage.objects
for select to authenticated
using (
  bucket_id = 'candidate-documents'
  and (
    (storage.foldername(name))[1] = (select candidate_id::text from public.user_profiles where auth_user_id = auth.uid())
    or exists (select 1 from public.user_profiles where auth_user_id = auth.uid() and role in ('admin','hr','recruiter'))
  )
);

create index if not exists idx_candidate_documents_verification on public.candidate_documents(verification_status, created_at desc);