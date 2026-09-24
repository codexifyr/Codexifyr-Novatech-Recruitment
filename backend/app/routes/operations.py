from datetime import date, datetime, timezone
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from app.config import Settings, get_settings
from app.schemas import ApiMessage, BulkApplicationAction, NotificationPreferencesUpdate, WorkflowReplayRequest
from app.security import current_user, require_permissions, require_roles
from app.services.supabase import SupabaseClient
from app.services.n8n import N8nClient
from app.services.pdf import create_analytics_pdf
from app.services.recruitment import ensure_candidate_portal_invite, ensure_interview
from app.services.emailer import EmailService

router = APIRouter(prefix="/operations", tags=["operations"])
staff = require_roles("admin", "hr", "recruiter", "hiring_manager", "interviewer", "operator")
managers = require_roles("admin", "hr", "recruiter", "hiring_manager")
admins = require_roles("admin")
operations_staff = require_roles("admin", "hr", "recruiter", "hiring_manager", "operator")


@router.get("/reference-data")
async def reference_data(user: dict = Depends(staff), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    departments = await db.query("departments", "active=eq.true&select=*&order=name")
    designations = await db.query("designations", "active=eq.true&select=*&order=title")
    permissions = await db.query("permissions", "select=*&order=category,key")
    return {"success": True, "departments": departments, "designations": designations, "permissions": permissions}


@router.get("/notifications")
async def notifications(user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("notifications", f"user_profile_id=eq.{user['profile']['id']}&select=*&order=created_at.desc&limit=100")
    return {"success": True, "items": rows}


@router.patch("/notifications/{notification_id}/read", response_model=ApiMessage)
async def read_notification(notification_id: str, user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).update("notifications", f"id=eq.{notification_id}&user_profile_id=eq.{user['profile']['id']}", {"read_at": datetime.now(timezone.utc).isoformat()})
    return ApiMessage(message="Notification marked as read", data=rows[0] if rows else None)


@router.get("/notifications/unread-count")
async def unread_notification_count(user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("notifications", f"user_profile_id=eq.{user['profile']['id']}&read_at=is.null&select=id")
    return {"success": True, "count": len(rows)}


@router.patch("/notifications/read-all", response_model=ApiMessage)
async def read_all_notifications(user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).update("notifications", f"user_profile_id=eq.{user['profile']['id']}&read_at=is.null", {"read_at": datetime.now(timezone.utc).isoformat()})
    return ApiMessage(message="All notifications marked as read", data={"count": len(rows)})


@router.get("/notification-preferences")
async def notification_preferences(user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("notification_preferences", f"user_profile_id=eq.{user['profile']['id']}&select=*")
    return {"success": True, "preferences": rows[0] if rows else {"user_profile_id": user["profile"]["id"], "email_enabled": True, "in_app_enabled": True, "interview_alerts": True, "approval_alerts": True, "digest_frequency": "DAILY"}}


@router.patch("/notification-preferences", response_model=ApiMessage)
async def update_notification_preferences(payload: NotificationPreferencesUpdate, user: dict = Depends(current_user), settings: Settings = Depends(get_settings)):
    changes = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(status_code=400, detail="No preference changes were provided")
    changes["user_profile_id"] = user["profile"]["id"]
    db = SupabaseClient(settings)
    existing = await db.query("notification_preferences", f"user_profile_id=eq.{user['profile']['id']}&select=user_profile_id")
    rows = await db.update("notification_preferences", f"user_profile_id=eq.{user['profile']['id']}", changes) if existing else await db.insert("notification_preferences", changes)
    return ApiMessage(message="Notification preferences updated", data=rows[0] if rows else changes)


@router.get("/audit")
async def audit(user: dict = Depends(admins), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("audit_logs", "select=*,user_profiles(full_name,email)&order=created_at.desc&limit=250")
    return {"success": True, "items": rows}


@router.get("/workflow-health")
async def workflow_health(user: dict = Depends(operations_staff), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    executions = await db.query("workflow_executions", "select=*&order=started_at.desc&limit=100")
    errors = await db.query("automation_errors", "status=in.(OPEN,RETRYING,DEAD)&select=*&order=created_at.desc&limit=100")
    return {"success": True, "executions": executions, "errors": errors}


@router.post("/workflow-health/{error_id}/replay", response_model=ApiMessage)
async def replay_workflow(error_id: str, payload: WorkflowReplayRequest, user: dict = Depends(require_permissions("workflows.manage")), settings: Settings = Depends(get_settings)):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Replay confirmation is required")
    routes = {"APPLICATION_INTAKE": "/webhook/novatech/applications", "INTERVIEW_CONFIRM": "/webhook/novatech/interviews/confirm", "INTERVIEW_RESCHEDULE": "/webhook/novatech/interviews/reschedule", "OFFER_CREATE": "/webhook/novatech/offers/create", "OFFER_APPROVAL": "/webhook/novatech/offers/approval", "OFFER_SEND": "/webhook/novatech/offers/send", "OFFER_RESPONSE": "/webhook/novatech/offers/respond", "ONBOARDING_START": "/webhook/novatech/onboarding/start", "ONBOARDING_TASK_COMPLETE": "/webhook/novatech/onboarding/tasks/complete"}
    db = SupabaseClient(settings)
    errors = await db.query("automation_errors", f"id=eq.{error_id}&status=in.(OPEN,RETRYING,DEAD)&select=id,correlation_id,retry_count")
    if not errors:
        raise HTTPException(status_code=404, detail="Replayable workflow error not found")
    event_key = f"MANUAL_REPLAY:{error_id}"
    if await db.query("processed_events", f"event_key=eq.{event_key}&select=id"):
        raise HTTPException(status_code=409, detail="This workflow error has already been replayed")
    event = await db.insert("processed_events", {"event_key": event_key, "event_type": "MANUAL_REPLAY", "correlation_id": errors[0].get("correlation_id") or error_id, "entity_type": "AUTOMATION_ERROR", "entity_id": error_id, "result": "REPLAY_REQUESTED"})
    replay_payload = {**payload.corrected_payload, "error_id": error_id, "correlation_id": errors[0].get("correlation_id"), "operator_id": user["profile"]["id"], "resolution_notes": payload.resolution_notes}
    result = await N8nClient(settings).trigger(routes[payload.target_key], replay_payload)
    await db.update("automation_errors", f"id=eq.{error_id}", {"status": "RETRYING", "retry_count": int(errors[0].get("retry_count") or 0) + 1})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "WORKFLOW_MANUAL_REPLAY", "entity_type": "AUTOMATION_ERROR", "entity_id": error_id, "new_data": {"target_key": payload.target_key, "event_id": event[0].get("id") if event else None}})
    return ApiMessage(message="Workflow replay requested", data=result)


@router.get("/pipeline")
async def pipeline(user: dict = Depends(operations_staff), settings: Settings = Depends(get_settings)):
    rows = await SupabaseClient(settings).query("applications", "archived_at=is.null&select=id,application_code,name_at_application,status,final_score,created_at,tags,job_positions(title,department)&order=created_at.desc&limit=500", token=user["access_token"])
    return {"success": True, "items": rows}


@router.patch("/applications/{application_id}/stage", response_model=ApiMessage)
async def move_stage(application_id: str, payload: dict, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    status = payload.get("status")
    allowed = {"NEW","VALIDATING","VALIDATED","SCORED","SHORTLISTED","MANUAL_REVIEW","REJECTED","INTERVIEW_SCHEDULED","INTERVIEWED","SELECTED","OFFER_PENDING_APPROVAL","OFFERED","ACCEPTED","DECLINED","NEGOTIATION","ONBOARDING","ONBOARDED"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported application status")
    db = SupabaseClient(settings)
    before = await db.query("applications", f"id=eq.{application_id}&select=status,correlation_id,name_at_application,email_at_application,job_positions(title)")
    if not before:
        raise HTTPException(status_code=404, detail="Application not found")
    rows = await db.update("applications", f"id=eq.{application_id}", {"status": status, "status_reason": payload.get("reason")})
    await db.insert("candidate_status_history", {"application_id": application_id, "previous_status": before[0]["status"], "new_status": status, "reason": payload.get("reason"), "workflow_name": "CODE_ADMIN_PIPELINE", "changed_by": user["profile"]["id"], "correlation_id": before[0]["correlation_id"]})
    await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": "APPLICATION_STAGE_CHANGED", "entity_type": "APPLICATION", "entity_id": application_id, "previous_data": {"status": before[0]["status"]}, "new_data": {"status": status}})
    if status == "SHORTLISTED":
        await ensure_interview(db, application_id, user["profile"]["id"])
        await ensure_candidate_portal_invite(db, settings, application_id)
    if before[0]["status"] != status and status in {"SHORTLISTED", "MANUAL_REVIEW", "REJECTED"}:
        await EmailService(settings).send_application_status(before[0]["email_at_application"], before[0]["name_at_application"], (before[0].get("job_positions") or {}).get("title", "the role"), status)
    return ApiMessage(message="Application stage updated", data=rows[0] if rows else None)


@router.post("/applications/bulk", response_model=ApiMessage)
async def bulk_application_action(payload: BulkApplicationAction, user: dict = Depends(managers), settings: Settings = Depends(get_settings)):
    db = SupabaseClient(settings)
    changes = {"SHORTLIST": {"status": "SHORTLISTED", "status_reason": payload.reason}, "REJECT": {"status": "REJECTED", "status_reason": payload.reason}, "ARCHIVE": {"archived_at": datetime.now(timezone.utc).isoformat()}}[payload.action]
    updated = 0
    for application_id in payload.application_ids:
        before = await db.query("applications", f"id=eq.{application_id}&select=status,name_at_application,email_at_application,job_positions(title)")
        rows = await db.update("applications", f"id=eq.{application_id}&archived_at=is.null", changes)
        if rows:
            updated += 1
            if payload.action == "SHORTLIST":
                await ensure_interview(db, str(application_id), user["profile"]["id"])
                await ensure_candidate_portal_invite(db, settings, str(application_id))
            target_status = changes.get("status")
            if before and target_status in {"SHORTLISTED", "REJECTED"} and before[0]["status"] != target_status:
                await EmailService(settings).send_application_status(before[0]["email_at_application"], before[0]["name_at_application"], (before[0].get("job_positions") or {}).get("title", "the role"), target_status)
            await db.insert("audit_logs", {"actor_id": user["profile"]["id"], "action": f"APPLICATION_BULK_{payload.action}", "entity_type": "APPLICATION", "entity_id": str(application_id), "new_data": {"reason": payload.reason}})
    return ApiMessage(message=f"Bulk {payload.action.lower()} action applied to {updated} applications", data={"updated": updated, "requested": len(payload.application_ids)})


def _analytics_filters(date_from: date | None, date_to: date | None) -> str:
    filters = ""
    if date_from:
        filters += f"&created_at=gte.{date_from.isoformat()}T00:00:00Z"
    if date_to:
        filters += f"&created_at=lte.{date_to.isoformat()}T23:59:59Z"
    return filters


async def _analytics_data(date_from: date | None, date_to: date | None, settings: Settings):
    db = SupabaseClient(settings)
    filters = _analytics_filters(date_from, date_to)
    applications = await db.query("applications", f"select=status,source,created_at,final_score,job_positions(title,department)&order=created_at.desc&limit=5000{filters}")
    offers = await db.query("offers", f"select=status,created_at,candidate_responded_at&order=created_at.desc&limit=5000{filters}")
    interviews = await db.query("interviews", f"select=status,assignment_status,scheduled_start,created_at&order=created_at.desc&limit=5000{filters}")
    counts: dict[str, int] = {}
    for item in applications:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    metrics = {"applications_total": len(applications), "interviews_total": len(interviews), "offers_total": len(offers), "by_status": counts}
    return metrics


@router.get("/analytics")
async def analytics(user: dict = Depends(operations_staff), settings: Settings = Depends(get_settings), date_from: date | None = Query(default=None), date_to: date | None = Query(default=None)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    return {"success": True, "metrics": await _analytics_data(date_from, date_to, settings)}


@router.get("/analytics/export")
async def analytics_export(user: dict = Depends(require_roles("admin", "hr", "recruiter", "hiring_manager")), settings: Settings = Depends(get_settings), date_from: date | None = Query(default=None), date_to: date | None = Query(default=None)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    metrics = await _analytics_data(date_from, date_to, settings)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    writer.writerow(["applications_total", metrics["applications_total"]])
    writer.writerow(["interviews_total", metrics["interviews_total"]])
    writer.writerow(["offers_total", metrics["offers_total"]])
    for status, count in metrics["by_status"].items():
        writer.writerow([f"applications_status_{status}", count])
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=novatech-analytics.csv"})


@router.get("/analytics/report.pdf")
async def analytics_pdf_export(user: dict = Depends(require_roles("admin", "hr", "recruiter", "hiring_manager")), settings: Settings = Depends(get_settings), date_from: date | None = Query(default=None), date_to: date | None = Query(default=None)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")
    return Response(content=create_analytics_pdf(await _analytics_data(date_from, date_to, settings)), media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=novatech-analytics.pdf"})

