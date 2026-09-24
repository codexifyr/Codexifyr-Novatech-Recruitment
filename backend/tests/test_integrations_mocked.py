from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.services.ai import AIReviewClient
from app.services.emailer import EmailService
from app.services.n8n import N8nClient
from app.services.supabase import SupabaseClient
from app.services.pdf import create_analytics_pdf
from app.services.google_calendar import GoogleCalendarService


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("mock failure", request=SimpleNamespace(), response=SimpleNamespace())


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = responses
        self.last_request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, *args, **kwargs):
        return self.responses.pop(0)

    async def post(self, *args, **kwargs):
        self.last_request = (args, kwargs)
        return self.responses.pop(0)

    async def patch(self, *args, **kwargs):
        self.last_request = (args, kwargs)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_supabase_rest_query_is_mocked_without_network():
    fake = FakeAsyncClient([FakeResponse([{"id": "1"}])])
    with patch("app.services.supabase.httpx.AsyncClient", return_value=fake):
        result = await SupabaseClient(Settings(supabase_url="https://example.test", supabase_secret_key="secret")).query("jobs", "select=id")
    assert result == [{"id": "1"}]


@pytest.mark.asyncio
async def test_smtp_delivery_is_mocked_without_sending_email():
    service = EmailService(Settings(email_enabled=True, smtp_user="sender@example.com", smtp_password="not-real"))
    service._send = lambda message: setattr(service, "captured", message)
    await service.send_otp("candidate@example.com", "123456", "PASSWORD_RESET")
    assert "123456" in service.captured.get_content()


@pytest.mark.asyncio
async def test_application_received_email_contains_reference_and_position():
    service = EmailService(Settings(email_enabled=True, smtp_user="sender@example.com", smtp_password="not-real"))
    service._send = lambda message: setattr(service, "captured", message)
    sent = await service.send_application_received("candidate@example.com", "Test Candidate", "Python Engineer", "APP-TEST-001")
    assert sent is True
    assert "APP-TEST-001" in service.captured.get_body(preferencelist=("plain",)).get_content()
    assert "Python Engineer" in service.captured["Subject"]


@pytest.mark.asyncio
async def test_interview_email_contains_confirm_reschedule_and_meet_actions():
    service = EmailService(Settings(email_enabled=True, smtp_user="sender@example.com", smtp_password="not-real", frontend_url="http://localhost:3000"))
    service._send = lambda message: setattr(service, "captured", message)
    await service.send_interview_schedule(
        email="candidate@example.com",
        name="Test Candidate",
        position="Python Engineer",
        interviewer="Hamza Ali",
        start="1 January 2099, 10:00 PKT",
        end="1 January 2099, 11:00 PKT",
        meet_url="https://meet.google.com/abc-defg-hij",
        interview_code="INT-TEST",
        confirmation_token="x" * 40,
    )
    html = service.captured.get_body(preferencelist=("html",)).get_content()
    assert "Confirm interview" in html
    assert "Request another time" in html
    assert "Join Google Meet" in html


@pytest.mark.asyncio
async def test_n8n_trigger_is_mocked_and_normalized():
    fake = FakeAsyncClient([FakeResponse({"success": True, "execution_id": "exec-1"})])
    settings = Settings(n8n_webhook_base_url="https://n8n.example", n8n_webhook_secret="secret")
    with patch("app.services.n8n.httpx.AsyncClient", return_value=fake):
        result = await N8nClient(settings).trigger("webhook/test", {"correlation_id": "corr-1"})
    assert result["execution_id"] == "exec-1"
    headers = fake.last_request[1]["headers"]
    assert headers["X-Webhook-Timestamp"]
    assert len(headers["X-Webhook-Signature"]) == 64


@pytest.mark.asyncio
async def test_gemini_primary_and_groq_fallback_are_mocked():
    settings = Settings(gemini_api_key="gemini", groq_api_key="groq")
    fake_gemini = FakeAsyncClient([FakeResponse({"candidates": [{"content": {"parts": [{"text": "gemini result"}]}}]})])
    with patch("app.services.ai.httpx.AsyncClient", return_value=fake_gemini):
        result = await AIReviewClient(settings).review("review candidate")
    assert result == {"provider": "gemini", "text": "gemini result"}
    fake_fallback = FakeAsyncClient([FakeResponse({}, 500), FakeResponse({"choices": [{"message": {"content": "groq result"}}]})])
    with patch("app.services.ai.httpx.AsyncClient", return_value=fake_fallback):
        result = await AIReviewClient(settings).review("review candidate")
    assert result == {"provider": "groq", "text": "groq result"}


def test_analytics_pdf_has_pdf_signature():
    assert create_analytics_pdf({"applications_total": 2, "interviews_total": 1, "offers_total": 1, "by_status": {"SHORTLISTED": 2}}).startswith(b"%PDF")


@pytest.mark.asyncio
async def test_google_calendar_creates_unique_meet_with_attendees():
    token = FakeResponse({"access_token": "mock-access"})
    event = FakeResponse({"id": "event-1", "htmlLink": "https://calendar.example/event", "hangoutLink": "https://meet.google.com/abc-defg-hij", "conferenceData": {"conferenceId": "abc-defg-hij"}})
    fake = FakeAsyncClient([token, event])
    settings = Settings(google_calendar_client_id="client", google_calendar_client_secret="secret", google_calendar_refresh_token="refresh")
    with patch("app.services.google_calendar.httpx.AsyncClient", return_value=fake):
        result = await GoogleCalendarService(settings).create_interview(summary="Interview", description="Test", start="2099-01-01T10:00:00+00:00", end="2099-01-01T11:00:00+00:00", timezone_name="UTC", attendees=["candidate@example.com", "interviewer@example.com"])
    assert result["meeting_code"] == "abc-defg-hij"
    assert result["meet_url"].startswith("https://meet.google.com/")
    args, kwargs = fake.last_request
    assert "conferenceDataVersion=1" in args[0]
    assert kwargs["json"]["conferenceData"]["createRequest"]["requestId"]
    assert len(kwargs["json"]["attendees"]) == 2


@pytest.mark.asyncio
async def test_google_calendar_reschedule_updates_existing_event_and_meet():
    token = FakeResponse({"access_token": "mock-access"})
    event = FakeResponse({"id": "event-1", "htmlLink": "https://calendar.example/event", "hangoutLink": "https://meet.google.com/abc-defg-hij", "conferenceData": {"conferenceId": "abc-defg-hij"}})
    fake = FakeAsyncClient([token, event])
    settings = Settings(google_calendar_client_id="client", google_calendar_client_secret="secret", google_calendar_refresh_token="refresh")
    with patch("app.services.google_calendar.httpx.AsyncClient", return_value=fake):
        result = await GoogleCalendarService(settings).schedule_interview(event_id="event-1", summary="Interview", description="Rescheduled", start="2099-01-02T10:00:00+00:00", end="2099-01-02T11:00:00+00:00", timezone_name="UTC", attendees=["candidate@example.com", "interviewer@example.com"])
    assert result["event_id"] == "event-1"
    args, kwargs = fake.last_request
    assert "/events/event-1" in args[0]
    assert "conferenceData" not in kwargs["json"]
