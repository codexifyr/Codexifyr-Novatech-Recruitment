from __future__ import annotations

import secrets
from urllib.parse import quote
import httpx
from fastapi import HTTPException
from app.config import Settings


class GoogleCalendarService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _access_token(self) -> str:
        if not self.settings.google_calendar_ready:
            raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.settings.google_calendar_client_id,
                "client_secret": self.settings.google_calendar_client_secret,
                "refresh_token": self.settings.google_calendar_refresh_token,
                "grant_type": "refresh_token",
            })
        if response.status_code >= 400 or not response.json().get("access_token"):
            raise HTTPException(status_code=502, detail="Google Calendar authentication failed")
        return response.json()["access_token"]

    async def schedule_interview(self, *, event_id: str | None = None, summary: str, description: str, start: str, end: str, timezone_name: str, attendees: list[str]) -> dict:
        token = await self._access_token()
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": timezone_name},
            "end": {"dateTime": end, "timeZone": timezone_name},
            "attendees": [{"email": email} for email in dict.fromkeys(attendees) if email],
        }
        if not event_id:
            body["conferenceData"] = {"createRequest": {"requestId": secrets.token_urlsafe(18), "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
        calendar_id = quote(self.settings.google_calendar_id, safe="")
        async with httpx.AsyncClient(timeout=25) as client:
            url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            response = await client.patch(f"{url}/{quote(event_id, safe='')}?conferenceDataVersion=1&sendUpdates=all", headers=headers, json=body) if event_id else await client.post(f"{url}?conferenceDataVersion=1&sendUpdates=all", headers=headers, json=body)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Google Calendar could not create the interview event")
        event = response.json()
        meet_url = event.get("hangoutLink")
        if not meet_url:
            for entry in (event.get("conferenceData") or {}).get("entryPoints", []):
                if entry.get("entryPointType") == "video":
                    meet_url = entry.get("uri")
                    break
        if not meet_url:
            raise HTTPException(status_code=502, detail="Google Calendar created an event without a Meet link")
        return {"event_id": event.get("id"), "event_url": event.get("htmlLink"), "meet_url": meet_url, "meeting_code": (event.get("conferenceData") or {}).get("conferenceId")}

    async def create_interview(self, **kwargs) -> dict:
        return await self.schedule_interview(**kwargs)
