from datetime import datetime, timezone

import pytest

from app.schemas import InterviewScheduleCreate
from app.services.recruitment import interviewer_is_eligible, interviewer_priority


def test_administrator_is_never_eligible_for_interview_assignment():
    assert interviewer_is_eligible({"id": "admin", "role": "admin", "department": "Engineering"}, "Engineering") is False


def test_department_interviewer_has_priority_over_manager_and_hr():
    candidates = [
        {"id": "hr", "role": "hr", "department": "Human Resources", "active_workload": 0},
        {"id": "manager", "role": "hiring_manager", "department": "Engineering", "active_workload": 0},
        {"id": "interviewer", "role": "interviewer", "department": "Engineering", "active_workload": 2},
    ]
    ranked = sorted(candidates, key=lambda profile: interviewer_priority(profile, "Engineering"))
    assert [profile["id"] for profile in ranked] == ["interviewer", "manager", "hr"]


def test_hr_is_valid_fallback_for_other_departments():
    assert interviewer_is_eligible({"id": "hr", "role": "hr", "department": "Human Resources"}, "Sales") is True
    assert interviewer_is_eligible({"id": "wrong", "role": "interviewer", "department": "Sales"}, "Engineering") is False


def test_interview_schedule_requires_timezone_aware_values():
    with pytest.raises(ValueError):
        InterviewScheduleCreate(
            scheduled_start=datetime(2099, 1, 1, 10, 0),
            scheduled_end=datetime(2099, 1, 1, 11, 0),
        )
    valid = InterviewScheduleCreate(
        scheduled_start=datetime(2099, 1, 1, 10, 0, tzinfo=timezone.utc),
        scheduled_end=datetime(2099, 1, 1, 11, 0, tzinfo=timezone.utc),
    )
    assert valid.timezone == "Asia/Karachi"

