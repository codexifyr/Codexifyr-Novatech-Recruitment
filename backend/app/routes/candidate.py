from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from app.config import Settings, get_settings
from app.security import require_roles
from app.services.supabase import SupabaseClient
from app.schemas import CandidateOfferResponse, CandidateRescheduleRequest, OnboardingTaskUpdate
from app.services.emailer import EmailService

router = APIRouter(prefix="/candidate", tags=["candidate portal"])
candidate_user = require_roles("candidate", "employee")
ALLOWED_DOCUMENTS = {"application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "image/jpeg": ".jpg", "image/png": ".png"}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def validate_document(file_name: str | None, content_type: str, content: bytes) -> str:
    extension = ALLOWED_DOCUMENTS.get(content_type.lower())
    if not extension or not file_name or not file_name.lower().endswith(extension):
        raise HTTPException(status_code=400, detail="Only PDF, DOCX, JPG and PNG documents are allowed")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document must be 10 MB or smaller")
    signatures = {"application/pdf": content.startswith(b"%PDF"), "image/jpeg": content.startswith(b"\xff\xd8\xff"), "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document": content.startswith(b"PK\x03\x04")}
    if not signatures.get(content_type.lower(), False):
        raise HTTPException(status_code=400, detail="The uploaded file content does not match its declared type")
    return extension


@router.get("/portal")
async def portal(user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="This account is not linked to a candidate record")
    db = SupabaseClient(settings)
    applications = await db.query("applications", f"candidate_id=eq.{candidate_id}&select=id,application_code,status,status_reason,final_score,created_at,job_positions(title,department,location),interviews(id,interview_code,status,scheduled_start,scheduled_end,schedule_timezone,meeting_url,meeting_code,reschedule_requested_at,reschedule_requested_start,reschedule_decision_status),offers(id,offer_code,status,joining_date,expiry_date,document_storage_path)&order=created_at.desc")
    documents = await db.query("candidate_documents", f"candidate_id=eq.{candidate_id}&select=id,document_type,file_name,verification_status,created_at&order=created_at.desc")
    privacy = await db.query("privacy_requests", f"candidate_id=eq.{candidate_id}&select=*&order=requested_at.desc")
    employees = await db.query("employees", f"candidate_id=eq.{candidate_id}&select=id,employee_code,department,start_date,status")
    onboarding = await db.query("onboarding_tasks", f"employee_id=eq.{employees[0]['id']}&select=*&order=due_date.asc") if employees else []
    return {"success": True, "applications": applications, "documents": documents, "privacy_requests": privacy, "employee": employees[0] if employees else None, "onboarding": onboarding}


@router.post("/interviews/{interview_id}/reschedule")
async def request_owned_interview_reschedule(interview_id: str, payload: CandidateRescheduleRequest, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    if payload.requested_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Preferred interview time must be in the future")
    db = SupabaseClient(settings)
    rows = await db.query("interviews", f"id=eq.{quote(interview_id)}&select=id,interview_code,status,interviewer_id,reschedule_requested_at,reschedule_decision_status,applications!inner(candidate_id,name_at_application,email_at_application,job_positions(title))")
    if not rows or str((rows[0].get("applications") or {}).get("candidate_id")) != str(candidate_id):
        raise HTTPException(status_code=404, detail="Interview not found")
    interview = rows[0]
    if interview.get("status") in {"CANCELLED", "COMPLETED", "NO_SHOW"}:
        raise HTTPException(status_code=409, detail="This interview can no longer be rescheduled")
    if interview.get("reschedule_requested_at") and not interview.get("reschedule_decision_status"):
        raise HTTPException(status_code=409, detail="A reschedule request is already awaiting a decision")
    now = datetime.now(timezone.utc).isoformat()
    requested = payload.requested_start.isoformat()
    await db.update("interviews", f"id=eq.{quote(interview_id)}", {
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
    application = interview.get("applications") or {}
    recipient_ids = set()
    managers = await db.query("user_profiles", "active=eq.true&role=in.(admin,hr,hiring_manager)&select=id")
    recipient_ids.update(str(row["id"]) for row in managers)
    if interview.get("interviewer_id"):
        recipient_ids.add(str(interview["interviewer_id"]))
    for profile_id in recipient_ids:
        await db.insert("notifications", {"user_profile_id": profile_id, "title": "Candidate requested a new interview time", "message": f"{application.get('name_at_application', 'Candidate')} requested {requested} for {interview['interview_code']}.", "category": "INTERVIEW", "action_url": f"/dashboard/interviews/{interview_id}"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "CANDIDATE_INTERVIEW_RESCHEDULE_REQUESTED", "entity_type": "INTERVIEW", "entity_id": interview_id, "new_data": {"requested_start": requested, "source": "CANDIDATE_PORTAL"}})
    await EmailService(settings).send_interview_response(email=application.get("email_at_application", ""), name=application.get("name_at_application", "Candidate"), position=(application.get("job_positions") or {}).get("title", "the role"), action="RESCHEDULE", requested_start=requested)
    return {"success": True, "message": "Your reschedule request has been sent to the assigned interviewer and hiring team."}


@router.post("/privacy-request")
async def privacy_request(payload: dict, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    request_type = payload.get("request_type")
    if request_type not in {"EXPORT", "CORRECT", "DELETE"}:
        raise HTTPException(status_code=400, detail="Unsupported privacy request")
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    rows = await SupabaseClient(settings).insert("privacy_requests", {"candidate_id": candidate_id, "request_type": request_type, "notes": payload.get("notes")})
    return {"success": True, "message": "Privacy request submitted", "data": rows[0]}


@router.post("/documents")
async def upload_document(document_type: str = Form(...), file: UploadFile = File(...), user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    content_type = (file.content_type or "").lower()
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    extension = validate_document(file.filename, content_type, content)
    storage_path = f"{candidate_id}/{uuid4().hex}{extension}"
    db = SupabaseClient(settings)
    await db.upload_object("candidate-documents", storage_path, content, content_type)
    rows = await db.insert("candidate_documents", {"candidate_id": candidate_id, "document_type": document_type.strip()[:80], "file_name": file.filename[:255], "storage_path": storage_path, "mime_type": content_type, "size_bytes": len(content), "verification_status": "PENDING"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "CANDIDATE_DOCUMENT_UPLOADED", "entity_type": "CANDIDATE_DOCUMENT", "entity_id": rows[0]["id"] if rows else None, "new_data": {"document_type": document_type[:80], "mime_type": content_type, "size_bytes": len(content)}})
    return {"success": True, "message": "Document uploaded for review", "data": rows[0] if rows else None}


@router.get("/documents/{document_id}/download")
async def download_document(document_id: str, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    db = SupabaseClient(settings)
    rows = await db.query("candidate_documents", f"id=eq.{quote(document_id)}&candidate_id=eq.{quote(candidate_id)}&select=storage_path,file_name")
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"success": True, "url": await db.signed_object_url("candidate-documents", rows[0]["storage_path"], 300), "file_name": rows[0]["file_name"], "expires_in": 300}


@router.patch("/onboarding/tasks/{task_id}")
async def update_own_onboarding_task(task_id: str, payload: OnboardingTaskUpdate, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    db = SupabaseClient(settings)
    employees = await db.query("employees", f"candidate_id=eq.{candidate_id}&select=id")
    if not employees:
        raise HTTPException(status_code=404, detail="Onboarding record not found")
    if payload.status not in {"IN_PROGRESS", "COMPLETED"}:
        raise HTTPException(status_code=400, detail="Candidate can only start or complete an onboarding task")
    rows = await db.update("onboarding_tasks", f"id=eq.{task_id}&employee_id=eq.{employees[0]['id']}", {"status": payload.status, "completed_at": datetime.now(timezone.utc).isoformat() if payload.status == "COMPLETED" else None, "completed_by": user["profile"]["id"] if payload.status == "COMPLETED" else None})
    if not rows:
        raise HTTPException(status_code=404, detail="Onboarding task not found")
    return {"success": True, "message": "Onboarding task updated", "data": rows[0]}


@router.get("/offers/{offer_id}/document")
async def candidate_offer_document(offer_id: str, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{offer_id}&status=in.(APPROVED,OFFERED,ACCEPTED)&select=document_storage_path,applications!inner(candidate_id)")
    if not rows or rows[0].get("applications", {}).get("candidate_id") != candidate_id or not rows[0].get("document_storage_path"):
        raise HTTPException(status_code=404, detail="Offer letter is not available")
    return {"success": True, "url": await db.signed_object_url("offer-documents", rows[0]["document_storage_path"], 300), "expires_in": 300}


@router.patch("/offers/{offer_id}/response")
async def respond_to_owned_offer(offer_id: str, payload: CandidateOfferResponse, user: dict = Depends(candidate_user), settings: Settings = Depends(get_settings)):
    candidate_id = user["profile"].get("candidate_id")
    if not candidate_id:
        raise HTTPException(status_code=409, detail="Candidate account is not linked")
    db = SupabaseClient(settings)
    rows = await db.query("offers", f"id=eq.{offer_id}&select=id,status,expiry_date,application_id,joining_date,department,employment_title,employment_level,employment_type,applications!inner(candidate_id,name_at_application,email_at_application)")
    if not rows or rows[0].get("applications", {}).get("candidate_id") != candidate_id:
        raise HTTPException(status_code=404, detail="Offer not found")
    offer = rows[0]
    if offer["status"] not in {"APPROVED", "OFFERED", "NEGOTIATION"}:
        raise HTTPException(status_code=409, detail="This offer is not available for response")
    if date.fromisoformat(offer["expiry_date"]) < date.today():
        raise HTTPException(status_code=409, detail="This offer has expired")
    updated = await db.update("offers", f"id=eq.{offer_id}", {"status": payload.decision, "candidate_responded_at": datetime.now(timezone.utc).isoformat(), "response_notes": payload.notes})
    application = offer.get("applications") or {}
    if payload.decision == "ACCEPTED":
        existing_employee = await db.query("employees", f"application_id=eq.{offer['application_id']}&select=id")
        if not existing_employee:
            employee_code = f"EMP-{datetime.now(timezone.utc):%Y%m}-{uuid4().hex[:6].upper()}"
            employees = await db.insert("employees", {"employee_code": employee_code, "candidate_id": candidate_id, "application_id": offer["application_id"], "offer_id": offer_id, "department": offer.get("department") or "Unassigned", "employment_title": offer.get("employment_title") or "Employee", "employment_level": offer.get("employment_level") or "Mid-level", "employment_type": offer.get("employment_type") or "Full-time", "start_date": offer["joining_date"], "status": "ONBOARDING"})
            employee = employees[0]
            start_date = date.fromisoformat(offer["joining_date"])
            for task_key, title, days, owner_role in (("PROFILE", "Complete employee profile", 1, "employee"), ("IDENTITY", "Upload identity and payroll documents", 3, "employee"), ("EQUIPMENT", "Prepare equipment and system access", 2, "operator"), ("WELCOME", "Complete company orientation", 7, "hr")):
                await db.insert("onboarding_tasks", {"employee_id": employee["id"], "task_key": task_key, "title": title, "due_date": (start_date + timedelta(days=days)).isoformat(), "owner_role": owner_role, "status": "PENDING"})
        profiles = await db.query("user_profiles", f"candidate_id=eq.{candidate_id}&select=id,role")
        for profile in profiles:
            await db.update("user_profiles", f"id=eq.{profile['id']}", {"role": "employee"})
            if profile.get("role") != "employee":
                await db.insert("user_roles", {"user_profile_id": profile["id"], "role": "employee"})
        await db.update("applications", f"id=eq.{offer['application_id']}", {"status": "ONBOARDING", "status_reason": "Offer accepted; employee onboarding started"})
        await EmailService(settings).send_employee_activation(application.get("email_at_application", user["profile"].get("email", "")), application.get("name_at_application", user["profile"].get("full_name", "Candidate")), offer.get("employment_title") or "Employee", offer.get("employment_level") or "Mid-level", offer.get("department") or "Unassigned")
    elif payload.decision == "DECLINED":
        await db.update("applications", f"id=eq.{offer['application_id']}", {"status": "DECLINED", "status_reason": payload.notes or "Candidate declined the offer"})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "CANDIDATE_OFFER_RESPONSE", "entity_type": "OFFER", "entity_id": offer_id, "new_data": {"decision": payload.decision}})
    return {"success": True, "message": "Offer response recorded", "data": updated[0] if updated else None}
