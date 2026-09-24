from datetime import (
    datetime,
    timedelta,
    timezone,
)
import hashlib
import json
import secrets
from urllib.parse import quote

import jwt
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)

from app.config import Settings, get_settings
from app.schemas import (
    ApiMessage,
    LoginRequest,
    OtpRequest,
    OtpVerify,
    PasswordChange,
    PasswordComplete,
    ProfileUpdate,
    StaffInvitationAccept,
)
from app.security import (
    current_user,
    generate_otp,
    make_verification_token,
    otp_hash,
    read_verification_token,
    safe_compare,
)
from app.services.emailer import EmailService
from app.services.supabase import SupabaseClient


router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

PROFILE_IMAGES = {
    "image/jpeg": (
        ".jpg",
        b"\xff\xd8\xff",
    ),
    "image/png": (
        ".png",
        b"\x89PNG\r\n\x1a\n",
    ),
    "image/webp": (
        ".webp",
        b"RIFF",
    ),
}


async def resolve_profile(
    identifier: str,
    db: SupabaseClient,
) -> dict | None:
    clean = identifier.strip().lower()

    column = (
        "email"
        if "@" in clean
        else "username"
    )

    rows = await db.query(
        "user_profiles",
        (
            f"{column}=ilike."
            f"{quote(clean, safe='@._-')}"
            "&select=*"
        ),
    )

    return rows[0] if rows else None


