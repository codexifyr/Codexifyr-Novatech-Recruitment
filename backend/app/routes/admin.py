from datetime import date, datetime, timedelta, timezone
import hashlib
import secrets
import asyncio
from zoneinfo import ZoneInfo
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from app.config import Settings, get_settings
from app.schemas import ApiMessage, AvailabilityCreate, DocumentVerificationUpdate, EmployeeCreate, HiringDecisionCreate, HiringTeamAssignment, InterviewerResponse, InternalNoteCreate, InterviewAssignmentUpdate, InterviewScheduleCreate, JobCreate, JobPublicationUpdate, OfferCreate, OfferDecision, OfferStatusUpdate, OnboardingTaskUpdate, RequisitionCreate, RequisitionDecision, ScorecardCreate, StaffInvitationCreate, StaffUserCreate, UserAccessUpdate
from app.security import require_permissions, require_roles
from app.services.emailer import EmailService
from app.services.n8n import N8nClient
from app.services.pdf import create_offer_pdf
from app.services.supabase import SupabaseClient
from app.services.cv_security import scan_cv
from app.services.cv_review import review_cv
from app.services.recruitment import ensure_candidate_portal_invite, ensure_interview, interviewer_is_eligible, reassign_declined_interview
from app.services.google_calendar import GoogleCalendarService

router = APIRouter(prefix="/admin", tags=["staff"])
staff = require_roles("admin", "operator", "hiring_manager", "interviewer", "hr", "recruiter")
managers = require_roles("admin", "operator", "hiring_manager", "hr", "recruiter")
assignment_managers = require_roles("admin", "hiring_manager", "hr")
admins = require_roles("admin")
user_managers = require_permissions("users.manage")
interview_conductors = require_permissions("interviews.conduct")


REASSIGNABLE_INTERVIEW_ROLES = {"interviewer", "hiring_manager", "hr"}


