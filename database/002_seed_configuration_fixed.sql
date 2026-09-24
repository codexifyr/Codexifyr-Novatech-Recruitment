-- Fixed, simpler version of the NovaTech Solutions configuration seed.
-- Run this instead of 002_seed_configuration.sql.

insert into public.job_positions (code, title, department, description, shortlist_threshold, manual_review_threshold)
values
  ('PY-DEV', 'Python Developer', 'Engineering', 'Backend and API development role', 80, 60),
  ('BD-EXEC', 'Business Development Executive', 'Business Development', 'Lead generation and client relationship role', 80, 60),
  ('QA-ENG', 'QA Engineer', 'Quality Assurance', 'Functional and automation testing role', 80, 60)
on conflict (code) do update set
  title = excluded.title,
  department = excluded.department,
  description = excluded.description,
  shortlist_threshold = excluded.shortlist_threshold,
  manual_review_threshold = excluded.manual_review_threshold,
  updated_at = now();

insert into public.scoring_rules (job_position_id, rule_key, description, points, condition_type, condition_value)
values
  ((select id from public.job_positions where code = 'PY-DEV'), 'python', 'Python', 20, 'skill', jsonb_build_object('value','Python')),
  ((select id from public.job_positions where code = 'PY-DEV'), 'framework', 'FastAPI or Django', 15, 'any_skill', jsonb_build_object('values',jsonb_build_array('FastAPI','Django'))),
  ((select id from public.job_positions where code = 'PY-DEV'), 'sql', 'SQL', 10, 'skill', jsonb_build_object('value','SQL')),
  ((select id from public.job_positions where code = 'PY-DEV'), 'api', 'REST APIs', 10, 'skill', jsonb_build_object('value','REST APIs')),
  ((select id from public.job_positions where code = 'PY-DEV'), 'git', 'Git', 5, 'skill', jsonb_build_object('value','Git')),
  ((select id from public.job_positions where code = 'PY-DEV'), 'docker', 'Docker', 10, 'skill', jsonb_build_object('value','Docker')),
  ((select id from public.job_positions where code = 'PY-DEV'), 'cloud', 'AWS or Azure', 10, 'any_skill', jsonb_build_object('values',jsonb_build_array('AWS','Azure'))),
  ((select id from public.job_positions where code = 'PY-DEV'), 'experience', '3+ years experience', 10, 'min_experience', jsonb_build_object('value',3)),
  ((select id from public.job_positions where code = 'PY-DEV'), 'domain', 'Relevant domain experience', 10, 'skill', jsonb_build_object('value','Backend')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'communication', 'Communication', 20, 'skill', jsonb_build_object('value','Communication')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'crm', 'CRM', 15, 'skill', jsonb_build_object('value','CRM')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'leadgen', 'Lead generation', 15, 'skill', jsonb_build_object('value','Lead Generation')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'sales', 'B2B sales', 15, 'skill', jsonb_build_object('value','B2B Sales')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'negotiation', 'Negotiation', 10, 'skill', jsonb_build_object('value','Negotiation')),
  ((select id from public.job_positions where code = 'BD-EXEC'), 'experience', '3+ years experience', 15, 'min_experience', jsonb_build_object('value',3)),
  ((select id from public.job_positions where code = 'QA-ENG'), 'testing', 'Test case design', 20, 'skill', jsonb_build_object('value','Test Cases')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'automation', 'Automation testing', 20, 'skill', jsonb_build_object('value','Automation')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'api', 'API testing', 10, 'skill', jsonb_build_object('value','API Testing')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'sql', 'SQL', 10, 'skill', jsonb_build_object('value','SQL')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'bugtracking', 'Bug tracking', 10, 'skill', jsonb_build_object('value','Jira')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'git', 'Git', 5, 'skill', jsonb_build_object('value','Git')),
  ((select id from public.job_positions where code = 'QA-ENG'), 'experience', '2+ years experience', 15, 'min_experience', jsonb_build_object('value',2))
on conflict (job_position_id, rule_key, version) do update set
  description = excluded.description,
  points = excluded.points,
  condition_type = excluded.condition_type,
  condition_value = excluded.condition_value,
  active = true;

select code, title, department from public.job_positions order by code;

