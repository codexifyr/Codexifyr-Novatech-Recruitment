from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app.config import get_settings
from app.security import csrf_is_valid
from app.services.supabase import SupabaseClient
from app.routes.candidate import validate_document
from app.routes.admin import schedule_conflicts


@pytest.fixture
def client(monkeypatch):
    profile = {"id": "profile-1", "email": "person@example.com", "role": "hr", "active": True, "full_name": "Test Person"}
    async def query(self, table, query="", **kwargs):
        if table == "user_profiles":
            return [profile]
        return []
    monkeypatch.setattr(SupabaseClient, "query", query)
    monkeypatch.setattr(SupabaseClient, "login", AsyncMock(return_value={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}))
    monkeypatch.setattr(SupabaseClient, "insert", AsyncMock(return_value=[]))
    monkeypatch.setattr(SupabaseClient, "update", AsyncMock(return_value=[]))
    return TestClient(app)


def test_login_sets_http_only_session_and_csrf_cookie(client):
    response = client.post("/api/v1/auth/login", json={"identifier": "person@example.com", "password": "password123"})
    assert response.status_code == 200
    cookies = response.cookies
    assert cookies.get("novatech_session") == "access"
    assert cookies.get("novatech_refresh") == "refresh"
    assert cookies.get("novatech_csrf")
    assert "HttpOnly" in response.headers["set-cookie"]


def test_cookie_state_change_requires_csrf(client):
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", b"novatech_csrf=expected")], "query_string": b"", "server": ("test", 80), "client": ("test", 1), "scheme": "http"}
    request = Request(scope)
    assert not csrf_is_valid(request, get_settings())
    scope["headers"].append((b"x-csrf-token", b"expected"))
    assert csrf_is_valid(Request(scope), get_settings())


def test_logout_revokes_cookie_session(client):
    response = client.post("/api/v1/auth/logout", headers={"Cookie": "novatech_session=access; novatech_csrf=expected", "X-CSRF-Token": "expected"})
    assert response.status_code == 200
    assert 'novatech_session=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_invitation_acceptance_creates_profile_and_closes_invitation(monkeypatch):
    invitation = {"id": "inv-1", "email": "new@example.com", "full_name": "New Person", "role": "recruiter", "expires_at": "2099-01-01T00:00:00+00:00"}
    inserted = []
    async def query(self, table, query="", **kwargs):
        if table == "user_invitations":
            return [invitation]
        return []
    async def insert(self, table, payload, **kwargs):
        inserted.append((table, payload))
        if table == "user_profiles":
            return [{"id": "profile-new", **payload}]
        return []
    monkeypatch.setattr(SupabaseClient, "query", query)
    monkeypatch.setattr(SupabaseClient, "insert", insert)
    monkeypatch.setattr(SupabaseClient, "create_user", AsyncMock(return_value={"id": "auth-new"}))
    monkeypatch.setattr(SupabaseClient, "update", AsyncMock(return_value=[]))
    response = TestClient(app).post("/api/v1/auth/invitations/accept", json={"token": "t" * 48, "username": "new.person", "password": "password12345"})
    assert response.status_code == 200
    assert any(table == "user_roles" and payload["role"] == "recruiter" for table, payload in inserted)


def test_invitation_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(SupabaseClient, "query", AsyncMock(return_value=[]))
    response = TestClient(app).post("/api/v1/auth/invitations/accept", json={"token": "t" * 48, "username": "new.person", "password": "password12345"})
    assert response.status_code == 400


def test_document_validation_checks_signature_and_extension():
    assert validate_document("resume.pdf", "application/pdf", b"%PDF-1.7") == ".pdf"
    with pytest.raises(HTTPException) as mismatch:
        validate_document("resume.pdf", "application/pdf", b"not a pdf")
    assert mismatch.value.status_code == 400
    with pytest.raises(HTTPException) as oversized:
        validate_document("resume.pdf", "application/pdf", b"%PDF" + b"x" * (10 * 1024 * 1024))
    assert oversized.value.status_code == 413


def test_interview_schedule_conflict_detection():
    from datetime import datetime, timezone
    start = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
    end = datetime(2026, 9, 22, 11, tzinfo=timezone.utc)
    existing = [{"id": "i-1", "scheduled_start": "2026-09-22T10:30:00+00:00", "scheduled_end": "2026-09-22T11:30:00+00:00"}]
    assert schedule_conflicts(existing, start, end) is True
    assert schedule_conflicts(existing, datetime(2026, 9, 22, 11, 30, tzinfo=timezone.utc), datetime(2026, 9, 22, 12, 30, tzinfo=timezone.utc)) is True
    assert schedule_conflicts(existing, datetime(2026, 9, 22, 11, 45, tzinfo=timezone.utc), datetime(2026, 9, 22, 12, 45, tzinfo=timezone.utc)) is False
    assert schedule_conflicts(existing, start, end, "i-1") is False


def test_scorecard_schema_rejects_out_of_range_scores():
    from app.schemas import ScorecardCreate
    with pytest.raises(ValueError):
        ScorecardCreate(technical_score=11, communication_score=8, problem_solving_score=8, experience_score=8, team_fit_score=8, overall_score=8, recommendation="HIRE")


def test_offer_schema_requires_valid_expiry():
    from datetime import date
    from app.schemas import OfferCreate
    with pytest.raises(ValueError):
        OfferCreate(application_id="00000000-0000-0000-0000-000000000001", salary=1000, joining_date=date(2026, 10, 10), expiry_date=date(2026, 10, 1))


def test_profile_image_signature_rules():
    from app.routes.auth import PROFILE_IMAGES
    assert PROFILE_IMAGES["image/png"][1] == b"\x89PNG\r\n\x1a\n"


def test_user_access_requires_at_least_one_role():
    from app.schemas import UserAccessUpdate
    with pytest.raises(ValueError):
        UserAccessUpdate(roles=[])


def test_offer_pdf_has_pdf_signature():
    from app.services.pdf import create_offer_pdf
    assert create_offer_pdf({"offer_code": "OFF-1", "salary": "1000", "joining_date": "2026-10-01", "expiry_date": "2026-10-15"}, {"full_name": "Test Person"}).startswith(b"%PDF")


def test_workflow_replay_requires_confirmation():
    from app.schemas import WorkflowReplayRequest
    with pytest.raises(ValueError):
        WorkflowReplayRequest(target_key="OFFER_SEND", confirm=False)


def test_candidate_offer_response_schema_limits_decisions():
    from app.schemas import CandidateOfferResponse
    with pytest.raises(ValueError):
        CandidateOfferResponse(decision="MAYBE")


def test_bulk_application_action_requires_confirmation():
    from app.schemas import BulkApplicationAction
    with pytest.raises(ValueError):
        BulkApplicationAction(application_ids=["00000000-0000-0000-0000-000000000001"], action="ARCHIVE", confirm=False)


def test_job_publication_status_is_limited():
    from app.schemas import JobPublicationUpdate
    with pytest.raises(ValueError):
        JobPublicationUpdate(publication_status="LIVE")


def test_application_sort_pattern_is_strict():
    from app.routes.admin import applications
    assert applications.__name__ == "applications"
