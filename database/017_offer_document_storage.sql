-- Private offer-letter PDF storage. Run after 016_profile_image_paths.sql.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('offer-documents', 'offer-documents', false, 10485760, array['application/pdf'])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

alter table public.offers add column if not exists document_storage_path text;
create index if not exists idx_offers_document_path on public.offers(document_storage_path) where document_storage_path is not null;