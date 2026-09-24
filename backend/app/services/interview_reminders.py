from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Settings
from app.services.emailer import EmailService
from app.services.supabase import SupabaseClient


REMINDER_SELECT = "id,interview_code,status,confirmation_token,scheduled_start,scheduled_end,schedule_timezone,meeting_url,interviewer_id,applications(candidate_id,name_at_application,email_at_application,job_positions(title)),user_profiles!interviews_interviewer_id_fkey(full_name,email)"


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def _deliver_reminder(db: SupabaseClient, emailer: EmailService, item: dict, claim_field: str, now: datetime, *, already_claimed: bool = False) -> None:
    if not already_claimed:
        claimed = await db.update("interviews", f"id=eq.{item['id']}&{claim_field}=is.null", {claim_field: now.isoformat()})
        if not claimed:
            return
    application = item.get("applications") or {}
    interviewer = item.get("user_profiles") or {}
    position = (application.get("job_positions") or {}).get("title", "Role")
    zone = _zone(item.get("schedule_timezone"))
    start_label = datetime.fromisoformat(item["scheduled_start"].replace("Z", "+00:00")).astimezone(zone).strftime("%A, %d %B %Y at %I:%M %p %Z")
    end_label = datetime.fromisoformat(item["scheduled_end"].replace("Z", "+00:00")).astimezone(zone).strftime("%A, %d %B %Y at %I:%M %p %Z")
    delivery = await asyncio.gather(
        emailer.send_interview_schedule(email=application.get("email_at_application", ""), name=application.get("name_at_application", "Candidate"), position=position, interviewer=interviewer.get("full_name", "NovaTech interviewer"), start=start_label, end=end_label, meet_url=item.get("meeting_url", ""), interview_code=item["interview_code"], confirmation_token=item.get("confirmation_token") if item.get("status") == "PENDING_CONFIRMATION" else None, reminder=True),
        emailer.send_interview_schedule(email=interviewer.get("email", ""), name=interviewer.get("full_name", "Interviewer"), position=position, interviewer=interviewer.get("full_name", "Interviewer"), start=start_label, end=end_label, meet_url=item.get("meeting_url", ""), interview_code=item["interview_code"], reminder=True),
        return_exceptions=True,
    )
    if any(isinstance(result, Exception) for result in delivery):
        await db.update("interviews", f"id=eq.{item['id']}", {claim_field: None})


async def process_interview_reminders(settings: Settings) -> None:
    db = SupabaseClient(settings)
    now = datetime.now(timezone.utc)
    emailer = EmailService(settings)
    day_start = now + timedelta(minutes=settings.interview_reminder_minutes + 1)
    day_end = now + timedelta(hours=settings.interview_day_reminder_hours)
    day_rows = await db.query("interviews", f"status=not.in.(CANCELLED,COMPLETED,NO_SHOW)&scheduled_start=gte.{day_start.isoformat().replace('+00:00','Z')}&scheduled_start=lte.{day_end.isoformat().replace('+00:00','Z')}&day_reminder_sent_at=is.null&select={REMINDER_SELECT}")
    for item in day_rows:
        await _deliver_reminder(db, emailer, item, "day_reminder_sent_at", now)
    reminder_until = now + timedelta(minutes=settings.interview_reminder_minutes)
    rows = await db.query("interviews", f"status=not.in.(CANCELLED,COMPLETED,NO_SHOW)&scheduled_start=gte.{now.isoformat().replace('+00:00','Z')}&scheduled_start=lte.{reminder_until.isoformat().replace('+00:00','Z')}&reminder_sent_at=is.null&select={REMINDER_SELECT}")
    for item in rows:
        await _deliver_reminder(db, emailer, item, "reminder_sent_at", now)
    due = await db.query("interviews", f"status=not.in.(CANCELLED,COMPLETED,NO_SHOW)&scheduled_start=lte.{now.isoformat().replace('+00:00','Z')}&scheduled_end=gte.{now.isoformat().replace('+00:00','Z')}&start_alert_sent_at=is.null&select={REMINDER_SELECT}")
    admins = await db.query("user_profiles", "active=eq.true&role=eq.admin&select=id") if due else []
    for item in due:
        claimed = await db.update("interviews", f"id=eq.{item['id']}&start_alert_sent_at=is.null", {"start_alert_sent_at": now.isoformat()})
        if not claimed:
            continue
        application = item.get("applications") or {}
        candidate = application.get("name_at_application", "Candidate")
        for profile_id in [item.get("interviewer_id"), *[row["id"] for row in admins]]:
            if profile_id:
                await db.insert("notifications", {"user_profile_id": profile_id, "title": "Interview starting now", "message": f"{candidate} - {item['interview_code']}", "category": "INTERVIEW_DUE", "action_url": f"/dashboard/interviews/{item['id']}"})
        candidate_profiles = await db.query("user_profiles", f"candidate_id=eq.{application.get('candidate_id')}&active=eq.true&select=id") if application.get("candidate_id") else []
        for profile in candidate_profiles:
            await db.insert("notifications", {"user_profile_id": profile["id"], "title": "Your interview is starting now", "message": item["interview_code"], "category": "INTERVIEW_DUE", "action_url": "/portal"})
        await _deliver_reminder(db, emailer, item, "start_alert_sent_at", now, already_claimed=True)


async def reminder_loop(settings: Settings) -> None:
    while True:
        try:
            if settings.supabase_ready:
                await process_interview_reminders(settings)
        except Exception:
            pass
        await asyncio.sleep(30)