@router.post(
    "/invitations/accept",
    response_model=ApiMessage,
)
async def accept_invitation(
    payload: StaffInvitationAccept,
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    token_hash = hashlib.sha256(
        payload.token.encode()
    ).hexdigest()

    rows = await db.query(
        "user_invitations",
        (
            f"token_hash=eq.{token_hash}"
            "&accepted_at=is.null"
            "&revoked_at=is.null"
            "&select=*"
        ),
    )

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invitation is invalid "
                "or expired"
            ),
        )

    invitation = rows[0]

    expires_at = datetime.fromisoformat(
        invitation["expires_at"].replace(
            "Z",
            "+00:00",
        )
    )

    if expires_at <= datetime.now(
        timezone.utc
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invitation is invalid "
                "or expired"
            ),
        )

    duplicate = await db.query(
        "user_profiles",
        (
            "username=ilike."
            f"{quote(payload.username.lower())}"
            "&select=id"
        ),
    )

    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                "Username is already in use"
            ),
        )

    existing_auth_user = (
        await db.find_auth_user_by_email(
            invitation["email"]
        )
    )

    if existing_auth_user:
        auth_user = existing_auth_user

        await db.update_user_password(
            auth_user["id"],
            payload.password,
        )
    else:
        auth_user = await db.create_user(
            invitation["email"],
            payload.password,
            {
                "full_name": (
                    invitation["full_name"]
                ),
                "role": invitation["role"],
            },
        )

    existing_profiles = await db.query(
        "user_profiles",
        (
            "email=eq."
            f"{quote(invitation['email'])}"
            "&select=*"
        ),
    )

    profile_data = {
        "auth_user_id": auth_user["id"],
        "full_name": (
            invitation["full_name"]
        ),
        "username": (
            payload.username.lower()
        ),
        "email": invitation["email"],
        "role": invitation["role"],
        "active": True,
        "must_change_password": False,
    }

    if existing_profiles:
        profiles = await db.update(
            "user_profiles",
            (
                f"id=eq."
                f"{existing_profiles[0]['id']}"
            ),
            profile_data,
        )
    else:
        profiles = await db.insert(
            "user_profiles",
            profile_data,
        )

    profile = profiles[0]

    role_rows = await db.query(
        "user_roles",
        (
            "user_profile_id=eq."
            f"{profile['id']}"
            "&role=eq."
            f"{invitation['role']}"
            "&select=user_profile_id"
        ),
    )

    if not role_rows:
        await db.insert(
            "user_roles",
            {
                "user_profile_id": (
                    profile["id"]
                ),
                "role": invitation["role"],
            },
        )

    await db.update(
        "user_invitations",
        (
            f"id=eq.{invitation['id']}"
            "&accepted_at=is.null"
        ),
        {
            "accepted_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "accepted_user_profile_id": (
                profile["id"]
            ),
            "username": (
                payload.username.lower()
            ),
        },
    )

    return ApiMessage(
        message=(
            "Invitation accepted. "
            "You can now sign in."
        ),
        data={
            "username": (
                payload.username.lower()
            ),
        },
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    profile = await resolve_profile(
        payload.identifier,
        db,
    )

    identifier_hash = hashlib.sha256(
        payload.identifier
        .strip()
        .lower()
        .encode()
    ).hexdigest()

    if (
        not profile
        or not profile.get("active")
    ):
        await db.insert(
            "login_history",
            {
                "identifier_hash": (
                    identifier_hash
                ),
                "successful": False,
                "ip_address": (
                    request.client.host
                    if request.client
                    else None
                ),
                "user_agent": (
                    request.headers.get(
                        "user-agent"
                    )
                ),
            },
        )

        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid login credentials"
            ),
        )

    try:
        session = await db.login(
            profile["email"],
            payload.password,
        )
    except HTTPException:
        await db.insert(
            "login_history",
            {
                "user_profile_id": (
                    profile["id"]
                ),
                "identifier_hash": (
                    identifier_hash
                ),
                "successful": False,
                "ip_address": (
                    request.client.host
                    if request.client
                    else None
                ),
                "user_agent": (
                    request.headers.get(
                        "user-agent"
                    )
                ),
            },
        )

        raise

    body = {
        "success": True,
        "access_token": (
            session["access_token"]
        ),
        "refresh_token": session.get(
            "refresh_token"
        ),
        "expires_in": session.get(
            "expires_in"
        ),
        "user": profile,
        "requires_persona": bool(
            settings
            .shared_staff_login_enabled
            and profile.get(
                "shared_staff_account"
            )
        ),
    }

    response = Response(
        content=json.dumps(body),
        media_type="application/json",
    )

    csrf = secrets.token_urlsafe(32)

    response.set_cookie(
        settings.session_cookie_name,
        session["access_token"],
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=(
            settings
            .session_max_age_seconds
        ),
        path="/",
    )

    if session.get("refresh_token"):
        response.set_cookie(
            settings.refresh_cookie_name,
            session["refresh_token"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=(
                settings
                .session_max_age_seconds
            ),
            path="/",
        )

    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=(
            settings
            .session_max_age_seconds
        ),
        path="/",
    )

    await db.insert(
        "login_history",
        {
            "user_profile_id": (
                profile["id"]
            ),
            "identifier_hash": (
                identifier_hash
            ),
            "successful": True,
            "ip_address": (
                request.client.host
                if request.client
                else None
            ),
            "user_agent": (
                request.headers.get(
                    "user-agent"
                )
            ),
        },
    )

    await db.insert(
        "auth_sessions",
        {
            "user_profile_id": (
                profile["id"]
            ),
            "access_token_hash": (
                hashlib.sha256(
                    session[
                        "access_token"
                    ].encode()
                ).hexdigest()
            ),
            "refresh_token_hash": (
                hashlib.sha256(
                    session[
                        "refresh_token"
                    ].encode()
                ).hexdigest()
                if session.get(
                    "refresh_token"
                )
                else None
            ),
            "ip_address": (
                request.client.host
                if request.client
                else None
            ),
            "user_agent": (
                request.headers.get(
                    "user-agent"
                )
            ),
            "expires_at": (
                datetime.now(
                    timezone.utc
                )
                + timedelta(
                    seconds=session.get(
                        "expires_in",
                        settings
                        .session_max_age_seconds,
                    )
                )
            ).isoformat(),
        },
    )

    return response


