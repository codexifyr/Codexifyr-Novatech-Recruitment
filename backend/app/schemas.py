from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class Job(BaseModel):
    id: UUID
    code: str
    slug: str
    title: str
    department: str
    description: str | None = None
    location: str
    employment_type: str
    workplace_type: str
    experience_level: str
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    currency: str = "PKR"
    responsibilities: list[str] = []
    requirements: list[str] = []
    benefits: list[str] = []
    closes_at: datetime | None = None


class ApplicationCreate(BaseModel):
    job_slug: str
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=25)
    experience_years: float = Field(ge=0, le=60)
    skills: list[str] = Field(min_length=1, max_length=30)
    expected_salary: Decimal = Field(ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    joining_date: date
    cv_url: str = Field(min_length=8, max_length=1000)
    consent: bool
    turnstile_token: str | None = None

    @field_validator("consent")
    @classmethod
    def consent_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Privacy consent is required")
        return value


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class OtpRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    purpose: Literal["PASSWORD_RESET", "CANDIDATE_REGISTRATION"]


class OtpVerify(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    purpose: Literal["PASSWORD_RESET", "CANDIDATE_REGISTRATION"]
    otp: str = Field(pattern=r"^\d{6}$")


class PasswordComplete(BaseModel):
    verification_token: str
    username: str | None = Field(default=None, min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=10, max_length=128)


class JobCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=120)
    department: str
    description: str
    location: str = "Islamabad, Pakistan"
    employment_type: str = "Full-time"
    workplace_type: str = "Hybrid"
    experience_level: str = "Mid-level"
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    requirements: list[str] = []
    responsibilities: list[str] = []
    benefits: list[str] = []
    closes_at: datetime | None = None


class ApiMessage(BaseModel):
    success: bool = True
    message: str
    data: Any | None = None
class StaffUserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)

    username: str = Field(
        min_length=3,
        max_length=40,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )

    email: EmailStr

    role: Literal[
        "admin",
        "hr",
        "recruiter",
        "hiring_manager",
        "interviewer",
        "operator",
    ]

    temporary_password: str = Field(
        min_length=10,
        max_length=128,
    )


class StaffInvitationCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    role: Literal["hr", "recruiter", "hiring_manager", "interviewer", "operator", "admin"]
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class StaffInvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=10, max_length=128)


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9._-]+$")
    job_title: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1000)
    timezone: str = Field(default="Asia/Karachi", max_length=80)


