-- Offer acceptance is public-token based; account activation starts only after acceptance.
-- Run once after 023_hiring_decisions_and_employee_activation.sql.

alter table public.offers
  add column if not exists response_token text unique,
  add column if not exists account_invitation_sent_at timestamptz;

create index if not exists idx_offers_response_token
  on public.offers(response_token)
  where response_token is not null;

notify pgrst, 'reload schema';