@router.post("/refresh")
async def refresh_session(
    response: Response,
    refresh_token: str | None = Cookie(
        default=None,
        alias="novatech_refresh",
    ),
    settings: Settings = Depends(
        get_settings
    ),
):
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Authentication required"
            ),
        )

    session = await SupabaseClient(
        settings
    ).refresh(refresh_token)

    response.set_cookie(
        settings.session_cookie_name,
        session["access_token"],
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=(
            settings
            .session_max_age_seconds
        ),
        path="/",
    )

    if session.get("refresh_token"):
        response.set_cookie(
            settings.refresh_cookie_name,
            session["refresh_token"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=(
                settings
                .session_max_age_seconds
            ),
            path="/",
        )

    return {
        "success": True,
        "expires_in": session.get(
            "expires_in"
        ),
    }


@router.post(
    "/logout",
    response_model=ApiMessage,
)
async def logout(
    response: Response,
    session_token: str | None = Cookie(
        default=None,
        alias="novatech_session",
    ),
    settings: Settings = Depends(
        get_settings
    ),
):
    if session_token:
        token_hash = hashlib.sha256(
            session_token.encode()
        ).hexdigest()

        await SupabaseClient(
            settings
        ).update(
            "auth_sessions",
            (
                "access_token_hash=eq."
                f"{token_hash}"
            ),
            {
                "revoked_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

    cookie_names = (
        settings.session_cookie_name,
        settings.refresh_cookie_name,
        settings.csrf_cookie_name,
        settings.persona_cookie_name,
    )

    for name in cookie_names:
        response.delete_cookie(
            name,
            path="/",
        )

    return ApiMessage(
        message="Signed out successfully"
    )


@router.get("/me")
async def account(
    user: dict = Depends(current_user),
):
    base = user.get(
        "base_profile",
        {},
    )

    shared = bool(
        base.get("shared_staff_account")
    )

    return {
        "success": True,
        "user": user["profile"],
        "requires_persona": bool(
            shared
            and user["profile"]["id"]
            == base.get("id")
        ),
        "shared_staff_session": shared,
    }


@router.get("/staff-personas")
async def staff_personas(
    user: dict = Depends(current_user),
    settings: Settings = Depends(
        get_settings
    ),
):
    base = (
        user.get("base_profile")
        or user["profile"]
    )

    if (
        not settings
        .shared_staff_login_enabled
        or not base.get(
            "shared_staff_account"
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Shared staff selection "
                "is not enabled for this "
                "account"
            ),
        )

    rows = await SupabaseClient(
        settings
    ).query(
        "user_profiles",
        (
            "shared_staff_selectable=eq.true"
            "&active=eq.true"
            "&select=id,full_name,email,"
            "role,department,job_title"
            "&order=department,full_name"
        ),
    )

    return {
        "success": True,
        "items": rows,
    }


@router.post(
    "/staff-personas/select",
    response_model=ApiMessage,
)
async def select_staff_persona(
    payload: dict,
    response: Response,
    user: dict = Depends(current_user),
    settings: Settings = Depends(
        get_settings
    ),
):
    base = (
        user.get("base_profile")
        or user["profile"]
    )

    if (
        not settings
        .shared_staff_login_enabled
        or not base.get(
            "shared_staff_account"
        )
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Shared staff selection "
                "is not enabled for this "
                "account"
            ),
        )

    profile_id = str(
        payload.get("profile_id", "")
    )

    rows = await SupabaseClient(
        settings
    ).query(
        "user_profiles",
        (
            f"id=eq.{quote(profile_id)}"
            "&shared_staff_selectable=eq.true"
            "&active=eq.true"
            "&select=*"
        ),
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                "Staff profile was not found"
            ),
        )

    token = jwt.encode(
        {
            "base": base["id"],
            "profile": profile_id,
            "exp": int(
                (
                    datetime.now(
                        timezone.utc
                    )
                    + timedelta(
                        seconds=(
                            settings
                            .session_max_age_seconds
                        )
                    )
                ).timestamp()
            ),
        },
        settings.otp_pepper,
        algorithm="HS256",
    )

    response.set_cookie(
        settings.persona_cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=(
            settings
            .session_max_age_seconds
        ),
        path="/",
    )

    await SupabaseClient(
        settings
    ).insert(
        "audit_logs",
        {
            "actor_id": profile_id,
            "action": (
                "SHARED_STAFF_"
                "PERSONA_SELECTED"
            ),
            "entity_type": "USER",
            "entity_id": profile_id,
            "metadata": {
                "base_profile_id": (
                    base["id"]
                ),
            },
        },
    )

    return ApiMessage(
        message=(
            "Staff workspace selected"
        ),
        data=rows[0],
    )


@router.patch(
    "/me",
    response_model=ApiMessage,
)
async def update_account(
    payload: ProfileUpdate,
    user: dict = Depends(current_user),
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    username = (
        payload.username
        .strip()
        .lower()
    )

    duplicates = await db.query(
        "user_profiles",
        (
            "username=ilike."
            f"{quote(username)}"
            "&id=neq."
            f"{user['profile']['id']}"
            "&select=id"
        ),
    )

    if duplicates:
        raise HTTPException(
            status_code=409,
            detail=(
                "Username is already in use"
            ),
        )

    changes = payload.model_dump()
    changes["username"] = username

    rows = await db.update(
        "user_profiles",
        (
            f"id=eq."
            f"{user['profile']['id']}"
        ),
        changes,
    )

    await db.insert(
        "audit_logs",
        {
            "actor_id": (
                user["profile"]["id"]
            ),
            "action": "PROFILE_UPDATED",
            "entity_type": "USER",
            "entity_id": (
                user["profile"]["id"]
            ),
            "new_data": changes,
        },
    )

    return ApiMessage(
        message="Account settings updated",
        data=(
            rows[0]
            if rows
            else changes
        ),
    )


@router.post(
    "/me/avatar",
    response_model=ApiMessage,
)
async def upload_avatar(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
    settings: Settings = Depends(
        get_settings
    ),
):
    content_type = (
        file.content_type or ""
    ).lower()

    image = PROFILE_IMAGES.get(
        content_type
    )

    if (
        not image
        or not file.filename
        or not file.filename
        .lower()
        .endswith(image[0])
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Only JPG, PNG and WebP "
                "profile images are allowed"
            ),
        )

    content = await file.read(
        5 * 1024 * 1024 + 1
    )

    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                "Profile image must be "
                "5 MB or smaller"
            ),
        )

    if not content.startswith(image[1]):
        raise HTTPException(
            status_code=400,
            detail=(
                "The uploaded image content "
                "does not match its "
                "declared type"
            ),
        )

    db = SupabaseClient(settings)

    old_path = user["profile"].get(
        "avatar_storage_path"
    )

    auth_user_id = user[
        "profile"
    ].get("auth_user_id")

    if not auth_user_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Complete account setup "
                "before uploading a photo"
            ),
        )

    path = (
        f"{auth_user_id}/"
        f"{secrets.token_hex(16)}"
        f"{image[0]}"
    )

    await db.upload_object(
        "profile-images",
        path,
        content,
        content_type,
    )

    signed = await db.signed_object_url(
        "profile-images",
        path,
        86400,
    )

    await db.update(
        "user_profiles",
        (
            f"id=eq."
            f"{user['profile']['id']}"
        ),
        {
            "avatar_url": signed,
            "avatar_storage_path": path,
        },
    )

    if old_path:
        try:
            await db.delete_object(
                "profile-images",
                old_path,
            )
        except HTTPException:
            pass

    await db.insert(
        "audit_logs",
        {
            "actor_id": (
                user["profile"]["id"]
            ),
            "action": (
                "PROFILE_IMAGE_UPDATED"
            ),
            "entity_type": "USER",
            "entity_id": (
                user["profile"]["id"]
            ),
            "new_data": {
                "mime_type": content_type,
                "size_bytes": len(content),
            },
        },
    )

    return ApiMessage(
        message="Profile photo updated",
        data={
            "avatar_url": signed,
        },
    )


