from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import secrets

from app.config import Settings
from app.services.emailer import EmailService
from app.services.supabase import SupabaseClient


INTERVIEWER_ROLES = {"interviewer", "hiring_manager", "hr"}


def interviewer_priority(profile: dict, job_department: str) -> tuple[int, int, str]:
    """Rank eligible interviewers without ever considering an administrator."""
    role = str(profile.get("role") or "").lower()
    department = str(profile.get("department") or "").strip().casefold()
    target = str(job_department or "").strip().casefold()
    if role == "interviewer" and department == target:
        role_priority = 0
    elif role == "hiring_manager" and department == target:
        role_priority = 1
    elif role == "hr":
        role_priority = 2
    else:
        role_priority = 99
    return role_priority, int(profile.get("active_workload") or 0), str(profile.get("id") or "")


def interviewer_is_eligible(profile: dict, job_department: str) -> bool:
    return interviewer_priority(profile, job_department)[0] < 99


async def select_interviewer(
    db: SupabaseClient,
    application_id: str,
    *,
    excluded_ids: set[str] | None = None,
) -> tuple[dict | None, str]:
    excluded_ids = excluded_ids or set()
    applications = await db.query(
        "applications",
        f"id=eq.{application_id}&select=job_positions(department)",
    )
    job_department = ((applications[0].get("job_positions") or {}).get("department") if applications else "") or ""
    profiles = await db.query(
        "user_profiles",
        "active=eq.true&role=in.(interviewer,hiring_manager,hr)&select=id,full_name,email,role,department,job_title,created_at",
    )
    profiles = [
        profile for profile in profiles
        if str(profile.get("id")) not in excluded_ids and interviewer_is_eligible(profile, job_department)
    ]
    if not profiles:
        return None, job_department

    ids = ",".join(str(profile["id"]) for profile in profiles)
    availability = await db.query(
        "interviewer_profiles",
        f"user_profile_id=in.({ids})&select=user_profile_id,available",
    )
    unavailable = {str(row["user_profile_id"]) for row in availability if row.get("available") is False}
    profiles = [profile for profile in profiles if str(profile["id"]) not in unavailable]
    if not profiles:
        return None, job_department

    active = await db.query(
        "interviews",
        f"interviewer_id=in.({ids})&status=not.in.(CANCELLED,COMPLETED)&select=interviewer_id",
    )
    workloads = Counter(str(row.get("interviewer_id")) for row in active if row.get("interviewer_id"))
    for profile in profiles:
        profile["active_workload"] = workloads[str(profile["id"])]
    profiles.sort(key=lambda profile: interviewer_priority(profile, job_department))
    return profiles[0], job_department


async def _notify_assignment_managers(db: SupabaseClient, interview_id: str, title: str, message: str) -> None:
    managers = await db.query(
        "user_profiles",
        "active=eq.true&role=in.(admin,hr,hiring_manager)&select=id",
    )
    for manager in managers:
        await db.insert("notifications", {
            "user_profile_id": manager["id"],
            "title": title,
            "message": message,
            "category": "INTERVIEW",
            "action_url": f"/dashboard/interviews/{interview_id}",
        })


