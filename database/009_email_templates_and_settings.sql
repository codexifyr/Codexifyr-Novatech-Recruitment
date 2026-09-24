-- Branded, editable communication templates. Internal fields and AI reasoning
-- are intentionally excluded from candidate-facing placeholders.

create table if not exists public.email_templates (
  id uuid primary key default gen_random_uuid(),
  template_key text not null unique,
  name text not null,
  subject_template text not null,
  html_template text not null,
  text_template text not null,
  enabled boolean not null default true,
  version integer not null default 1,
  updated_by uuid references public.user_profiles(id) on delete set null,
  updated_at timestamptz not null default now()
);

create table if not exists public.email_delivery_logs (
  id uuid primary key default gen_random_uuid(),
  template_key text,
  recipient_email text not null,
  subject text not null,
  entity_type text,
  entity_id uuid,
  provider text,
  status text not null default 'QUEUED' check (status in ('QUEUED','SENT','FAILED','RETRYING')),
  retry_count integer not null default 0,
  error_message text,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

insert into public.email_templates (template_key, name, subject_template, html_template, text_template) values
('APPLICATION_RECEIVED','Application received','Application received — {{job_title}} | NovaTech Solutions','<h1>Application received</h1><p>Hello {{candidate_name}},</p><p>Thank you for applying for <strong>{{job_title}}</strong>.</p><p>Application reference: <strong>{{application_code}}</strong></p><p>Our hiring team will review your application and contact you about the next step.</p>','Hello {{candidate_name}}, we received your application for {{job_title}}. Reference: {{application_code}}.'),
('INTERVIEW_INVITATION','Interview invitation','Interview invitation — {{job_title}} | NovaTech Solutions','<h1>Your interview is ready</h1><p>Hello {{candidate_name}},</p><p>Your {{interview_type}} interview for <strong>{{job_title}}</strong> is scheduled for {{scheduled_time}} ({{timezone}}).</p><p>Duration: {{duration_minutes}} minutes</p><p><a href="{{confirmation_url}}">Confirm or request a new time</a></p><p>Reference: {{interview_code}}</p>','Hello {{candidate_name}}, your {{interview_type}} interview for {{job_title}} is scheduled for {{scheduled_time}} {{timezone}}. Confirm: {{confirmation_url}}'),
('INTERVIEW_REMINDER','Interview reminder','Reminder — {{job_title}} interview | NovaTech Solutions','<h1>Interview reminder</h1><p>Hello {{candidate_name}},</p><p>Your interview starts at {{scheduled_time}} ({{timezone}}).</p><p><a href="{{meeting_url}}">Join interview</a></p>','Reminder: your {{job_title}} interview starts at {{scheduled_time}} {{timezone}}. {{meeting_url}}'),
('OFFER_READY','Offer ready','Your offer — {{job_title}} | NovaTech Solutions','<h1>Your offer is ready</h1><p>Hello {{candidate_name}},</p><p>We are pleased to share your offer for <strong>{{job_title}}</strong>.</p><p><a href="{{offer_url}}">Review your secure offer</a></p><p>This link expires on {{expiry_date}}.</p>','Hello {{candidate_name}}, your offer for {{job_title}} is ready: {{offer_url}}. Expires {{expiry_date}}.'),
('ACCOUNT_OTP','Account verification','Your verification code | NovaTech Solutions','<h1>Verification code</h1><p>Your one-time code is <strong>{{otp}}</strong>.</p><p>It expires in {{expiry_minutes}} minutes. Never share this code.</p>','Your NovaTech Solutions verification code is {{otp}}. It expires in {{expiry_minutes}} minutes.')
on conflict (template_key) do nothing;

alter table public.email_templates enable row level security;
alter table public.email_delivery_logs enable row level security;
create index if not exists idx_email_logs_entity on public.email_delivery_logs(entity_type, entity_id, created_at desc);