@router.post(
    "/password/change",
    response_model=ApiMessage,
)
async def change_password(
    payload: PasswordChange,
    user: dict = Depends(current_user),
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    await db.update_own_password(
        user["access_token"],
        payload.password,
    )

    await db.update(
        "user_profiles",
        (
            f"id=eq."
            f"{user['profile']['id']}"
        ),
        {
            "must_change_password": False,
        },
    )

    await db.insert(
        "audit_logs",
        {
            "actor_id": (
                user["profile"]["id"]
            ),
            "action": "PASSWORD_CHANGED",
            "entity_type": "USER",
            "entity_id": (
                user["profile"]["id"]
            ),
        },
    )

    return ApiMessage(
        message="Password changed successfully"
    )


@router.post(
    "/otp/request",
    response_model=ApiMessage,
)
async def request_otp(
    payload: OtpRequest,
    request: Request,
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    profile = await resolve_profile(
        payload.identifier,
        db,
    )

    generic = (
        "If an eligible account exists, "
        "a verification code has been sent."
    )

    if not profile:
        return ApiMessage(
            message=generic
        )

    if (
        payload.purpose
        == "CANDIDATE_REGISTRATION"
        and profile.get("role")
        not in {"candidate", "employee"}
    ):
        return ApiMessage(
            message=generic
        )

    email = profile["email"].lower()

    recent_since = (
        datetime.now(timezone.utc)
        - timedelta(seconds=60)
    ).isoformat()

    recent = await db.query(
        "otp_challenges",
        (
            f"email=eq.{quote(email)}"
            "&purpose=eq."
            f"{payload.purpose}"
            "&created_at=gte."
            f"{quote(recent_since)}"
            "&select=id"
        ),
    )

    if recent:
        return ApiMessage(
            message=generic
        )

    otp = generate_otp()

    await db.insert(
        "otp_challenges",
        {
            "email": email,
            "purpose": payload.purpose,
            "otp_hash": otp_hash(
                email,
                payload.purpose,
                otp,
                settings.otp_pepper,
            ),
            "expires_at": (
                datetime.now(
                    timezone.utc
                )
                + timedelta(
                    minutes=(
                        settings
                        .otp_expiry_minutes
                    )
                )
            ).isoformat(),
            "requested_ip": (
                request.client.host
                if request.client
                else None
            ),
        },
    )

    await EmailService(
        settings
    ).send_otp(
        email,
        otp,
        payload.purpose,
    )

    data = (
        {"test_otp": otp}
        if (
            settings.app_env
            != "production"
            and settings.expose_test_otp
        )
        else None
    )

    return ApiMessage(
        message=generic,
        data=data,
    )


@router.post(
    "/otp/verify",
    response_model=ApiMessage,
)
async def verify_otp(
    payload: OtpVerify,
    settings: Settings = Depends(
        get_settings
    ),
):
    db = SupabaseClient(settings)

    profile = await resolve_profile(
        payload.identifier,
        db,
    )

    if not profile:
        raise HTTPException(
            status_code=400,
            detail=(
                "Verification code is "
                "invalid or expired"
            ),
        )

    email = profile["email"].lower()

    rows = await db.query(
        "otp_challenges",
        (
            f"email=eq.{quote(email)}"
            "&purpose=eq."
            f"{payload.purpose}"
            "&used_at=is.null"
            "&order=created_at.desc"
            "&limit=1"
            "&select=*"
        ),
    )

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "Verification code is "
                "invalid or expired"
            ),
        )

    challenge = rows[0]

    expires_at = datetime.fromisoformat(
        challenge["expires_at"].replace(
            "Z",
            "+00:00",
        )
    )

    expired = (
        expires_at
        <= datetime.now(timezone.utc)
    )

    valid = safe_compare(
        challenge["otp_hash"],
        otp_hash(
            email,
            payload.purpose,
            payload.otp,
            settings.otp_pepper,
        ),
    )

    if (
        expired
        or challenge["attempts"]
        >= challenge["max_attempts"]
        or not valid
    ):
        await db.update(
            "otp_challenges",
            f"id=eq.{challenge['id']}",
            {
                "attempts": (
                    challenge["attempts"]
                    + 1
                ),
            },
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "Verification code is "
                "invalid or expired"
            ),
        )

    await db.update(
        "otp_challenges",
        f"id=eq.{challenge['id']}",
        {
            "used_at": datetime.now(
                timezone.utc
            ).isoformat(),
        },
    )

    token = make_verification_token(
        email,
        payload.purpose,
        settings,
    )

    return ApiMessage(
        message="Verification successful",
        data={
            "verification_token": token,
        },
    )


