import hashlib
import hmac
import secrets
import time
import asyncio
import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from app.config import Settings, get_settings
from app.services.supabase import SupabaseClient


def csrf_is_valid(request: Request, settings: Settings) -> bool:
    cookie = request.cookies.get(settings.csrf_cookie_name)
    return bool(cookie and request.headers.get("X-CSRF-Token") == cookie)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_hash(email: str, purpose: str, otp: str, pepper: str) -> str:
    value = f"{email.lower()}:{purpose}:{otp}:{pepper}".encode()
    return hashlib.sha256(value).hexdigest()


def safe_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def make_verification_token(email: str, purpose: str, settings: Settings) -> str:
    return jwt.encode(
        {"sub": email.lower(), "purpose": purpose, "exp": int(time.time()) + 600},
        settings.otp_pepper,
        algorithm="HS256",
    )


def read_verification_token(token: str, settings: Settings, purpose: str) -> str:
    try:
        payload = jwt.decode(token, settings.otp_pepper, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Verification token is invalid or expired") from exc
    if payload.get("purpose") != purpose:
        raise HTTPException(status_code=400, detail="Verification token purpose is invalid")
    return str(payload["sub"])


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias="novatech_session"),
    settings: Settings = Depends(get_settings),
) -> dict:
    token = session_cookie
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    client = SupabaseClient(settings)
    user = await client.auth_user(token)
    profiles = await client.query("user_profiles", f"auth_user_id=eq.{user['id']}&select=*", token=token)
    if not profiles or not profiles[0].get("active"):
        raise HTTPException(status_code=403, detail="Account is not active")
    profile = profiles[0]
    base_profile = profile
    persona_token = request.cookies.get(settings.persona_cookie_name)
    if settings.shared_staff_login_enabled and profile.get("shared_staff_account") and persona_token:
        try:
            persona = jwt.decode(persona_token, settings.otp_pepper, algorithms=["HS256"])
            if persona.get("base") != profile["id"]:
                raise jwt.InvalidTokenError()
            selected = await client.query("user_profiles", f"id=eq.{persona.get('profile')}&shared_staff_selectable=eq.true&active=eq.true&select=*")
            if selected:
                profile = selected[0]
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Staff persona session is invalid; select a staff profile again")
    profile_token = None if profile["id"] != base_profile["id"] else token
    roles_task = client.query("user_roles", f"user_profile_id=eq.{profile['id']}&select=role", token=profile_token)
    overrides_task = client.query("user_permission_overrides", f"user_profile_id=eq.{profile['id']}&select=permission_key,allowed", token=profile_token)
    avatar_task = client.signed_object_url("profile-images", profile["avatar_storage_path"], 86400) if profile.get("avatar_storage_path") else None
    roles, overrides = await asyncio.gather(roles_task, overrides_task)
    if avatar_task:
        profile["avatar_url"] = await avatar_task
    role_names = {item["role"] for item in roles} | {profile.get("role")}
    permission_rows = await client.query("role_permissions", f"role=in.({','.join(sorted(role_names))})&select=permission_key", token=token)
    permissions = {item["permission_key"] for item in permission_rows}
    permissions.update(item["permission_key"] for item in overrides if item.get("allowed"))
    permissions.difference_update(item["permission_key"] for item in overrides if not item.get("allowed"))
    return {**user, "profile": profile, "base_profile": base_profile, "access_token": token, "roles": role_names, "permissions": permissions}


def require_roles(*roles: str):
    async def dependency(user: dict = Depends(current_user)) -> dict:
        if not set(roles).intersection(user.get("roles", {user["profile"].get("role")})):
            raise HTTPException(status_code=403, detail="You do not have permission for this action")
        return user
    return dependency


def require_permissions(*permissions: str):
    async def dependency(user: dict = Depends(current_user)) -> dict:
        if not set(permissions).issubset(user.get("permissions", set())):
            raise HTTPException(status_code=403, detail="You do not have permission for this action")
        return user

    return dependency