class PasswordChange(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class InterviewAssignmentUpdate(BaseModel):
    interviewer_id: UUID
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    meeting_url: str | None = Field(default=None, max_length=1000)
    interview_type: str = Field(default="Technical", max_length=80)
    round_number: int = Field(default=1, ge=1, le=20)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    assignment_role: Literal["LEAD", "INTERVIEWER", "OBSERVER"] = "LEAD"
    approve: bool = True


class InterviewScheduleCreate(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str = Field(default="Asia/Karachi", max_length=80)
    send_email: bool = True

    @model_validator(mode="after")
    def timezone_aware_schedule(self):
        if self.scheduled_start.tzinfo is None or self.scheduled_end.tzinfo is None:
            raise ValueError("Interview times must include a timezone")
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("Interview end time must be after its start time")
        return self


class InterviewCandidateResponse(BaseModel):
    confirmation_token: str = Field(min_length=32, max_length=256)
    action: Literal["CONFIRMED", "RESCHEDULE"]
    requested_start: datetime | None = None
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_reschedule_request(self):
        if self.action == "RESCHEDULE" and self.requested_start is None:
            raise ValueError("A preferred date and time is required for rescheduling")
        if self.requested_start is not None and self.requested_start.tzinfo is None:
            raise ValueError("Preferred date and time must include a timezone")
        return self


class InterviewRescheduleDecision(BaseModel):
    decision: Literal["ACCEPTED", "REJECTED"]
    reason: str = Field(default="", max_length=1000)


class CandidateRescheduleRequest(BaseModel):
    requested_start: datetime
    note: str = Field(default="", max_length=1000)

    @field_validator("requested_start")
    @classmethod
    def timezone_aware_request(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Preferred date and time must include a timezone")
        return value


class InternalNoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=5000)
    visibility: Literal["HIRING_TEAM", "HR_ONLY", "ADMIN_ONLY"] = "HIRING_TEAM"


class DocumentVerificationUpdate(BaseModel):
    verification_status: Literal["PENDING", "VERIFIED", "REJECTED"]


class ScorecardCreate(BaseModel):
    technical_score: int = Field(ge=1, le=10)
    communication_score: int = Field(ge=1, le=10)
    problem_solving_score: int = Field(ge=1, le=10)
    experience_score: int = Field(ge=1, le=10)
    team_fit_score: int = Field(ge=1, le=10)
    overall_score: float = Field(ge=1, le=10)
    recommendation: Literal["STRONG_HIRE", "HIRE", "REVIEW", "NO_HIRE", "STRONG_NO_HIRE"]
    comments: str = Field(default="", max_length=5000)


class HiringDecisionCreate(BaseModel):
    action: Literal["APPROVE", "REJECT", "SECOND_INTERVIEW", "RETURN_TO_REVIEW"]
    reason: str = Field(min_length=3, max_length=3000)


class OfferCreate(BaseModel):
    application_id: UUID
    salary: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    joining_date: date
    probation_months: int = Field(default=3, ge=0, le=24)
    reporting_manager_id: UUID | None = None
    expiry_date: date
    approval_required_levels: int = Field(default=1, ge=1, le=2)
    employment_title: str = Field(min_length=2, max_length=120)
    employment_level: Literal["Intern", "Junior", "Mid-level", "Senior", "Lead", "Manager"] = "Mid-level"
    employment_type: Literal["Internship", "Full-time", "Part-time", "Contract"] = "Full-time"
    department: str = Field(min_length=2, max_length=120)

    @model_validator(mode="after")
    def expiry_after_joining(self):
        if self.expiry_date < date.today():
            raise ValueError("Offer expiry date cannot be in the past")
        if self.joining_date < self.expiry_date:
            raise ValueError("Joining date must be on or after the offer expiry date")
        return self


class OfferDecision(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    comments: str = Field(default="", max_length=2000)


class OfferStatusUpdate(BaseModel):
    status: Literal["CANCELLED"]
    reason: str = Field(min_length=3, max_length=1000)


class EmployeeCreate(BaseModel):
    offer_id: UUID
    employee_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    department: str = Field(min_length=2, max_length=120)
    manager_id: UUID | None = None
    start_date: date


class OnboardingTaskUpdate(BaseModel):
    status: Literal["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


class NotificationPreferencesUpdate(BaseModel):
    email_enabled: bool | None = None
    in_app_enabled: bool | None = None
    interview_alerts: bool | None = None
    approval_alerts: bool | None = None
    digest_frequency: Literal["IMMEDIATE", "DAILY", "WEEKLY", "NONE"] | None = None


class UserAccessUpdate(BaseModel):
    roles: list[Literal["admin", "hr", "recruiter", "hiring_manager", "interviewer", "operator"]] = Field(min_length=1, max_length=6)
    allowed_permissions: list[str] = Field(default_factory=list, max_length=100)
    denied_permissions: list[str] = Field(default_factory=list, max_length=100)


class WorkflowReplayRequest(BaseModel):
    target_key: Literal["APPLICATION_INTAKE", "INTERVIEW_CONFIRM", "INTERVIEW_RESCHEDULE", "OFFER_CREATE", "OFFER_APPROVAL", "OFFER_SEND", "OFFER_RESPONSE", "ONBOARDING_START", "ONBOARDING_TASK_COMPLETE"]
    corrected_payload: dict[str, Any] = Field(default_factory=dict)
    resolution_notes: str = Field(default="Corrected and replayed by operator", max_length=2000)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def confirmation_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Replay confirmation is required")
        return value


class CandidateOfferResponse(BaseModel):
    decision: Literal["ACCEPTED", "DECLINED"]
    notes: str = Field(default="", max_length=2000)


class BulkApplicationAction(BaseModel):
    application_ids: list[UUID] = Field(min_length=1, max_length=100)
    action: Literal["SHORTLIST", "REJECT", "ARCHIVE"]
    reason: str = Field(default="Bulk action by authorized hiring staff", max_length=1000)
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def confirmation_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Bulk action confirmation is required")
        return value


class JobPublicationUpdate(BaseModel):
    publication_status: Literal["DRAFT", "PENDING_APPROVAL", "PUBLISHED", "CLOSED", "ARCHIVED"]


class RequisitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=2, max_length=120)
    department_id: UUID | None = None
    headcount: int = Field(default=1, ge=1, le=100)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="PKR", min_length=3, max_length=3)
    justification: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def budget_order(self):
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("budget_min must not exceed budget_max")
        return self


class RequisitionDecision(BaseModel):
    status: Literal["APPROVED", "REJECTED"]
    comments: str = Field(default="", max_length=2000)


class HiringTeamAssignment(BaseModel):
    user_profile_id: UUID
    team_role: Literal["RECRUITER", "HR_OWNER", "HIRING_MANAGER", "INTERVIEWER"]


class AvailabilityCreate(BaseModel):
    starts_at: datetime
    ends_at: datetime
    unavailable: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Availability end must be after start")
        return self


class InterviewerResponse(BaseModel):
    response: Literal["ACCEPTED", "DECLINED"]
    reason: str = Field(default="", max_length=1000)