@router.post(
    "/password/complete",
    response_model=ApiMessage,
)
async def complete_password(
    payload: PasswordComplete,
    purpose: str,
    settings: Settings = Depends(
        get_settings
    ),
):
    if purpose not in {
        "PASSWORD_RESET",
        "CANDIDATE_REGISTRATION",
    }:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported verification "
                "purpose"
            ),
        )

    email = read_verification_token(
        payload.verification_token,
        settings,
        purpose,
    )

    db = SupabaseClient(settings)

    profiles = await db.query(
        "user_profiles",
        (
            f"email=eq.{quote(email)}"
            "&select=*"
        ),
    )

    if not profiles:
        raise HTTPException(
            status_code=404,
            detail="Account was not found",
        )

    profile = profiles[0]

    if payload.username:
        username = (
            payload.username
            .strip()
            .lower()
        )

        duplicate = await db.query(
            "user_profiles",
            (
                "username=ilike."
                f"{quote(username)}"
                "&id=neq."
                f"{profile['id']}"
                "&select=id"
            ),
        )

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Username is already "
                    "in use"
                ),
            )
    else:
        username = None

    auth_user_id = profile.get(
        "auth_user_id"
    )

    if not auth_user_id:
        existing_auth_user = (
            await db.find_auth_user_by_email(
                email
            )
        )

        if existing_auth_user:
            auth_user_id = (
                existing_auth_user["id"]
            )

            await db.update_user_password(
                auth_user_id,
                payload.password,
            )
        else:
            created = await db.create_user(
                email,
                payload.password,
                {
                    "full_name": (
                        profile["full_name"]
                    ),
                    "role": profile["role"],
                },
            )

            auth_user_id = created["id"]
    else:
        await db.update_user_password(
            auth_user_id,
            payload.password,
        )

    update = {
        "auth_user_id": auth_user_id,
        "must_change_password": False,
    }

    if username:
        update["username"] = username

    await db.update(
        "user_profiles",
        f"id=eq.{profile['id']}",
        update,
    )

    role_rows = await db.query(
        "user_roles",
        (
            "user_profile_id=eq."
            f"{profile['id']}"
            "&role=eq."
            f"{profile['role']}"
            "&select=user_profile_id"
        ),
    )

    if not role_rows:
        await db.insert(
            "user_roles",
            {
                "user_profile_id": (
                    profile["id"]
                ),
                "role": profile["role"],
            },
        )

    await db.insert(
        "audit_logs",
        {
            "actor_id": profile["id"],
            "action": (
                "ACCOUNT_CREDENTIALS_COMPLETED"
            ),
            "entity_type": "USER",
            "entity_id": profile["id"],
            "new_data": {
                "purpose": purpose,
                "role": profile["role"],
                "auth_user_id": auth_user_id,
            },
        },
    )

    return ApiMessage(
        message=(
            "Your account credentials have "
            "been updated successfully."
        )
    )