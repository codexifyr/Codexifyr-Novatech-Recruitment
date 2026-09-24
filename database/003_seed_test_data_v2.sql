-- NovaTech Solutions fictional test data - simplified version.
-- Run this file instead of any previous 003 seed query.

with seed as (
  select
    g.i,
    case when g.i >= 38 then g.i - 37 else g.i end as base_i,
    (array[
      'Ali Ahmed','Sara Khan','Hamza Malik','Ayesha Noor','Bilal Raza',
      'Hina Tariq','Usman Iqbal','Mariam Shah','Danish Qureshi','Iqra Javed',
      'Omar Siddiqui','Laiba Hassan','Zain Abbas','Nimra Saeed','Fahad Nadeem',
      'Mehwish Ali','Talha Yousaf','Anum Farooq','Saad Rehman','Sana Khalid',
      'Haris Nawaz','Mahnoor Aslam','Rayan Ahmed','Eman Zafar','Waleed Tariq',
      'Areeba Khan','Shahzaib Malik','Maha Iqbal','Arham Raza','Noor Fatima',
      'Dua Siddiqui','Kashif Javed','Minal Hassan','Adeel Shah','Zoya Abbas',
      'Rida Saeed','Sameer Nadeem','Aiman Ali','Yasir Farooq','Kiran Rehman'
    ])[case when g.i >= 38 then g.i - 37 else g.i end] as full_name
  from generate_series(1, 40) as g(i)
), contact_data as (
  select
    s.*,
    case when s.i = 5 then 'invalid-email'
         when s.i = 6 then 'missing-at.example.com'
         else lower(replace(s.full_name, ' ', '.')) || '@example.com' end as email,
    case when s.i = 5 then '123'
         when s.i = 6 then 'phone-missing'
         else '+92-300-' || lpad((1000000 + s.base_i)::text, 7, '0') end as phone
  from seed s
), candidates_to_insert as (
  select distinct on (base_i)
    'CAN-2026-' || lpad(base_i::text, 3, '0') as candidate_code,
    full_name,
    lower(full_name) as normalized_name,
    email,
    lower(trim(email)) as normalized_email,
    phone,
    regexp_replace(phone, '[^0-9+]', '', 'g') as normalized_phone
  from contact_data
  order by base_i, i
)
insert into public.candidates (
  candidate_code, full_name, normalized_name, email, normalized_email,
  phone, normalized_phone
)
select candidate_code, full_name, normalized_name, email, normalized_email,
       phone, normalized_phone
from candidates_to_insert
on conflict (normalized_email, normalized_phone) do update
set updated_at = now();

with seed as (
  select
    g.i,
    case when g.i >= 38 then g.i - 37 else g.i end as base_i,
    case ((case when g.i >= 38 then g.i - 37 else g.i end - 1) % 3)
      when 0 then 'PY-DEV' when 1 then 'BD-EXEC' else 'QA-ENG' end as position_code,
    (array[
      'Ali Ahmed','Sara Khan','Hamza Malik','Ayesha Noor','Bilal Raza',
      'Hina Tariq','Usman Iqbal','Mariam Shah','Danish Qureshi','Iqra Javed',
      'Omar Siddiqui','Laiba Hassan','Zain Abbas','Nimra Saeed','Fahad Nadeem',
      'Mehwish Ali','Talha Yousaf','Anum Farooq','Saad Rehman','Sana Khalid',
      'Haris Nawaz','Mahnoor Aslam','Rayan Ahmed','Eman Zafar','Waleed Tariq',
      'Areeba Khan','Shahzaib Malik','Maha Iqbal','Arham Raza','Noor Fatima',
      'Dua Siddiqui','Kashif Javed','Minal Hassan','Adeel Shah','Zoya Abbas',
      'Rida Saeed','Sameer Nadeem','Aiman Ali','Yasir Farooq','Kiran Rehman'
    ])[case when g.i >= 38 then g.i - 37 else g.i end] as full_name
  from generate_series(1, 40) as g(i)
), shaped as (
  select *,
    case when base_i <= 5 then 0.5 when base_i <= 15 then 2
         when base_i <= 25 then 4 when base_i <= 30 then 7 else 3 end as experience_years,
    case when position_code = 'PY-DEV' and base_i <= 5 then jsonb_build_array('Python')
         when position_code = 'PY-DEV' and base_i <= 15 then jsonb_build_array('Python','SQL','Git')
         when position_code = 'PY-DEV' then jsonb_build_array('Python','FastAPI','SQL','REST APIs','Git','Docker','AWS','Backend')
         when position_code = 'BD-EXEC' and base_i <= 5 then jsonb_build_array('Communication')
         when position_code = 'BD-EXEC' and base_i <= 15 then jsonb_build_array('Communication','CRM','Lead Generation')
         when position_code = 'BD-EXEC' then jsonb_build_array('Communication','CRM','Lead Generation','B2B Sales','Negotiation')
         when base_i <= 5 then jsonb_build_array('Test Cases')
         when base_i <= 15 then jsonb_build_array('Test Cases','Jira')
         else jsonb_build_array('Test Cases','Automation','API Testing','SQL','Jira','Git') end as skills,
    case when base_i not in (1,2,3,4,5) then true else false end as cv_present
  from seed
)
insert into public.applications (
  application_code, candidate_id, job_position_id, correlation_id, event_id,
  name_at_application, email_at_application, phone_at_application,
  experience_years, skills, expected_salary, joining_date, cv_present,
  source, status, status_reason
)
select
  'APP-2026-' || lpad(s.i::text, 4, '0'),
  c.id,
  p.id,
  'COR-20260917-' || lpad(s.i::text, 4, '0'),
  'APPLICATION_EVENT_2026_' || lpad(s.i::text, 4, '0'),
  s.full_name,
  case when s.i = 5 then 'invalid-email' when s.i = 6 then 'missing-at.example.com'
       else lower(replace(s.full_name, ' ', '.')) || '@example.com' end,
  case when s.i = 5 then '123' when s.i = 6 then 'phone-missing'
       else '+92-300-' || lpad((1000000 + s.base_i)::text, 7, '0') end,
  s.experience_years,
  s.skills,
  case when s.base_i <= 5 then 90000 else 150000 + (s.base_i * 2500) end,
  current_date + (30 + s.base_i),
  s.cv_present,
  case when s.i >= 38 then 'replayed_webhook' else 'fictional_seed' end,
  'NEW',
  case when s.base_i <= 5 then 'Seeded incomplete or weak test scenario' else 'Seeded fictional application' end
from shaped s
join public.candidates c on c.candidate_code = 'CAN-2026-' || lpad(s.base_i::text, 3, '0')
join public.job_positions p on p.code = s.position_code
on conflict (event_id) do nothing;

select
  count(*) as total_applications,
  count(*) filter (where source = 'replayed_webhook') as replay_test_records,
  count(*) filter (where cv_present = false) as incomplete_cv_records
from public.applications;

