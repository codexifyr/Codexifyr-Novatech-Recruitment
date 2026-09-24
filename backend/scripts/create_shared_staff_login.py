"""Create/update the optional shared demo login. Run after migration 020."""
import asyncio
from app.config import get_settings
from app.services.supabase import SupabaseClient

USERNAME = "staff"
EMAIL = "shared.staff@novatech.local"
PASSWORD = "Staff@234"


async def main():
    settings = get_settings()
    db = SupabaseClient(settings)
    profiles = await db.query("user_profiles", f"username=eq.{USERNAME}&select=*")
    if profiles:
        profile = profiles[0]
        if profile.get("auth_user_id"):
            await db.update_user_password(profile["auth_user_id"], PASSWORD)
            await db.update("user_profiles", f"id=eq.{profile['id']}", {"active": True, "shared_staff_account": True})
        else:
            auth = await db.create_user(EMAIL, PASSWORD, {"full_name": "Shared Staff Login", "role": "operator"})
            await db.update("user_profiles", f"id=eq.{profile['id']}", {"auth_user_id": auth["id"], "active": True, "shared_staff_account": True})
    else:
        auth = await db.create_user(EMAIL, PASSWORD, {"full_name": "Shared Staff Login", "role": "operator"})
        profile = (await db.insert("user_profiles", {"auth_user_id": auth["id"], "full_name": "Shared Staff Login", "email": EMAIL, "username": USERNAME, "role": "operator", "department": "Operations", "job_title": "Shared demonstration access", "active": True, "shared_staff_account": True}))[0]
        await db.insert("user_roles", {"user_profile_id": profile["id"], "role": "operator"})
    print("Shared staff login is ready. Enable SHARED_STAFF_LOGIN_ENABLED=true in .env to use it.")


if __name__ == "__main__":
    asyncio.run(main())