async def propose_interviewer(
    db: SupabaseClient,
    interview: dict,
    application_id: str,
    *,
    excluded_ids: set[str] | None = None,
) -> dict:
    selected, department = await select_interviewer(db, application_id, excluded_ids=excluded_ids)
    now = datetime.now(timezone.utc).isoformat()
    await db.update(
        "interview_assignments",
        f"interview_id=eq.{interview['id']}&status=in.(PENDING_APPROVAL,APPROVED,ACCEPTED)",
        {"status": "REPLACED", "responded_at": now},
    )
    if not selected:
        changes = {
            "interviewer_id": None,
            "assignment_status": "PENDING_APPROVAL",
            "assignment_reason": f"No available interviewer, hiring manager or HR reviewer for {department or 'the job department'}.",
            "assignment_score": None,
        }
        rows = await db.update("interviews", f"id=eq.{interview['id']}", changes)
        await _notify_assignment_managers(
            db,
            interview["id"],
            "Manual interview assignment required",
            f"No eligible staff member is currently available for {department or 'this department'}.",
        )
        return rows[0] if rows else interview | changes

    role = str(selected.get("role") or "").lower()
    same_department = str(selected.get("department") or "").strip().casefold() == department.strip().casefold()
    score = 95 if role == "interviewer" and same_department else 90 if role == "hiring_manager" and same_department else 80
    reason = (
        f"Automatically suggested {role.replace('_', ' ')} for {department or 'the role'} "
        f"using department fit, availability and active workload."
    )
    changes = {
        "interviewer_id": selected["id"],
        "assignment_status": "PENDING_APPROVAL",
        "assignment_reason": reason,
        "assignment_score": score,
        "assignment_approved_by": None,
        "assignment_approved_at": None,
    }
    rows = await db.update("interviews", f"id=eq.{interview['id']}", changes)
    existing = await db.query(
        "interview_assignments",
        f"interview_id=eq.{interview['id']}&interviewer_id=eq.{selected['id']}&select=id",
    )
    assignment = {
        "interview_id": interview["id"],
        "interviewer_id": selected["id"],
        "assignment_role": "LEAD",
        "status": "PENDING_APPROVAL",
        "auto_suggested": True,
        "match_score": score,
        "match_reason": reason,
        "approved_by": None,
        "approved_at": None,
        "responded_at": None,
    }
    if existing:
        await db.update("interview_assignments", f"id=eq.{existing[0]['id']}", assignment)
    else:
        await db.insert("interview_assignments", assignment)
    await db.insert("notifications", {
        "user_profile_id": selected["id"],
        "title": "Interview assignment proposed",
        "message": "A department-matched interview is awaiting HR or hiring-manager approval.",
        "category": "INTERVIEW",
        "action_url": f"/dashboard/interviews/{interview['id']}",
    })
    await _notify_assignment_managers(
        db,
        interview["id"],
        "Interview assignment awaiting approval",
        f"{selected.get('full_name', 'A staff member')} was suggested for {department or 'this role'}.",
    )
    return rows[0] if rows else interview | changes


async def ensure_interview(db: SupabaseClient, application_id: str, actor_id: str | None = None) -> dict:
    existing = await db.query("interviews", f"application_id=eq.{application_id}&select=*&order=created_at.desc&limit=1")
    if existing:
        return existing[0]
    interview = (await db.insert("interviews", {
        "interview_code": f"INT-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}",
        "application_id": application_id,
        "status": "PENDING_CONFIRMATION",
        "assignment_status": "PENDING_APPROVAL",
        "interview_type": "Technical",
        "round_number": 1,
        "confirmation_token": secrets.token_urlsafe(32),
    }))[0]
    interview = await propose_interviewer(db, interview, application_id)
    if actor_id:
        await db.insert("audit_logs", {
            "actor_id": actor_id,
            "action": "INTERVIEW_CREATED",
            "entity_type": "APPLICATION",
            "entity_id": application_id,
            "new_data": {"interview_id": interview["id"], "automatic": True},
        })
    return interview


async def reassign_declined_interview(db: SupabaseClient, interview_id: str, declined_user_id: str) -> dict:
    rows = await db.query("interviews", f"id=eq.{interview_id}&select=*,applications(id)")
    if not rows:
        return {}
    interview = rows[0]
    application = interview.get("applications") or {}
    return await propose_interviewer(
        db,
        interview,
        str(application.get("id") or interview.get("application_id")),
        excluded_ids={str(declined_user_id)},
    )


async def ensure_candidate_portal_invite(db: SupabaseClient, settings: Settings, application_id: str) -> None:
    # Account creation is intentionally deferred until a formal offer is accepted.
    # Calls remain as compatibility hooks for existing workflows, but do not create
    # a profile or send registration email during shortlist/interview stages.
    return None
