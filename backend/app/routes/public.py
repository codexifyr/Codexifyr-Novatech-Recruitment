from datetime import date, datetime, timezone
from decimal import Decimal
from datetime import timedelta
from uuid import uuid4
import asyncio
from typing import Awaitable
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import EmailStr
from app.config import Settings, get_settings
from app.schemas import ApiMessage, InterviewCandidateResponse
from app.services.cv_security import scan_cv
from app.services.cv_review import review_cv
from app.services.recruitment import ensure_candidate_portal_invite, ensure_interview
from app.services.emailer import EmailService
from app.services.n8n import N8nClient
from app.services.supabase import SupabaseClient

router = APIRouter(tags=["public"])
CV_TYPES = {"application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}
MAX_CV_BYTES = 10 * 1024 * 1024


async def deliver_application_emails(db: SupabaseClient, application_id: str | None, recipient: str, deliveries: list[tuple[str, str, Awaitable[bool]]]) -> None:
    results = await asyncio.gather(*(delivery[2] for delivery in deliveries), return_exceptions=True)
    now = datetime.now(timezone.utc).isoformat()
    for (template_key, subject, _), result in zip(deliveries, results):
        await db.insert("email_delivery_logs", {
            "template_key": template_key,
            "recipient_email": recipient,
            "subject": subject,
            "entity_type": "APPLICATION",
            "entity_id": application_id,
            "provider": "SMTP",
            "status": "FAILED" if isinstance(result, Exception) else ("SENT" if result else "QUEUED"),
            "error_message": str(result)[:500] if isinstance(result, Exception) else None,
            "sent_at": now if result is True else None,
        })


@router.get("/jobs")
async def list_jobs(settings: Settings = Depends(get_settings)):
    client = SupabaseClient(settings)
    deadline = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    query = f"active=eq.true&publication_status=eq.PUBLISHED&or=(application_deadline.is.null,application_deadline.gte.{deadline})&select=id,code,slug,title,department,description,location,employment_type,workplace_type,experience_level,salary_min,salary_max,currency,responsibilities,requirements,benefits,closes_at&order=created_at.desc"
    return {"success": True, "items": await client.query("job_positions", query)}


@router.get("/jobs/{slug}")
async def get_job(slug: str, settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query(
        "job_positions",
        f"slug=eq.{slug}&active=eq.true&publication_status=eq.PUBLISHED&or=(application_deadline.is.null,application_deadline.gte.{datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})&select=id,code,slug,title,department,description,location,employment_type,workplace_type,experience_level,salary_min,salary_max,currency,responsibilities,requirements,benefits,closes_at",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Job was not found")
    return {"success": True, "item": rows[0]}


async def verify_turnstile(token: str | None, request: Request, settings: Settings) -> None:
    if not settings.turnstile_enabled:
        return
    if not token:
        raise HTTPException(status_code=400, detail="Human verification is required")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.turnstile_secret_key, "response": token, "remoteip": request.client.host if request.client else ""},
        )
    if not response.json().get("success"):
        raise HTTPException(status_code=400, detail="Human verification failed")


@router.post("/applications", response_model=ApiMessage, status_code=202)
async def submit_application(
    request: Request,
    job_slug: str = Form(...), full_name: str = Form(..., min_length=2, max_length=120),
    email: EmailStr = Form(...), phone: str = Form(..., min_length=7, max_length=25),
    experience_years: float = Form(..., ge=0, le=60), skills: str = Form(...),
    expected_salary: Decimal = Form(..., ge=0), currency: str = Form("PKR", min_length=3, max_length=3),
    joining_date: date = Form(...), consent: bool = Form(...), cv: UploadFile = File(...),
    turnstile_token: str | None = Form(None), settings: Settings = Depends(get_settings),
):
    if not consent:
        raise HTTPException(status_code=400, detail="Privacy consent is required")
    await verify_turnstile(turnstile_token, request, settings)
    content_type = (cv.content_type or "").lower()
    extension = CV_TYPES.get(content_type)
    if not extension or not cv.filename or not cv.filename.lower().endswith(extension):
        raise HTTPException(status_code=400, detail="CV must be a PDF or DOCX file")
    content = await cv.read(MAX_CV_BYTES + 1)
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="CV must be 10 MB or smaller")
    if (content_type == "application/pdf" and not content.startswith(b"%PDF")) or (content_type.endswith("document") and not content.startswith(b"PK\x03\x04")):
        raise HTTPException(status_code=400, detail="CV content does not match its declared file type")
    security = scan_cv(content, content_type)
    parsed_skills = [item.strip()[:80] for item in skills.split(",") if item.strip()][:30]
    if not parsed_skills:
        raise HTTPException(status_code=400, detail="At least one skill is required")
    db = SupabaseClient(settings)
    jobs = await db.query("job_positions", f"slug=eq.{job_slug}&active=eq.true&publication_status=eq.PUBLISHED&or=(application_deadline.is.null,application_deadline.gte.{datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})&select=id,title,requirements,department")
    if not jobs:
        raise HTTPException(status_code=404, detail="This job is no longer available")
    normalized_email = str(email).strip().lower()
    existing_applications = await db.query(
        "applications",
        f"job_position_id=eq.{jobs[0]['id']}&email_at_application={db.eq(normalized_email)}&select=id,application_code,status,created_at&order=created_at.desc&limit=1",
    )
    if existing_applications:
        return ApiMessage(
            message=f"Your application request for {jobs[0]['title']} has been received. Please check your email for previous application details.",
            data={
                "display_status": "Application request received",
            },
        )
    request_id = str(uuid4())
    storage_path = f"applications/{request_id}{extension}"
    await db.upload_object("candidate-documents", storage_path, content, content_type)
    signed_cv_url = await db.signed_object_url("candidate-documents", storage_path, 3600)
    review = review_cv(
        text=security.safe_text, title=jobs[0]["title"], requirements=jobs[0].get("requirements"),
        submitted_skills=parsed_skills, submitted_experience=float(experience_years),
        security_status=security.status, security_flags=list(security.flags),
    )
    if security.requires_manual_review:
        normalized_phone = "".join(character for character in phone if character.isdigit() or character == "+")
        candidates = await db.query("candidates", f"normalized_email={db.eq(normalized_email)}&normalized_phone={db.eq(normalized_phone)}&select=id")
        if candidates:
            candidate_id = candidates[0]["id"]
        else:
            candidate_id = (await db.insert("candidates", {
                "candidate_code": f"CAN-{datetime.now().year}-{uuid4().hex[:10].upper()}",
                "full_name": full_name.strip(), "normalized_name": " ".join(full_name.lower().split()),
                "email": normalized_email, "normalized_email": normalized_email,
                "phone": phone.strip(), "normalized_phone": normalized_phone,
            }))[0]["id"]
        correlation_id = f"COR-{datetime.now(timezone.utc):%Y%m%d}-{request_id.replace('-', '')[-8:]}"
        event_id = f"APPLICATION_EVENT_{request_id}"
        application = (await db.insert("applications", {
            "application_code": f"APP-{datetime.now().year}-{request_id.replace('-', '')[-10:].upper()}",
            "candidate_id": candidate_id, "job_position_id": jobs[0]["id"],
            "correlation_id": correlation_id, "event_id": event_id,
            "name_at_application": full_name.strip(), "email_at_application": normalized_email,
            "phone_at_application": phone.strip(), "experience_years": experience_years,
            "skills": parsed_skills, "expected_salary": float(expected_salary), "currency": currency.upper(),
            "joining_date": joining_date.isoformat(), "cv_url": None, "cv_present": True,
            "cv_storage_path": storage_path, "cv_original_filename": cv.filename, "cv_mime_type": content_type,
            "cv_security_status": security.status,
            "cv_security_flags": list(security.flags), "source": "careers_portal",
            "status": "MANUAL_REVIEW", "status_reason": "CV security review required",
            "rule_score": review["score"], "final_score": review["score"], "ai_review": review,
            "reviewed_at": datetime.now(timezone.utc).isoformat(), "review_version": review["review_version"],
        }))[0]
        await db.insert("cv_security_assessments", {"application_id": application["id"], "file_sha256": security.sha256, "mime_type": content_type, "status": security.status, "flags": list(security.flags), "extracted_characters": security.extracted_characters, "scanner_version": "1.0.0"})
        await db.insert("candidate_status_history", {"application_id": application["id"], "previous_status": None, "new_status": "MANUAL_REVIEW", "reason": "Automated CV security screening requires human review", "workflow_name": "BACKEND_CV_SECURITY", "workflow_version": "1.0.0", "correlation_id": correlation_id})
        emailer = EmailService(settings)
        await deliver_application_emails(db, application["id"], normalized_email, [
            ("APPLICATION_RECEIVED", f"Application received - {jobs[0]['title']}", emailer.send_application_received(normalized_email, full_name.strip(), jobs[0]["title"], application["application_code"])),
            ("APPLICATION_MANUAL_REVIEW", "Your application is under review", emailer.send_application_status(normalized_email, full_name.strip(), jobs[0]["title"], "MANUAL_REVIEW")),
        ])
        return ApiMessage(message="Your application has been submitted successfully.", data={"application_code": application["application_code"], "status": "MANUAL_REVIEW", "display_status": "Application received"})
    payload = {
        "request_id": request_id,
        "name": full_name.strip(),
        "email": str(email).lower(),
        "phone": phone.strip(),
        "position": jobs[0]["title"],
        "experience_years": review["cv_experience_years"],
        "skills": review["verified_skills"],
        "expected_salary": float(expected_salary),
        "currency": currency.upper(),
        "joining_date": joining_date.isoformat(),
        "cv_url": signed_cv_url,
        "cv_text": security.safe_text[:50000],
        "cv_security": security.public_metadata(),
        "cv_present": True,
        "source": "careers_portal",
        "submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        result = await N8nClient(settings).trigger("webhook/novatech/applications", payload)
    except Exception:
        await db.delete_object("candidate-documents", storage_path)
        raise
    correlation_id = result.get("correlation_id")
    applications = await db.query("applications", f"correlation_id=eq.{correlation_id}&select=id,status,application_code,correlation_id") if correlation_id else []
    application = applications[0] if applications else None
    email_deliveries = []
    application_code = (application or {}).get("application_code") or result.get("application_code") or f"APP-{datetime.now().year}-{request_id.replace('-', '')[-10:].upper()}"
    emailer = EmailService(settings)
    email_deliveries.append(("APPLICATION_RECEIVED", f"Application received - {jobs[0]['title']}", emailer.send_application_received(str(email).lower(), full_name.strip(), jobs[0]["title"], application_code)))
    if application:
        authoritative_status = review["decision"]
        update = {
            "cv_storage_path": storage_path, "cv_original_filename": cv.filename, "cv_mime_type": content_type,
            "cv_security_status": security.status, "cv_security_flags": list(security.flags),
            "rule_score": review["score"], "final_score": review["score"], "ai_review": review,
            "status": authoritative_status,
            "status_reason": "CV evidence score is 80 or above" if authoritative_status == "SHORTLISTED" else "CV evidence requires human review",
            "reviewed_at": datetime.now(timezone.utc).isoformat(), "review_version": review["review_version"],
        }
        await db.update("applications", f"id=eq.{application['id']}", update)
        await db.insert("cv_security_assessments", {"application_id": application["id"], "file_sha256": security.sha256, "mime_type": content_type, "status": security.status, "flags": list(security.flags), "extracted_characters": security.extracted_characters, "scanner_version": "1.0.0"})
        if application.get("status") != authoritative_status:
            await db.insert("candidate_status_history", {"application_id": application["id"], "previous_status": application.get("status"), "new_status": authoritative_status, "reason": update["status_reason"], "workflow_name": "BACKEND_CV_EVIDENCE_REVIEW", "workflow_version": "2.0.0", "correlation_id": application["correlation_id"]})
        if authoritative_status == "SHORTLISTED":
            await ensure_interview(db, application["id"])
            await ensure_candidate_portal_invite(db, settings, application["id"])
        if application.get("status") != authoritative_status:
            email_deliveries.append((f"APPLICATION_{authoritative_status}", f"Application status - {authoritative_status}", emailer.send_application_status(str(email).lower(), full_name.strip(), jobs[0]["title"], authoritative_status)))
    await deliver_application_emails(db, application.get("id") if application else None, str(email).lower(), email_deliveries)
    safe_data = {
        "application_code": application_code,
        "status": review["decision"],
        "display_status": result.get("display_status") or "Application received",
    }
    return ApiMessage(message="Your application has been submitted successfully.", data=safe_data)


async def _interview_for_response(db: SupabaseClient, token: str) -> dict:
    rows = await db.query(
        "interviews",
        f"confirmation_token={db.eq(token)}&select=id,interview_code,status,scheduled_start,scheduled_end,schedule_timezone,meeting_url,confirmation_expires_at,interviewer_id,reschedule_requested_at,reschedule_decision_status,applications(id,name_at_application,email_at_application,job_positions(title))",
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Interview response link is invalid")
    interview = rows[0]
    expires_at = interview.get("confirmation_expires_at") or interview.get("scheduled_start")
    if expires_at:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Interview response link has expired")
    if interview.get("status") in {"CANCELLED", "COMPLETED", "NO_SHOW"}:
        label = str(interview["status"]).lower().replace("_", " ")
        raise HTTPException(status_code=409, detail=f"Interview is already {label}")
    return interview


@router.get("/interviews/respond")
async def interview_response_details(token: str = Query(min_length=32, max_length=256), settings: Settings = Depends(get_settings)):
    interview = await _interview_for_response(SupabaseClient(settings), token)
    application = interview.get("applications") or {}
    return {
        "success": True,
        "item": {
            "interview_code": interview.get("interview_code"),
            "status": interview.get("status"),
            "scheduled_start": interview.get("scheduled_start"),
            "scheduled_end": interview.get("scheduled_end"),
            "timezone": interview.get("schedule_timezone"),
            "meeting_url": interview.get("meeting_url") if interview.get("status") == "CONFIRMED" else None,
            "candidate_name": application.get("name_at_application"),
            "position": (application.get("job_positions") or {}).get("title"),
        },
    }


async def _notify_interview_response(db: SupabaseClient, interview: dict, title: str, message: str) -> None:
    recipients = await db.query("user_profiles", "active=eq.true&role=in.(admin,hr,hiring_manager)&select=id")
    recipient_ids = {str(row["id"]) for row in recipients}
    if interview.get("interviewer_id"):
        recipient_ids.add(str(interview["interviewer_id"]))
    for profile_id in recipient_ids:
        await db.insert("notifications", {
            "user_profile_id": profile_id,
            "title": title,
            "message": message,
            "category": "INTERVIEW",
            "action_url": f"/dashboard/interviews/{interview['id']}",
        })


@router.post("/interviews/confirm", response_model=ApiMessage)
async def confirm_interview(payload: InterviewCandidateResponse, settings: Settings = Depends(get_settings)):
    if payload.action != "CONFIRMED":
        raise HTTPException(status_code=422, detail="Use the reschedule action to request another time")
    db = SupabaseClient(settings)
    interview = await _interview_for_response(db, payload.confirmation_token)
    application = interview.get("applications") or {}
    if interview.get("reschedule_requested_at") and not interview.get("reschedule_decision_status"):
        raise HTTPException(status_code=409, detail="Your reschedule request is awaiting a hiring-team decision")
    if interview.get("status") != "CONFIRMED":
        now = datetime.now(timezone.utc).isoformat()
        await db.update("interviews", f"id=eq.{interview['id']}", {"status": "CONFIRMED", "confirmed_at": now, "reschedule_requested_at": None, "reschedule_requested_start": None, "candidate_response_note": payload.note or None})
        await db.insert("audit_logs", {"action": "CANDIDATE_INTERVIEW_CONFIRMED", "entity_type": "INTERVIEW", "entity_id": interview["id"], "new_data": {"confirmed_at": now}})
        await _notify_interview_response(db, interview, "Candidate confirmed interview", f"{application.get('name_at_application', 'Candidate')} confirmed {interview['interview_code']}.")
        await EmailService(settings).send_interview_response(
            email=application.get("email_at_application", ""),
            name=application.get("name_at_application", "Candidate"),
            position=(application.get("job_positions") or {}).get("title", "the role"),
            action="CONFIRMED",
        )
    return ApiMessage(message="Your interview has been confirmed successfully.", data={"status": "CONFIRMED", "interview_code": interview["interview_code"]})


@router.post("/interviews/reschedule", response_model=ApiMessage)
async def reschedule_interview(payload: InterviewCandidateResponse, settings: Settings = Depends(get_settings)):
    if payload.action != "RESCHEDULE" or payload.requested_start is None:
        raise HTTPException(status_code=422, detail="A preferred future date and time is required")
    if payload.requested_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Preferred interview time must be in the future")
    db = SupabaseClient(settings)
    interview = await _interview_for_response(db, payload.confirmation_token)
    application = interview.get("applications") or {}
    if interview.get("reschedule_requested_at") and not interview.get("reschedule_decision_status"):
        raise HTTPException(status_code=409, detail="A reschedule request is already awaiting a decision")
    now = datetime.now(timezone.utc).isoformat()
    requested = payload.requested_start.isoformat()
    await db.update("interviews", f"id=eq.{interview['id']}", {
        "status": "PENDING_CONFIRMATION",
        "reschedule_previous_status": interview.get("status") or "PENDING_CONFIRMATION",
        "reschedule_requested_at": now,
        "reschedule_requested_start": requested,
        "candidate_response_note": payload.note or None,
        "reschedule_decision_status": None,
        "reschedule_decided_by": None,
        "reschedule_decided_at": None,
        "reschedule_decision_note": None,
    })
    await db.insert("audit_logs", {"action": "CANDIDATE_INTERVIEW_RESCHEDULE_REQUESTED", "entity_type": "INTERVIEW", "entity_id": interview["id"], "new_data": {"requested_start": requested}})
    await _notify_interview_response(db, interview, "Candidate requested a new interview time", f"{application.get('name_at_application', 'Candidate')} requested {requested} for {interview['interview_code']}.")
    await EmailService(settings).send_interview_response(
        email=application.get("email_at_application", ""),
        name=application.get("name_at_application", "Candidate"),
        position=(application.get("job_positions") or {}).get("title", "the role"),
        action="RESCHEDULE",
        requested_start=requested,
    )
    return ApiMessage(message="Your reschedule request has been sent to HR and the hiring manager.", data={"status": "PENDING_CONFIRMATION", "interview_code": interview["interview_code"]})


@router.post("/offers/respond", response_model=ApiMessage)
async def respond_offer(payload: dict, settings: Settings = Depends(get_settings)):
    offer_id = str(payload.get("offer_id") or "").strip()
    response_token = str(payload.get("response_token") or "").strip()
    decision = str(payload.get("response") or "").upper()
    notes = str(payload.get("notes") or "")[:2000]
    if not offer_id or not response_token or decision not in {"ACCEPTED", "DECLINED"}:
        raise HTTPException(status_code=422, detail="A valid secure offer response is required")
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{offer_id}&response_token=eq.{response_token}&status=eq.OFFERED&select=*,applications(id,candidate_id,name_at_application,email_at_application,job_positions(title,department))")
    if not rows:
        raise HTTPException(status_code=404, detail="This offer response link is invalid or has already been used")
    offer = rows[0]
    if date.fromisoformat(offer["expiry_date"]) < date.today():
        await db.update("offers", f"id=eq.{offer_id}", {"status": "EXPIRED", "response_token": None})
        raise HTTPException(status_code=409, detail="This offer has expired")
    application = offer.get("applications") or {}
    now = datetime.now(timezone.utc).isoformat()
    await db.update("offers", f"id=eq.{offer_id}&status=eq.OFFERED", {"status": decision, "candidate_responded_at": now, "response_notes": notes, "response_token": None})
    if decision == "DECLINED":
        await db.update("applications", f"id=eq.{application['id']}", {"status": "DECLINED", "status_reason": notes or "Candidate declined the offer"})
        return ApiMessage(message="Your offer response has been recorded.")
    candidate_id = application.get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Offer is not linked to a candidate")
    existing_employee = await db.query("employees", f"application_id=eq.{application['id']}&select=id")
    if not existing_employee:
        employee_code = f"EMP-{datetime.now(timezone.utc):%Y%m}-{uuid4().hex[:6].upper()}"
        employees = await db.insert("employees", {"employee_code": employee_code, "candidate_id": candidate_id, "application_id": application["id"], "offer_id": offer_id, "department": offer.get("department") or (application.get("job_positions") or {}).get("department") or "Unassigned", "employment_title": offer.get("employment_title") or (application.get("job_positions") or {}).get("title") or "Employee", "employment_level": offer.get("employment_level") or "Mid-level", "employment_type": offer.get("employment_type") or "Full-time", "start_date": offer["joining_date"], "status": "ONBOARDING"})
        employee = employees[0]
        starts = date.fromisoformat(offer["joining_date"])
        for task_key, title, days, owner_role in (("PROFILE", "Complete employee profile", 1, "employee"), ("IDENTITY", "Upload identity and payroll documents", 3, "employee"), ("EQUIPMENT", "Prepare equipment and system access", 2, "operator"), ("WELCOME", "Complete company orientation", 7, "hr")):
            await db.insert("onboarding_tasks", {"employee_id": employee["id"], "task_key": task_key, "title": title, "due_date": (starts + timedelta(days=days)).isoformat(), "owner_role": owner_role, "status": "PENDING"})
    email = str(application.get("email_at_application") or "").strip().lower()
    profiles = await db.query("user_profiles", f"email={db.eq(email)}&select=id,auth_user_id,candidate_id,role")
    if profiles:
        profile = profiles[0]
        await db.update("user_profiles", f"id=eq.{profile['id']}", {"role": "employee", "candidate_id": candidate_id, "active": True})
    else:
        profile = (await db.insert("user_profiles", {"full_name": application.get("name_at_application") or "Employee", "email": email, "role": "employee", "candidate_id": candidate_id, "active": True, "must_change_password": False}))[0]
    role_rows = await db.query("user_roles", f"user_profile_id=eq.{profile['id']}&role=eq.employee&select=user_profile_id")
    if not role_rows:
        await db.insert("user_roles", {"user_profile_id": profile["id"], "role": "employee"})
    await db.update("applications", f"id=eq.{application['id']}", {"status": "ONBOARDING", "status_reason": "Offer accepted; employee account setup invited"})
    await EmailService(settings).send_employee_activation(email, application.get("name_at_application") or "Employee", offer.get("employment_title") or "Employee", offer.get("employment_level") or "Mid-level", offer.get("department") or "Unassigned")
    await db.update("offers", f"id=eq.{offer_id}", {"account_invitation_sent_at": now})
    await db.insert("audit_logs", {"action": "PUBLIC_OFFER_ACCEPTED_AND_ACCOUNT_INVITED", "entity_type": "OFFER", "entity_id": offer_id, "new_data": {"employee_role": "employee", "employment_title": offer.get("employment_title")}})
    return ApiMessage(message="Offer accepted. Check your email to create your employee account.")