def schedule_conflicts(existing: list[dict], scheduled_start, scheduled_end, interview_id: str | None = None) -> bool:
    if scheduled_start is None or scheduled_end is None:
        return False
    for item in existing:
        if interview_id and str(item.get("id")) == interview_id:
            continue
        if not item.get("scheduled_start") or not item.get("scheduled_end"):
            continue
        start = datetime.fromisoformat(item["scheduled_start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(item["scheduled_end"].replace("Z", "+00:00"))
        buffer = timedelta(minutes=15)
        if scheduled_start - buffer < end and scheduled_end + buffer > start:
            return True
    return False


def _is_pure_interviewer(user: dict) -> bool:
    roles = set(user.get("roles", set()))
    return "interviewer" in roles and not roles.intersection({"admin", "operator", "hiring_manager", "hr", "recruiter"})


async def _require_application_access(application_id: str, user: dict, db: SupabaseClient) -> None:
    if not _is_pure_interviewer(user):
        return
    rows = await db.query(
        "interviews",
        f"application_id=eq.{quote(application_id)}&interviewer_id=eq.{user['profile']['id']}&select=id&limit=1",
    )
    if not rows:
        raise HTTPException(status_code=403, detail="You are not assigned to this candidate")

@router.get("/me")
async def me(user: dict = Depends(staff)):
    return {"success": True, "user": user["profile"]}


@router.get("/dashboard")
async def dashboard(user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    if _is_pure_interviewer(user):
        assigned = await SupabaseClient(settings).query("interviews", f"interviewer_id=eq.{user['profile']['id']}&assignment_status=eq.APPROVED&select=id,status,scheduled_start")
        now = datetime.now(timezone.utc)
        return {"success": True, "metrics": {"assigned_interviews": len(assigned), "upcoming_interviews": sum(bool(item.get("scheduled_start") and datetime.fromisoformat(item["scheduled_start"].replace("Z", "+00:00")) >= now) for item in assigned), "pending_scorecards": sum(item.get("status") not in {"COMPLETED", "CANCELLED"} for item in assigned)}}
    rows = await SupabaseClient(settings).query("operational_dashboard_metrics", "select=*", token=user["access_token"])
    return {"success": True, "metrics": rows[0] if rows else {}}


@router.get("/applications")
async def applications(user: dict = Depends(staff), settings: Settings = Depends(get_settings), search: str = Query(default="", max_length=100), status: str | None = Query(default=None, max_length=40), page: int = Query(default=1, ge=1, le=10000), page_size: int = Query(default=50, ge=1, le=100), sort: str = Query(default="created_at.desc", pattern=r"^(created_at|final_score|name_at_application)\.(asc|desc)$")):
    filters = []
    db = SupabaseClient(settings)
    if _is_pure_interviewer(user):
        assigned = await db.query("interviews", f"interviewer_id=eq.{user['profile']['id']}&select=application_id")
        application_ids = sorted({str(row["application_id"]) for row in assigned if row.get("application_id")})
        if not application_ids:
            return {"success": True, "items": [], "page": page, "page_size": page_size, "has_more": False}
        filters.append(f"id=in.({','.join(application_ids)})")
    if search.strip():
        clean = quote(search.strip(), safe="-_.@")
        filters.append(f"or=(name_at_application.ilike.*{clean}*,application_code.ilike.*{clean}*,email_at_application.ilike.*{clean}*)")
    if status:
        filters.append(f"status=eq.{quote(status, safe='_')}")
    offset = (page - 1) * page_size
    query = "select=id,application_code,name_at_application,email_at_application,experience_years,status,final_score,created_at,job_positions(title,department)&" + "&".join(filters + [f"order={sort}", f"limit={page_size}", f"offset={offset}"])
    items = await db.query("applications", query)
    return {"success": True, "items": items, "page": page, "page_size": page_size, "has_more": len(items) == page_size}


@router.get("/applications/{application_id}")
async def application_detail(application_id: str, user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    await _require_application_access(application_id, user, db)
    query = "select=*,job_positions(*),candidates(*),interviews(*,interview_assignments(*,user_profiles!interview_assignments_interviewer_id_fkey(*))),offers(*)&id=eq." + quote(application_id)
    rows = await db.query("applications", query, token=user["access_token"])
    if not rows:
        raise HTTPException(status_code=404, detail="Application not found")
    history, notes, decisions, scorecards = await asyncio.gather(
        db.query("candidate_status_history", f"application_id=eq.{application_id}&select=*&order=changed_at.desc", token=user["access_token"]),
        db.query("internal_notes", f"entity_type=eq.APPLICATION&entity_id=eq.{application_id}&select=*&order=created_at.desc"),
        db.query("hiring_decisions", f"application_id=eq.{application_id}&select=*&limit=1"),
        db.query("interview_scorecards", f"interview_id=in.({','.join(str(i['id']) for i in rows[0].get('interviews', []) if i.get('id'))})&select=*,user_profiles!interview_scorecards_interviewer_id_fkey(full_name,job_title)&order=submitted_at.desc") if rows[0].get("interviews") else asyncio.sleep(0, result=[]),
    )
    return {"success": True, "item": rows[0], "history": history, "notes": notes, "hiring_decision": decisions[0] if decisions else None, "scorecards": scorecards}


@router.get("/applications/{application_id}/cv")
async def application_cv(application_id: str, user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    await _require_application_access(application_id, user, db)
    rows = await db.query("applications", f"id=eq.{quote(application_id)}&select=cv_storage_path,cv_original_filename,cv_mime_type")
    if not rows or not rows[0].get("cv_storage_path"):
        raise HTTPException(status_code=404, detail="CV is not available")
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "APPLICATION_CV_ACCESSED", "entity_type": "APPLICATION", "entity_id": application_id})
    return {"success": True, "url": await db.signed_object_url("candidate-documents", rows[0]["cv_storage_path"], 300), "filename": rows[0].get("cv_original_filename") or "candidate-cv", "mime_type": rows[0].get("cv_mime_type"), "expires_in": 300}


@router.post("/applications/{application_id}/review", response_model=ApiMessage)
async def rerun_application_review(application_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.query("applications", f"id=eq.{quote(application_id)}&select=*,job_positions(title,requirements,department)")
    if not rows:
        raise HTTPException(status_code=404, detail="Application not found")
    application = rows[0]
    path = application.get("cv_storage_path")
    if not path:
        raise HTTPException(status_code=409, detail="A stored CV is required before review")
    mime = application.get("cv_mime_type") or ("application/pdf" if path.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    security = scan_cv(await db.download_object("candidate-documents", path), mime)
    job = application.get("job_positions") or {}
    review = review_cv(text=security.safe_text, title=job.get("title", ""), requirements=job.get("requirements"), submitted_skills=application.get("skills") or [], submitted_experience=float(application.get("experience_years") or 0), security_status=security.status, security_flags=list(security.flags))
    previous = application.get("status")
    changes = {"rule_score": review["score"], "final_score": review["score"], "ai_review": review, "status": review["decision"], "status_reason": review["ai_recommendation"], "cv_security_status": security.status, "cv_security_flags": list(security.flags), "reviewed_at": datetime.now(timezone.utc).isoformat(), "review_version": review["review_version"]}
    updated = await db.update("applications", f"id=eq.{quote(application_id)}", changes)
    await db.insert("cv_security_assessments", {"application_id": application_id, "file_sha256": security.sha256, "mime_type": mime, "status": security.status, "flags": list(security.flags), "extracted_characters": security.extracted_characters, "scanner_version": "1.0.0"})
    if previous != review["decision"]:
        await db.insert("candidate_status_history", {"application_id": application_id, "previous_status": previous, "new_status": review["decision"], "reason": review["ai_recommendation"], "workflow_name": "CODE_CV_EVIDENCE_REVIEW", "workflow_version": review["review_version"], "changed_by": user["profile"]["id"], "correlation_id": application["correlation_id"]})
    interview = await ensure_interview(db, application_id, user["profile"]["id"]) if review["decision"] == "SHORTLISTED" else None
    if review["decision"] == "SHORTLISTED":
        await ensure_candidate_portal_invite(db, settings, application_id)
    if previous != review["decision"]:
        await EmailService(settings).send_application_status(application["email_at_application"], application["name_at_application"], job.get("title", "the role"), review["decision"])
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "APPLICATION_CV_REVIEWED", "entity_type": "APPLICATION", "entity_id": application_id, "new_data": {"score": review["score"], "decision": review["decision"]}})
    return ApiMessage(message="CV review completed", data={"application": updated[0] if updated else changes, "interview": interview})


@router.post("/applications/{application_id}/interview", response_model=ApiMessage)
async def create_application_interview(application_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    if not await db.query("applications", f"id=eq.{quote(application_id)}&select=id"):
        raise HTTPException(status_code=404, detail="Application not found")
    interview = await ensure_interview(db, application_id, user["profile"]["id"])
    return ApiMessage(message="Interview is ready for assignment approval", data=interview)


@router.post("/applications/{application_id}/notes", response_model=ApiMessage)
async def add_application_note(application_id: str, payload: InternalNoteCreate, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).insert("internal_notes", {"entity_type": "APPLICATION", "entity_id": application_id, "note": payload.note, "visibility": payload.visibility, "created_by": user["profile"]["id"]})
    return ApiMessage(message="Internal note added", data=rows[0])


@router.get("/upcoming-meetings")
async def upcoming_meetings(
    user: dict = Depends(staff),
    settings: Settings = Depends(get_settings),
    days: int = Query(default=30, ge=1, le=90),
):
    """Return all company meetings for admins and only assigned meetings for other staff."""
    db = SupabaseClient(settings)
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days)
    now_value = now.isoformat().replace("+00:00", "Z")
    until_value = until.isoformat().replace("+00:00", "Z")
    filters = [
        "scheduled_start=not.is.null",
        "scheduled_end=not.is.null",
        f"scheduled_end=gte.{now_value}",
        f"scheduled_start=lte.{until_value}",
        "status=not.in.(CANCELLED,COMPLETED,NO_SHOW)",
        "assignment_status=eq.APPROVED",
    ]
    roles = set(user.get("roles", set()))
    is_admin = "admin" in roles
    if not is_admin:
        filters.append(f"interviewer_id=eq.{quote(str(user['profile']['id']), safe='-')}")
    query = (
        "select=id,interview_code,status,assignment_status,interview_type,round_number,"
        "scheduled_start,scheduled_end,schedule_timezone,meeting_url,meeting_code,"
        "google_event_id,google_event_url,interviewer_id,reschedule_requested_at,"
        "reschedule_requested_start,reschedule_decision_status,"
        "applications(id,application_code,name_at_application,email_at_application,"
        "job_positions(title,department)),"
        "user_profiles!interviews_interviewer_id_fkey("
        "id,full_name,email,role,department,job_title,timezone)&"
        + "&".join(filters)
        + "&order=scheduled_start.asc&limit=250"
    )
    meetings = await db.query("interviews", query)
    items = []
    for meeting in meetings:
        start_value = meeting.get("scheduled_start")
        end_value = meeting.get("scheduled_end")
        start_time = datetime.fromisoformat(str(start_value).replace("Z", "+00:00")) if start_value else None
        end_time = datetime.fromisoformat(str(end_value).replace("Z", "+00:00")) if end_value else None
        starts_in_minutes = int((start_time - now).total_seconds() // 60) if start_time else None
        join_available = bool(start_time and end_time and start_time - timedelta(minutes=15) <= now <= end_time)
        meeting_in_progress = bool(start_time and end_time and start_time <= now <= end_time)
        application = meeting.get("applications") or {}
        position = application.get("job_positions") or {}
        interviewer = meeting.get("user_profiles") or {}
        items.append({
            **meeting,
            "starts_in_minutes": starts_in_minutes,
            "join_available": join_available,
            "meeting_in_progress": meeting_in_progress,
            "candidate_name": application.get("name_at_application"),
            "candidate_email": application.get("email_at_application"),
            "position_title": position.get("title"),
            "position_department": position.get("department"),
            "interviewer_name": interviewer.get("full_name"),
            "interviewer_email": interviewer.get("email"),
            "interviewer_job_title": interviewer.get("job_title"),
            "reschedule_pending": bool(
                meeting.get("reschedule_requested_at")
                and not meeting.get("reschedule_decision_status")
            ),
        })
    return {
        "success": True,
        "items": items,
        "scope": "ALL_STAFF" if is_admin else "MY_MEETINGS",
        "generated_at": now.isoformat(),
        "range_days": days,
    }


@router.get("/interviews")
async def interviews(user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    filters = []
    if _is_pure_interviewer(user):
        filters.append(f"interviewer_id=eq.{user['profile']['id']}")
        filters.append("assignment_status=eq.APPROVED")
    query = "select=id,interview_code,status,assignment_status,interview_type,round_number,scheduled_start,scheduled_end,meeting_url,meeting_code,google_event_url,interviewer_id,applications(id,application_code,name_at_application,job_positions(title,department)),user_profiles!interviews_interviewer_id_fkey(id,full_name,email,role,department,job_title)&" + "&".join(filters + ["order=created_at.desc", "limit=100"])
    return {"success": True, "items": await SupabaseClient(settings).query("interviews", query)}


@router.get("/interviews/{interview_id}/workspace")
async def interview_workspace(interview_id: str, user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    if "interviewer" in user.get("roles", set()) and not set(user.get("roles", set())).intersection({"admin", "operator", "hiring_manager", "hr", "recruiter"}):
        await _assigned_interview(interview_id, user, db)
    rows = await db.query("interviews", f"id=eq.{quote(interview_id)}&select=*,applications(*,job_positions(*),candidates(*)),user_profiles!interviews_interviewer_id_fkey(id,full_name,email,job_title,department)")
    if not rows:
        raise HTTPException(status_code=404, detail="Interview not found")
    item = rows[0]
    application = item.get("applications") or {}
    if application.get("cv_storage_path"):
        application["cv_download"] = await db.signed_object_url("candidate-documents", application["cv_storage_path"], 300)
    return {"success": True, "item": item}


async def _assigned_interview(interview_id: str, user: dict, db: SupabaseClient) -> dict:
    interviews = await db.query("interviews", f"id=eq.{interview_id}&select=id,interviewer_id,assignment_status")
    if not interviews:
        raise HTTPException(status_code=404, detail="Interview not found")
    if interviews[0].get("interviewer_id") == user["profile"]["id"] and interviews[0].get("assignment_status") == "APPROVED":
        return interviews[0]
    assignments = await db.query("interview_assignments", f"interview_id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}&status=in.(APPROVED,ACCEPTED)&select=id")
    if not assignments:
        raise HTTPException(status_code=403, detail="You are not assigned to this interview")
    return interviews[0]


@router.get("/interviews/{interview_id}/scorecard")
async def get_scorecard(interview_id: str, user: dict = Depends(interview_conductors), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    await _assigned_interview(interview_id, user, db)
    rows = await db.query("interview_scorecards", f"interview_id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}&select=*")
    return {"success": True, "item": rows[0] if rows else None}


@router.post("/interviews/{interview_id}/scorecard", response_model=ApiMessage)
async def submit_scorecard(interview_id: str, payload: ScorecardCreate, user: dict = Depends(interview_conductors), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    await _assigned_interview(interview_id, user, db)
    data = payload.model_dump() | {"interview_id": interview_id, "interviewer_id": user["profile"]["id"], "criteria": {"technical": payload.technical_score, "communication": payload.communication_score, "problem_solving": payload.problem_solving_score, "experience": payload.experience_score, "team_fit": payload.team_fit_score}, "submitted_at": datetime.now(timezone.utc).isoformat()}
    existing = await db.query("interview_scorecards", f"interview_id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}&select=id")
    rows = await db.update("interview_scorecards", f"id=eq.{existing[0]['id']}", data) if existing else await db.insert("interview_scorecards", data)
    interview_rows = await db.query("interviews", f"id=eq.{interview_id}&select=application_id")
    await db.update("interviews", f"id=eq.{interview_id}", {"status": "COMPLETED"})
    if interview_rows:
        application_id = interview_rows[0]["application_id"]
        await db.update("applications", f"id=eq.{application_id}", {"status": "INTERVIEWED", "status_reason": "Interview scorecard submitted; awaiting human hiring decision"})
        existing_decision = await db.query("hiring_decisions", f"application_id=eq.{application_id}&select=id")
        decision_data = {"application_id": application_id, "interview_id": interview_id, "status": "PENDING_MANAGER", "manager_status": "PENDING", "hr_status": "PENDING", "updated_at": datetime.now(timezone.utc).isoformat()}
        if existing_decision:
            await db.update("hiring_decisions", f"id=eq.{existing_decision[0]['id']}", decision_data)
        else:
            await db.insert("hiring_decisions", decision_data)
        recipients = await db.query("user_profiles", "active=eq.true&role=in.(admin,hr,hiring_manager)&select=id")
        for recipient in recipients:
            await db.insert("notifications", {"user_profile_id": recipient["id"], "title": "Hiring decision required", "message": "An interview scorecard is complete and awaiting review.", "category": "APPROVAL", "action_url": f"/dashboard/decisions?application={application_id}"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "INTERVIEW_SCORECARD_SUBMITTED", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": {"recommendation": payload.recommendation, "overall_score": payload.overall_score, "interview_status": "COMPLETED"}})
    return ApiMessage(message="Scorecard submitted", data=rows[0] if rows else None)


@router.get("/hiring-decisions")
async def hiring_decisions(user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings), status: str | None = Query(default=None, max_length=40)):
    filters = [f"status=eq.{quote(status, safe='_')}" ] if status else []
    query = "select=*,applications(id,application_code,name_at_application,email_at_application,status,final_score,job_positions(title,department),interviews(id,interview_code,status,scheduled_start,interview_scorecards(*,user_profiles!interview_scorecards_interviewer_id_fkey(full_name,job_title))))&" + "&".join(filters + ["order=updated_at.desc", "limit=250"])
    rows = await SupabaseClient(settings).query("hiring_decisions", query)
    if user["profile"].get("role") == "hiring_manager" and user["profile"].get("department"):
        department = str(user["profile"]["department"]).strip().casefold()
        rows = [row for row in rows if str(((row.get("applications") or {}).get("job_positions") or {}).get("department") or "").strip().casefold() == department]
    return {"success": True, "items": rows}


@router.post("/applications/{application_id}/hiring-decision", response_model=ApiMessage)
async def decide_application(application_id: str, payload: HiringDecisionCreate, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    applications_found = await db.query("applications", f"id=eq.{quote(application_id)}&select=*,job_positions(title,department)")
    if not applications_found:
        raise HTTPException(status_code=404, detail="Application not found")
    application = applications_found[0]
    completed = await db.query("interviews", f"application_id=eq.{application_id}&status=eq.COMPLETED&select=id")
    if not completed:
        raise HTTPException(status_code=409, detail="A completed interview scorecard is required before the hiring decision")
    interview_ids = ",".join(str(item["id"]) for item in completed)
    scorecards = await db.query("interview_scorecards", f"interview_id=in.({interview_ids})&submitted_at=not.is.null&select=id")
    if not scorecards:
        raise HTTPException(status_code=409, detail="A submitted interview scorecard is required before the hiring decision")
    decisions = await db.query("hiring_decisions", f"application_id=eq.{application_id}&select=*")
    if not decisions:
        latest_interview = await db.query("interviews", f"application_id=eq.{application_id}&status=eq.COMPLETED&select=id&order=created_at.desc&limit=1")
        decisions = await db.insert("hiring_decisions", {"application_id": application_id, "interview_id": latest_interview[0]["id"] if latest_interview else None})
    decision = decisions[0]
    role = user["profile"].get("role")
    now = datetime.now(timezone.utc).isoformat()
    changes: dict = {"updated_at": now}
    final_status = None
    if payload.action == "APPROVE":
        # One authorized human approval is sufficient. The exact actor and role
        # remain visible in the decision/audit record.
        changes |= {"status": "APPROVED", "final_decided_by": user["profile"]["id"], "final_decided_at": now}
        if role == "hr":
            changes |= {"hr_status": "APPROVED", "hr_id": user["profile"]["id"], "hr_reason": payload.reason, "hr_decided_at": now}
        else:
            changes |= {"manager_status": "APPROVED", "manager_id": user["profile"]["id"], "manager_reason": payload.reason, "manager_decided_at": now}
        final_status = "SELECTED"
    elif payload.action == "REJECT":
        changes |= {"status": "REJECTED", "final_decided_by": user["profile"]["id"], "final_decided_at": now}
        changes |= ({"hr_status": "REJECTED", "hr_id": user["profile"]["id"], "hr_reason": payload.reason, "hr_decided_at": now} if role == "hr" else {"manager_status": "REJECTED", "manager_id": user["profile"]["id"], "manager_reason": payload.reason, "manager_decided_at": now})
        final_status = "REJECTED"
    elif payload.action == "SECOND_INTERVIEW":
        changes |= {"status": "SECOND_INTERVIEW", "final_decided_by": user["profile"]["id"], "final_decided_at": now}
        final_status = "SHORTLISTED"
    else:
        changes |= {"status": "RETURNED_TO_REVIEW", "final_decided_by": user["profile"]["id"], "final_decided_at": now}
        final_status = "MANUAL_REVIEW"
    updated = await db.update("hiring_decisions", f"id=eq.{decision['id']}", changes)
    if final_status:
        await db.update("applications", f"id=eq.{application_id}", {"status": final_status, "status_reason": payload.reason})
        await db.insert("candidate_status_history", {"application_id": application_id, "previous_status": application.get("status"), "new_status": final_status, "reason": payload.reason, "workflow_name": "HUMAN_HIRING_DECISION", "workflow_version": "1.0.0", "changed_by": user["profile"]["id"], "correlation_id": application["correlation_id"]})
        await EmailService(settings).send_application_status(application["email_at_application"], application["name_at_application"], (application.get("job_positions") or {}).get("title", "the role"), final_status)
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "HIRING_DECISION_RECORDED", "entity_type": "APPLICATION", "entity_id": application_id, "new_data": {"action": payload.action, "reason": payload.reason, "decision_status": changes.get("status")}})
    return ApiMessage(message="Hiring decision recorded", data=updated[0] if updated else changes)


@router.get("/offers/eligible-applications")
async def offer_eligible_applications(user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    decisions = await db.query("hiring_decisions", "status=eq.APPROVED&select=application_id")
    approved_ids = [str(item["application_id"]) for item in decisions if item.get("application_id")]
    if not approved_ids:
        return {"success": True, "items": []}
    rows = await db.query("applications", f"id=in.({','.join(approved_ids)})&status=eq.SELECTED&select=id,application_code,name_at_application,email_at_application,final_score,job_positions(title,department,employment_type,experience_level)&order=updated_at.desc")
    existing = await db.query("offers", "status=not.in.(REJECTED,CANCELLED,EXPIRED)&select=application_id")
    used = {str(item["application_id"]) for item in existing}
    return {"success": True, "items": [item for item in rows if str(item["id"]) not in used]}


@router.get("/interviewers")
async def list_interviewers(user: dict = Depends(assignment_managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    direct = await db.query("user_profiles", "active=eq.true&role=in.(interviewer,hiring_manager,hr)&select=id,full_name,email,role,department,job_title,timezone&order=full_name")
    return {"success": True, "items": direct}


@router.patch("/interviews/{interview_id}/assignment", response_model=ApiMessage)
async def assign_interviewer(interview_id: str, payload: InterviewAssignmentUpdate, user: dict = Depends(assignment_managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    interviewer = await db.query("user_profiles", f"id=eq.{payload.interviewer_id}&active=eq.true&select=id,full_name,role,department")
    if not interviewer:
        raise HTTPException(status_code=400, detail="Selected interviewer is unavailable")
    if str(interviewer[0].get("role") or "").lower() not in REASSIGNABLE_INTERVIEW_ROLES:
        raise HTTPException(status_code=422, detail="Administrators, recruiters and operators cannot be assigned as interviewers")
    interview_context = await db.query("interviews", f"id=eq.{interview_id}&select=id,applications(job_positions(department))")
    if not interview_context:
        raise HTTPException(status_code=404, detail="Interview not found")
    application = interview_context[0].get("applications") or {}
    job_department = (application.get("job_positions") or {}).get("department", "")
    if not interviewer_is_eligible(interviewer[0], job_department):
        raise HTTPException(status_code=422, detail="Select an interviewer or hiring manager from the job department, or assign HR")
    assignment_status = "APPROVED" if payload.approve else "PENDING_APPROVAL"
    interview_changes = {"interviewer_id": str(payload.interviewer_id), "assignment_status": assignment_status, "interview_type": payload.interview_type, "round_number": payload.round_number, "duration_minutes": payload.duration_minutes}
    if payload.scheduled_start:
        interview_changes["scheduled_start"] = payload.scheduled_start.isoformat()
    if payload.scheduled_end:
        interview_changes["scheduled_end"] = payload.scheduled_end.isoformat()
    if payload.meeting_url is not None:
        interview_changes["meeting_url"] = payload.meeting_url
    if payload.approve:
        interview_changes["assignment_approved_by"] = user["profile"]["id"]
        interview_changes["assignment_approved_at"] = datetime.now(timezone.utc).isoformat()
    if payload.scheduled_start and payload.scheduled_end:
        scheduled = await db.query("interviews", f"interviewer_id=eq.{payload.interviewer_id}&status=not.in.(CANCELLED,COMPLETED)&scheduled_start=not.is.null&scheduled_end=not.is.null&select=id,scheduled_start,scheduled_end")
        if schedule_conflicts(scheduled, payload.scheduled_start, payload.scheduled_end, interview_id):
            raise HTTPException(status_code=409, detail="The selected interviewer is already booked during this time")
    rows = await db.update("interviews", f"id=eq.{interview_id}", interview_changes)
    await db.update("interview_assignments", f"interview_id=eq.{interview_id}&interviewer_id=neq.{payload.interviewer_id}&status=in.(PENDING_APPROVAL,APPROVED,ACCEPTED)", {"status": "REPLACED", "responded_at": datetime.now(timezone.utc).isoformat()})
    existing = await db.query("interview_assignments", f"interview_id=eq.{interview_id}&interviewer_id=eq.{payload.interviewer_id}&select=id")
    assignment = {"interview_id": interview_id, "interviewer_id": str(payload.interviewer_id), "assignment_role": payload.assignment_role, "status": assignment_status, "auto_suggested": False, "approved_by": user["profile"]["id"] if payload.approve else None, "approved_at": datetime.now(timezone.utc).isoformat() if payload.approve else None}
    if existing:
        await db.update("interview_assignments", f"id=eq.{existing[0]['id']}", assignment)
    else:
        await db.insert("interview_assignments", assignment)
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "INTERVIEW_ASSIGNMENT_UPDATED", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": interview_changes})
    details = await db.query("interviews", f"id=eq.{quote(interview_id)}&select=applications(name_at_application,email_at_application,job_positions(title))")
    if payload.approve:
        await db.insert("notifications", {"user_profile_id": str(payload.interviewer_id), "title": "Interview assigned to you", "message": "Open the interview workspace to review the candidate and schedule.", "category": "INTERVIEW", "action_url": f"/dashboard/interviews/{interview_id}"})
    if payload.approve and details:
        application = details[0].get("applications") or {}
        await EmailService(settings).send_interview_assignment_notice(application.get("email_at_application", ""), application.get("name_at_application", "Candidate"), (application.get("job_positions") or {}).get("title", "the role"))
    return ApiMessage(message="Interviewer assignment approved" if payload.approve else "Interviewer proposed for approval", data=rows[0] if rows else None)


@router.post("/interviews/{interview_id}/schedule", response_model=ApiMessage)
async def schedule_interview(interview_id: str, payload: InterviewScheduleCreate, user: dict = Depends(interview_conductors), settings: Settings = Depends(get_settings)):
    if payload.scheduled_end <= payload.scheduled_start:
        raise HTTPException(status_code=422, detail="Interview end time must be after its start time")
    if payload.scheduled_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Interview must be scheduled in the future")
    try:
        zone = ZoneInfo(payload.timezone)
    except Exception:
        raise HTTPException(status_code=422, detail="Unsupported interview timezone")
    db = SupabaseClient(settings)
    await _assigned_interview(interview_id, user, db)
    rows = await db.query("interviews", f"id=eq.{quote(interview_id)}&select=*,applications(id,candidate_id,name_at_application,email_at_application,correlation_id,job_positions(title)),user_profiles!interviews_interviewer_id_fkey(id,full_name,email)")
    if not rows:
        raise HTTPException(status_code=404, detail="Interview not found")
    interview = rows[0]; application = interview.get("applications") or {}; interviewer = interview.get("user_profiles") or user["profile"]
    conflicts = await db.query("interviews", f"interviewer_id=eq.{interviewer['id']}&id=neq.{quote(interview_id)}&status=not.in.(CANCELLED,COMPLETED)&scheduled_start=not.is.null&scheduled_end=not.is.null&select=id,scheduled_start,scheduled_end")
    if schedule_conflicts(conflicts, payload.scheduled_start, payload.scheduled_end, interview_id):
        raise HTTPException(status_code=409, detail="You already have another interview during this time")
    calendar = await GoogleCalendarService(settings).schedule_interview(
        event_id=interview.get("google_event_id"),
        summary=f"NovaTech interview - {application.get('name_at_application')} - {(application.get('job_positions') or {}).get('title')}",
        description=f"Interview code: {interview['interview_code']}", start=payload.scheduled_start.isoformat(), end=payload.scheduled_end.isoformat(), timezone_name=payload.timezone,
        attendees=[application.get("email_at_application", ""), interviewer.get("email", "")],
    )
    confirmation_token = secrets.token_urlsafe(32)
    changes = {"scheduled_start": payload.scheduled_start.isoformat(), "scheduled_end": payload.scheduled_end.isoformat(), "schedule_timezone": payload.timezone, "meeting_url": calendar["meet_url"], "meeting_code": calendar.get("meeting_code"), "google_event_id": calendar.get("event_id"), "google_event_url": calendar.get("event_url"), "status": "PENDING_CONFIRMATION", "confirmation_token": confirmation_token, "confirmation_expires_at": payload.scheduled_start.isoformat(), "confirmed_at": None, "reschedule_requested_at": None, "reschedule_requested_start": None, "candidate_response_note": None, "assignment_status": "APPROVED", "schedule_email_sent_at": None, "day_reminder_sent_at": None, "reminder_sent_at": None, "start_alert_sent_at": None}
    updated = await db.update("interviews", f"id=eq.{quote(interview_id)}", changes)
    await db.update("applications", f"id=eq.{application['id']}", {"status": "INTERVIEW_SCHEDULED", "status_reason": "Interview scheduled with Google Meet"})
    await ensure_candidate_portal_invite(db, settings, application["id"])
    recipients = await db.query("user_profiles", "active=eq.true&role=in.(admin,hr,hiring_manager)&select=id")
    for recipient in recipients:
        await db.insert("notifications", {"user_profile_id": recipient["id"], "title": "Interview scheduled", "message": f"{application.get('name_at_application')} - {payload.scheduled_start.isoformat()}", "category": "INTERVIEW", "action_url": f"/dashboard/interviews/{interview_id}"})
    await db.insert("notifications", {"user_profile_id": interviewer["id"], "title": "Interview schedule confirmed", "message": f"Starts {payload.scheduled_start.isoformat()}", "category": "INTERVIEW", "action_url": f"/dashboard/interviews/{interview_id}"})
    candidate_profiles = await db.query("user_profiles", f"candidate_id=eq.{application['candidate_id']}&active=eq.true&select=id") if application.get("candidate_id") else []
    for profile in candidate_profiles:
        await db.insert("notifications", {"user_profile_id": profile["id"], "title": "Your interview is scheduled", "message": f"Starts {payload.scheduled_start.isoformat()}", "category": "INTERVIEW", "action_url": "/portal"})
    if payload.send_email:
        emailer = EmailService(settings); position = (application.get("job_positions") or {}).get("title", "Role")
        start_label = payload.scheduled_start.astimezone(zone).strftime("%A, %d %B %Y at %I:%M %p %Z")
        end_label = payload.scheduled_end.astimezone(zone).strftime("%A, %d %B %Y at %I:%M %p %Z")
        delivery = await asyncio.gather(
            emailer.send_interview_schedule(email=application["email_at_application"], name=application["name_at_application"], position=position, interviewer=interviewer.get("full_name", "NovaTech interviewer"), start=start_label, end=end_label, meet_url=calendar["meet_url"], interview_code=interview["interview_code"], confirmation_token=confirmation_token),
            emailer.send_interview_schedule(email=interviewer.get("email", ""), name=interviewer.get("full_name", "Interviewer"), position=position, interviewer=interviewer.get("full_name", "Interviewer"), start=start_label, end=end_label, meet_url=calendar["meet_url"], interview_code=interview["interview_code"]),
            return_exceptions=True,
        )
        if any(isinstance(result, Exception) for result in delivery):
            await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "INTERVIEW_EMAIL_DELIVERY_FAILED", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": {"retry_required": True}})
        else:
            await db.update("interviews", f"id=eq.{quote(interview_id)}", {"schedule_email_sent_at": datetime.now(timezone.utc).isoformat()})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "INTERVIEW_GOOGLE_MEET_SCHEDULED", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": {"scheduled_start": payload.scheduled_start.isoformat(), "google_event_id": calendar.get("event_id")}})
    return ApiMessage(message="Google Meet interview scheduled and invitations sent", data=updated[0] if updated else changes)


@router.get("/offers")
async def offers(user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    expired = await db.query("offers", f"status=eq.OFFERED&expiry_date=lt.{date.today().isoformat()}&select=id,application_id")
    for item in expired:
        await db.update("offers", f"id=eq.{item['id']}&status=eq.OFFERED", {"status": "EXPIRED", "response_token": None, "response_notes": "Offer expired without a candidate response"})
        await db.update("applications", f"id=eq.{item['application_id']}&status=eq.OFFERED", {"status": "SELECTED", "status_reason": "Offer expired; revised offer may be created"})
    query = "select=id,offer_code,status,salary,currency,joining_date,expiry_date,employment_title,employment_level,employment_type,department,document_storage_path,sent_at,candidate_responded_at,response_notes,created_at,updated_at,applications(id,application_code,name_at_application,email_at_application,status,job_positions(title,department))&order=created_at.desc&limit=250"
    items = await db.query("offers", query)
    metrics = {status: sum(1 for item in items if item.get("status") == status) for status in ("APPROVED", "OFFERED", "ACCEPTED", "DECLINED", "CANCELLED", "EXPIRED")}
    metrics["TOTAL"] = len(items)
    return {"success": True, "items": items, "metrics": metrics}


@router.post("/offers", response_model=ApiMessage, status_code=201)
async def create_offer(payload: OfferCreate, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    applications = await db.query("applications", f"id=eq.{payload.application_id}&status=eq.SELECTED&select=id,status,name_at_application,email_at_application,candidates(full_name,email),job_positions(title,code,department)")
    if not applications:
        raise HTTPException(status_code=409, detail="Only a selected candidate can receive an offer")
    application = applications[0]
    approved = await db.query("hiring_decisions", f"application_id=eq.{payload.application_id}&status=eq.APPROVED&select=id")
    if not approved:
        raise HTTPException(status_code=409, detail="An authorized human hiring approval is required before creating an offer")
    existing = await db.query("offers", f"application_id=eq.{payload.application_id}&select=id,status")
    if existing and existing[0].get("status") not in {"REJECTED", "DECLINED", "CANCELLED", "EXPIRED"}:
        raise HTTPException(status_code=409, detail="An offer already exists for this application")
    offer_code = f"OFF-{secrets.token_hex(5).upper()}"
    response_token = secrets.token_urlsafe(40)
    data = payload.model_dump(mode="json") | {"offer_code": offer_code, "status": "APPROVED", "approval_required_levels": 1, "response_token": response_token, "sent_at": None}
    if existing:
        data |= {"candidate_responded_at": None, "response_notes": None, "document_storage_path": None, "account_invitation_sent_at": None}
        rows = await db.update("offers", f"id=eq.{existing[0]['id']}", data)
    else:
        rows = await db.insert("offers", data)
    offer = rows[0] if rows else data
    candidate = application.get("candidates") or {"full_name": application.get("name_at_application", "Candidate"), "email": application.get("email_at_application")}
    job = application.get("job_positions") or {"title": payload.employment_title}
    pdf = create_offer_pdf(offer, candidate, job)
    document_path = f"{offer['id']}/{secrets.token_hex(16)}.pdf"
    await db.upload_object("offer-documents", document_path, pdf, "application/pdf")
    await db.update("offers", f"id=eq.{offer['id']}", {"document_storage_path": document_path})
    delivered = await EmailService(settings).send_offer_ready(application["email_at_application"], application["name_at_application"], payload.employment_title, payload.expiry_date.isoformat(), str(offer["id"]), response_token)
    if not delivered:
        raise HTTPException(status_code=503, detail="Offer was created, but email delivery is disabled or SMTP configuration is incomplete. Correct email settings and use Retry sending.")
    sent_at = datetime.now(timezone.utc).isoformat()
    updated = await db.update("offers", f"id=eq.{offer['id']}&status=eq.APPROVED", {"status": "OFFERED", "sent_at": sent_at})
    await db.update("applications", f"id=eq.{payload.application_id}", {"status": "OFFERED", "status_reason": "Formal offer created and sent"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "OFFER_CREATED_AND_SENT", "entity_type": "OFFER", "entity_id": offer.get("id"), "new_data": {"salary": str(payload.salary), "employment_title": payload.employment_title, "created_by_role": user["profile"].get("role")}})
    return ApiMessage(message="Offer created and sent to the candidate", data=updated[0] if updated else offer | {"document_storage_path": document_path, "status": "OFFERED", "sent_at": sent_at})


@router.patch("/offers/{offer_id}/status", response_model=ApiMessage)
async def update_offer_status(offer_id: str, payload: OfferStatusUpdate, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{quote(offer_id)}&select=id,status,application_id,offer_code")
    if not rows:
        raise HTTPException(status_code=404, detail="Offer not found")
    offer = rows[0]
    if offer.get("status") not in {"APPROVED", "OFFERED", "NEGOTIATION"}:
        raise HTTPException(status_code=409, detail="Only an active offer can be cancelled")
    now = datetime.now(timezone.utc).isoformat()
    updated = await db.update("offers", f"id=eq.{quote(offer_id)}", {"status": "CANCELLED", "response_token": None, "response_notes": payload.reason, "candidate_responded_at": now})
    await db.update("applications", f"id=eq.{offer['application_id']}", {"status": "SELECTED", "status_reason": f"Offer cancelled: {payload.reason}"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "OFFER_CANCELLED", "entity_type": "OFFER", "entity_id": offer_id, "new_data": {"reason": payload.reason, "previous_status": offer.get("status")}})
    return ApiMessage(message="Offer cancelled. The candidate is available for a revised offer.", data=updated[0] if updated else None)


@router.patch("/offers/{offer_id}/decision", response_model=ApiMessage)
async def decide_offer(offer_id: str, payload: OfferDecision, user: dict = Depends(require_permissions("offers.approve")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    offers_found = await db.query("offers", f"id=eq.{offer_id}&select=id,status,approval_required_levels")
    if not offers_found:
        raise HTTPException(status_code=404, detail="Offer not found")
    offer = offers_found[0]
    if offer["status"] not in {"PENDING_APPROVAL", "DRAFT"}:
        raise HTTPException(status_code=409, detail="Offer is no longer awaiting approval")
    approvals = await db.query("offer_approvals", f"offer_id=eq.{offer_id}&status=eq.PENDING&order=approval_level.asc&limit=1&select=id,approval_level")
    if not approvals:
        raise HTTPException(status_code=409, detail="No pending approval step remains")
    approval = approvals[0]
    await db.update("offer_approvals", f"id=eq.{approval['id']}", {"status": payload.status, "approver_id": user["profile"]["id"], "comments": payload.comments, "decided_at": datetime.now(timezone.utc).isoformat()})
    new_status = "REJECTED" if payload.status == "REJECTED" else ("APPROVED" if int(offer["approval_required_levels"]) == int(approval["approval_level"]) else "PENDING_APPROVAL")
    rows = await db.update("offers", f"id=eq.{offer_id}", {"status": new_status})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "OFFER_APPROVAL_DECISION", "entity_type": "OFFER", "entity_id": offer_id, "new_data": {"status": payload.status, "approval_level": approval["approval_level"], "comments": payload.comments}})
    return ApiMessage(message=f"Offer {new_status.lower().replace('_', ' ')}", data=rows[0] if rows else None)


@router.post("/offers/{offer_id}/document", response_model=ApiMessage)
async def generate_offer_document(offer_id: str, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{offer_id}&status=in.(APPROVED,OFFERED,ACCEPTED)&select=*")
    if not rows:
        raise HTTPException(status_code=409, detail="Only an approved offer can generate an offer letter")
    offer = rows[0]
    applications = await db.query("applications", f"id=eq.{offer['application_id']}&select=name_at_application,candidates(full_name,email),job_positions(title,code)")
    if not applications:
        raise HTTPException(status_code=409, detail="Offer application data is unavailable")
    application = applications[0]
    candidate = application.get("candidates") or {"full_name": application.get("name_at_application", "Candidate")}
    job = application.get("job_positions") or {}
    pdf = create_offer_pdf(offer, candidate, job)
    path = f"{offer_id}/{secrets.token_hex(16)}.pdf"
    await db.upload_object("offer-documents", path, pdf, "application/pdf")
    updated = await db.update("offers", f"id=eq.{offer_id}", {"document_storage_path": path})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "OFFER_DOCUMENT_GENERATED", "entity_type": "OFFER", "entity_id": offer_id, "new_data": {"size_bytes": len(pdf)}})
    return ApiMessage(message="Offer letter PDF generated", data=updated[0] if updated else {"document_storage_path": path})


@router.get("/offers/{offer_id}/document")
async def download_offer_document(offer_id: str, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("offers", f"id=eq.{offer_id}&select=document_storage_path")
    if not rows or not rows[0].get("document_storage_path"):
        raise HTTPException(status_code=404, detail="Offer letter has not been generated")
    return {"success": True, "url": await SupabaseClient(settings).signed_object_url("offer-documents", rows[0]["document_storage_path"], 300), "expires_in": 300}


@router.post("/offers/{offer_id}/send", response_model=ApiMessage)
async def send_offer(offer_id: str, user: dict = Depends(require_roles("admin", "hr", "hiring_manager")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{offer_id}&status=in.(APPROVED,OFFERED)&select=id,application_id,expiry_date,document_storage_path,employment_title,applications(name_at_application,email_at_application)")
    if not rows:
        raise HTTPException(status_code=409, detail="Only an approved or previously sent offer can be sent")
    offer = rows[0]
    if not offer.get("document_storage_path"):
        raise HTTPException(status_code=409, detail="Generate the offer PDF before sending it")
    application = offer.get("applications") or {}
    response_token = secrets.token_urlsafe(40)
    delivered = await EmailService(settings).send_offer_ready(application.get("email_at_application", ""), application.get("name_at_application", "Candidate"), offer.get("employment_title") or "the role", offer["expiry_date"], offer_id, response_token)
    if not delivered:
        raise HTTPException(status_code=503, detail="Email delivery is disabled, SMTP configuration is incomplete, or the candidate email is invalid")
    updated = await db.update("offers", f"id=eq.{offer_id}&status=in.(APPROVED,OFFERED)", {"status": "OFFERED", "sent_at": datetime.now(timezone.utc).isoformat(), "response_token": response_token})
    await db.update("applications", f"id=eq.{offer['application_id']}", {"status": "OFFERED", "status_reason": "Formal offer sent to candidate portal"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "OFFER_SENT", "entity_type": "OFFER", "entity_id": offer_id})
    return ApiMessage(message="Offer sent to the candidate", data=updated[0] if updated else None)


@router.get("/employees")
async def employees(user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    query = "select=id,employee_code,department,start_date,status,candidates(full_name,email)&order=created_at.desc&limit=100"
    return {"success": True, "items": await SupabaseClient(settings).query("employees", query, token=user["access_token"])}


@router.post("/employees", response_model=ApiMessage, status_code=201)
async def create_employee(payload: EmployeeCreate, user: dict = Depends(require_permissions("employees.manage")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    offers_found = await db.query("offers", f"id=eq.{payload.offer_id}&status=eq.ACCEPTED&select=id,application_id,applications(candidate_id)")
    if not offers_found:
        raise HTTPException(status_code=409, detail="Only an accepted offer can create an employee")
    offer = offers_found[0]
    candidate_id = offer.get("applications", {}).get("candidate_id") if isinstance(offer.get("applications"), dict) else None
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Accepted offer is not linked to a candidate")
    existing = await db.query("employees", f"application_id=eq.{offer['application_id']}&select=id")
    if existing:
        raise HTTPException(status_code=409, detail="An employee already exists for this offer")
    employee_rows = await db.insert("employees", {"employee_code": payload.employee_code, "candidate_id": candidate_id, "application_id": offer["application_id"], "department": payload.department, "manager_id": str(payload.manager_id) if payload.manager_id else None, "start_date": payload.start_date.isoformat(), "status": "ONBOARDING"})
    employee = employee_rows[0]
    templates = [("IDENTITY", "Complete identity and tax documents", 7, "employee"), ("EQUIPMENT", "Prepare equipment and accounts", 3, "operator"), ("WELCOME", "Complete company orientation", 14, "hr")]
    for task_key, title, days, owner_role in templates:
        await db.insert("onboarding_tasks", {"employee_id": employee["id"], "task_key": task_key, "title": title, "due_date": (payload.start_date + timedelta(days=days)).isoformat(), "owner_role": owner_role, "status": "PENDING"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "EMPLOYEE_CREATED", "entity_type": "EMPLOYEE", "entity_id": employee["id"], "new_data": {"employee_code": payload.employee_code, "start_date": payload.start_date.isoformat()}})
    return ApiMessage(message="Employee created with onboarding tasks", data=employee)


@router.get("/employees/{employee_id}/onboarding")
async def employee_onboarding(employee_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    employees_found = await db.query("employees", f"id=eq.{employee_id}&select=*")
    if not employees_found:
        raise HTTPException(status_code=404, detail="Employee not found")
    tasks = await db.query("onboarding_tasks", f"employee_id=eq.{employee_id}&select=*&order=due_date.asc")
    completed = sum(task.get("status") == "COMPLETED" for task in tasks)
    return {"success": True, "employee": employees_found[0], "tasks": tasks, "progress_percent": round(completed / len(tasks) * 100) if tasks else 0}


@router.patch("/onboarding/tasks/{task_id}", response_model=ApiMessage)
async def update_onboarding_task(task_id: str, payload: OnboardingTaskUpdate, user: dict = Depends(require_permissions("employees.manage")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.update("onboarding_tasks", f"id=eq.{task_id}", {"status": payload.status, "completed_at": datetime.now(timezone.utc).isoformat() if payload.status == "COMPLETED" else None, "completed_by": user["profile"]["id"] if payload.status == "COMPLETED" else None})
    if not rows:
        raise HTTPException(status_code=404, detail="Onboarding task not found")
    return ApiMessage(message="Onboarding task updated", data=rows[0])


@router.post("/jobs", response_model=ApiMessage, status_code=201)
async def create_job(payload: JobCreate, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    data = payload.model_dump(mode="json") | {"active": True}
    rows = await SupabaseClient(settings).insert("job_positions", data, token=user["access_token"])
    return ApiMessage(message="Job created successfully", data=rows[0])


@router.patch("/jobs/{job_id}", response_model=ApiMessage)
async def update_job(job_id: str, payload: dict, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    allowed = {"title", "description", "department", "location", "employment_type", "workplace_type", "experience_level", "salary_min", "salary_max", "responsibilities", "requirements", "benefits", "closes_at", "active"}
    safe = {key: value for key, value in payload.items() if key in allowed}
    if not safe:
        raise HTTPException(status_code=400, detail="No supported fields were provided")
    rows = await SupabaseClient(settings).update("job_positions", f"id=eq.{job_id}", safe, token=user["access_token"])
    return ApiMessage(message="Job updated successfully", data=rows[0] if rows else None)


@router.patch("/jobs/{job_id}/publication", response_model=ApiMessage)
async def update_job_publication(job_id: str, payload: JobPublicationUpdate, user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    active = payload.publication_status == "PUBLISHED"
    rows = await SupabaseClient(settings).update("job_positions", f"id=eq.{job_id}", {"publication_status": payload.publication_status, "active": active})
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    await SupabaseClient(settings).insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "JOB_PUBLICATION_STATUS_CHANGED", "entity_type": "JOB", "entity_id": job_id, "new_data": {"publication_status": payload.publication_status}})
    return ApiMessage(message="Job publication status updated", data=rows[0])


@router.post("/requisitions", response_model=ApiMessage, status_code=201)
async def create_requisition(payload: RequisitionCreate, user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    existing = await db.query("hiring_requisitions", f"code=eq.{payload.code}&select=id")
    if existing:
        raise HTTPException(status_code=409, detail="Requisition code already exists")
    data = payload.model_dump(mode="json") | {"requested_by": user["profile"]["id"], "status": "PENDING"}
    rows = await db.insert("hiring_requisitions", data)
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "REQUISITION_CREATED", "entity_type": "REQUISITION", "entity_id": rows[0].get("id") if rows else None, "new_data": {"code": payload.code, "headcount": payload.headcount}})
    return ApiMessage(message="Requisition submitted for approval", data=rows[0] if rows else data)


@router.get("/requisitions")
async def list_requisitions(user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("hiring_requisitions", "select=*&order=created_at.desc&limit=200")
    return {"success": True, "items": rows}


@router.patch("/requisitions/{requisition_id}/decision", response_model=ApiMessage)
async def decide_requisition(requisition_id: str, payload: RequisitionDecision, user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.update("hiring_requisitions", f"id=eq.{requisition_id}&status=eq.PENDING", {"status": payload.status, "approved_by": user["profile"]["id"] if payload.status == "APPROVED" else None, "approved_at": datetime.now(timezone.utc).isoformat() if payload.status == "APPROVED" else None})
    if not rows:
        raise HTTPException(status_code=404, detail="Pending requisition not found")
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "REQUISITION_DECISION", "entity_type": "REQUISITION", "entity_id": requisition_id, "new_data": {"status": payload.status, "comments": payload.comments}})
    return ApiMessage(message=f"Requisition {payload.status.lower()}", data=rows[0])


@router.post("/requisitions/{requisition_id}/convert", response_model=ApiMessage, status_code=201)
async def convert_requisition(requisition_id: str, payload: JobCreate, user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    requisitions = await db.query("hiring_requisitions", f"id=eq.{requisition_id}&status=eq.APPROVED&select=id")
    if not requisitions:
        raise HTTPException(status_code=409, detail="Only an approved requisition can be converted")
    existing = await db.query("job_positions", f"requisition_id=eq.{requisition_id}&select=id")
    if existing:
        raise HTTPException(status_code=409, detail="Requisition already has a job")
    rows = await db.insert("job_positions", payload.model_dump(mode="json") | {"requisition_id": requisition_id, "publication_status": "DRAFT", "active": False})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "REQUISITION_CONVERTED_TO_JOB", "entity_type": "JOB", "entity_id": rows[0].get("id") if rows else None, "new_data": {"requisition_id": requisition_id}})
    return ApiMessage(message="Approved requisition converted to draft job", data=rows[0] if rows else None)


@router.put("/jobs/{job_id}/hiring-team", response_model=ApiMessage)
async def assign_hiring_team(job_id: str, payload: list[HiringTeamAssignment], user: dict = Depends(require_permissions("jobs.manage")), settings: Settings = Depends(get_settings)):
    if len(payload) > 50:
        raise HTTPException(status_code=422, detail="Hiring team cannot exceed 50 members")
    db = SupabaseClient(settings)
    jobs = await db.query("job_positions", f"id=eq.{job_id}&select=id")
    if not jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.delete("job_hiring_team", f"job_position_id=eq.{job_id}")
    for member in payload:
        await db.insert("job_hiring_team", {"job_position_id": job_id, **member.model_dump(mode="json")})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "HIRING_TEAM_UPDATED", "entity_type": "JOB", "entity_id": job_id, "new_data": {"member_count": len(payload)}})
    return ApiMessage(message="Hiring team updated", data={"member_count": len(payload)})


@router.get("/interviewers/{interviewer_id}/availability")
async def list_availability(interviewer_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("interviewer_availability", f"interviewer_id=eq.{interviewer_id}&select=*&order=starts_at.asc")
    return {"success": True, "items": rows}


@router.post("/interviewers/{interviewer_id}/availability", response_model=ApiMessage)
async def create_availability(interviewer_id: str, payload: AvailabilityCreate, user: dict = Depends(require_roles("admin", "hr", "recruiter", "hiring_manager", "interviewer")), settings: Settings = Depends(get_settings)):
    if user["profile"]["id"] != interviewer_id and not set(user.get("roles", set())).intersection({"admin", "hr", "recruiter", "hiring_manager"}):
        raise HTTPException(status_code=403, detail="You can only manage your own availability")
    if payload.starts_at.tzinfo is None or payload.ends_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Availability times must include a timezone")
    rows = await SupabaseClient(settings).insert("interviewer_availability", {"interviewer_id": interviewer_id, **payload.model_dump(mode="json")})
    return ApiMessage(message="Availability saved", data=rows[0] if rows else None)


@router.patch("/interviews/{interview_id}/response", response_model=ApiMessage)
async def respond_to_interview_assignment(interview_id: str, payload: InterviewerResponse, user: dict = Depends(interview_conductors), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    assignments = await db.query("interview_assignments", f"interview_id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}&status=in.(APPROVED,PENDING_APPROVAL)&select=id")
    if not assignments:
        raise HTTPException(status_code=404, detail="Interview assignment not found")
    new_status = payload.response
    rows = await db.update("interview_assignments", f"id=eq.{assignments[0]['id']}", {"status": new_status, "responded_at": datetime.now(timezone.utc).isoformat()})
    if payload.response == "ACCEPTED":
        await db.update("interviews", f"id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}", {"assignment_status": "APPROVED", "interviewer_response": "ACCEPTED", "interviewer_responded_at": datetime.now(timezone.utc).isoformat()})
    else:
        await db.update("interviews", f"id=eq.{interview_id}&interviewer_id=eq.{user['profile']['id']}", {"interviewer_response": "DECLINED", "interviewer_responded_at": datetime.now(timezone.utc).isoformat(), "assignment_reason": payload.reason or "Interviewer declined the assignment"})
        await reassign_declined_interview(db, interview_id, user["profile"]["id"])
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "INTERVIEWER_ASSIGNMENT_RESPONSE", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": {"response": payload.response, "reason": payload.reason}})
    message = "Interview assignment accepted" if payload.response == "ACCEPTED" else "Assignment declined; the next eligible department reviewer has been proposed"
    return ApiMessage(message=message, data=rows[0] if rows else None)


@router.post("/onboarding/{offer_id}/retry", response_model=ApiMessage)
async def retry_onboarding(offer_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    result = await N8nClient(settings).trigger("webhook/novatech/onboarding/start", {"offer_id": offer_id, "requested_by": user["profile"]["id"]})
    return ApiMessage(message=result.get("admin_message", "Onboarding request processed"), data=result)


@router.get("/documents")
async def documents(user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("candidate_documents", "select=id,candidate_id,application_id,document_type,file_name,mime_type,size_bytes,verification_status,verified_by,verified_at,created_at&order=created_at.desc&limit=250", token=user["access_token"])
    return {"success": True, "items": rows}


@router.get("/documents/{document_id}/download")
async def staff_document_download(document_id: str, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.query("candidate_documents", f"id=eq.{document_id}&select=storage_path,file_name")
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"success": True, "url": await db.signed_object_url("candidate-documents", rows[0]["storage_path"], 300), "file_name": rows[0]["file_name"], "expires_in": 300}


@router.patch("/documents/{document_id}/verification", response_model=ApiMessage)
async def verify_document(document_id: str, payload: DocumentVerificationUpdate, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    rows = await db.update("candidate_documents", f"id=eq.{document_id}", {"verification_status": payload.verification_status, "verified_by": user["profile"]["id"] if payload.verification_status != "PENDING" else None, "verified_at": datetime.now(timezone.utc).isoformat() if payload.verification_status != "PENDING" else None})
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "CANDIDATE_DOCUMENT_VERIFIED", "entity_type": "CANDIDATE_DOCUMENT", "entity_id": document_id, "new_data": {"verification_status": payload.verification_status}})
    return ApiMessage(message="Document verification updated", data=rows[0])
@router.get("/users")
async def list_users(
    user: dict = Depends(admins),
    settings: Settings = Depends(get_settings),
):
    query = (
        "select=id,full_name,username,email,role,department,"
        "active,must_change_password,created_at"
        "&order=created_at.desc"
    )

    items = await SupabaseClient(settings).query(
        "user_profiles",
        query,
        token=user["access_token"],
    )

    return {
        "success": True,
        "items": items,
    }


@router.post("/users", response_model=ApiMessage, status_code=201)
async def create_staff_user(
    payload: StaffUserCreate,
    user: dict = Depends(admins),
    settings: Settings = Depends(get_settings),
):
    db = SupabaseClient(settings)

    email = str(payload.email).lower()
    username = payload.username.lower()

    existing_email = await db.query(
        "user_profiles",
        f"email=eq.{email}&select=id",
    )

    existing_username = await db.query(
        "user_profiles",
        f"username=ilike.{username}&select=id",
    )

    if existing_email or existing_username:
        raise HTTPException(
            status_code=409,
            detail="Email or username already exists",
        )

    auth_user = await db.create_user(
        email,
        payload.temporary_password,
        {
            "full_name": payload.full_name,
            "role": payload.role,
        },
    )

    rows = await db.insert(
        "user_profiles",
        {
            "auth_user_id": auth_user["id"],
            "full_name": payload.full_name,
            "username": username,
            "email": email,
            "role": payload.role,
            "active": True,
            "must_change_password": True,
        },
    )

    safe_user = {
        key: rows[0].get(key)
        for key in (
            "id",
            "full_name",
            "username",
            "email",
            "role",
            "active",
        )
    }

    return ApiMessage(
        message=(
            "Staff account created. Share the temporary password "
            "securely and require an immediate password change."
        ),
        data=safe_user,
    )


@router.post("/invitations", response_model=ApiMessage, status_code=201)
async def create_invitation(payload: StaffInvitationCreate, user: dict = Depends(user_managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    email = str(payload.email).lower()
    existing = await db.query("user_profiles", f"email=eq.{email}&select=id")
    pending = await db.query("user_invitations", f"email=eq.{email}&accepted_at=is.null&revoked_at=is.null&expires_at=gt.{datetime.now(timezone.utc).isoformat()}&select=id")
    if existing or pending:
        raise HTTPException(status_code=409, detail="An active account or invitation already exists for this email")
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    rows = await db.insert("user_invitations", {"email": email, "full_name": payload.full_name, "role": payload.role, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "invited_by": user["profile"]["id"], "expires_at": expires_at.isoformat()})
    await EmailService(settings).send_staff_invitation(email, payload.full_name, payload.role, token, expires_at)
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "STAFF_INVITATION_CREATED", "entity_type": "USER_INVITATION", "entity_id": rows[0]["id"] if rows else None, "new_data": {"email": email, "role": payload.role, "expires_at": expires_at.isoformat()}})
    return ApiMessage(message="Invitation created and sent", data={"id": rows[0].get("id") if rows else None, "expires_at": expires_at})


@router.post("/invitations/{invitation_id}/revoke", response_model=ApiMessage)
async def revoke_invitation(invitation_id: str, user: dict = Depends(user_managers), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).update("user_invitations", f"id=eq.{invitation_id}&accepted_at=is.null&revoked_at=is.null", {"revoked_at": datetime.now(timezone.utc).isoformat()})
    if not rows:
        raise HTTPException(status_code=404, detail="Invitation not found or already closed")
    return ApiMessage(message="Invitation revoked")


@router.patch("/users/{profile_id}/status", response_model=ApiMessage)
async def update_staff_status(
    profile_id: str,
    payload: dict,
    user: dict = Depends(admins),
    settings: Settings = Depends(get_settings),
):
    active = payload.get("active")

    if not isinstance(active, bool):
        raise HTTPException(
            status_code=400,
            detail="active must be true or false",
        )

    if profile_id == user["profile"]["id"] and not active:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own account",
        )

    rows = await SupabaseClient(settings).update(
        "user_profiles",
        f"id=eq.{profile_id}",
        {"active": active},
    )

    return ApiMessage(
        message="User status updated",
        data=rows[0] if rows else None,
    )


@router.get("/users/{profile_id}/access")
async def get_user_access(profile_id: str, user: dict = Depends(user_managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    roles = await db.query("user_roles", f"user_profile_id=eq.{profile_id}&select=role")
    overrides = await db.query("user_permission_overrides", f"user_profile_id=eq.{profile_id}&select=permission_key,allowed")
    return {"success": True, "roles": [item["role"] for item in roles], "overrides": overrides}


@router.put("/users/{profile_id}/access", response_model=ApiMessage)
async def update_user_access(profile_id: str, payload: UserAccessUpdate, user: dict = Depends(user_managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    profiles = await db.query("user_profiles", f"id=eq.{profile_id}&select=id,role,active")
    if not profiles:
        raise HTTPException(status_code=404, detail="User not found")
    if profiles[0].get("active") and profiles[0].get("role") == "admin" and "admin" not in payload.roles:
        admins = await db.query("user_profiles", "role=eq.admin&active=eq.true&select=id")
        if len(admins) <= 1:
            raise HTTPException(status_code=409, detail="The last active administrator cannot lose admin access")
    await db.delete("user_roles", f"user_profile_id=eq.{profile_id}")
    for role in sorted(set(payload.roles)):
        await db.insert("user_roles", {"user_profile_id": profile_id, "role": role, "assigned_by": user["profile"]["id"]})
    await db.update("user_profiles", f"id=eq.{profile_id}", {"role": payload.roles[0]})
    await db.delete("user_permission_overrides", f"user_profile_id=eq.{profile_id}")
    for permission in set(payload.allowed_permissions):
        await db.insert("user_permission_overrides", {"user_profile_id": profile_id, "permission_key": permission, "allowed": True, "granted_by": user["profile"]["id"]})
    for permission in set(payload.denied_permissions):
        await db.insert("user_permission_overrides", {"user_profile_id": profile_id, "permission_key": permission, "allowed": False, "granted_by": user["profile"]["id"]})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "USER_ACCESS_UPDATED", "entity_type": "USER", "entity_id": profile_id, "new_data": {"roles": payload.roles, "allowed_permission_count": len(payload.allowed_permissions), "denied_permission_count": len(payload.denied_permissions)}})
    return ApiMessage(message="User roles and permission overrides updated", data={"roles": payload.roles})
