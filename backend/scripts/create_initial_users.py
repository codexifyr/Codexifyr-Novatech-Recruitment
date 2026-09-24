"""Create initial staff accounts from environment variables.

Run only from a trusted machine after Supabase variables are configured.
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env", override=True)
from app.config import get_settings
from app.services.supabase import SupabaseClient

ACCOUNTS = (
    ("ADMIN", "admin"),
    ("HR", "hr"),
    ("RECRUITER", "recruiter"),
    ("INTERVIEWER", "interviewer"),
)


async def main() -> None:
    db = SupabaseClient(get_settings())
    for prefix, role in ACCOUNTS:
        email = os.getenv(f"INITIAL_{prefix}_EMAIL", "").strip().lower()
        password = os.getenv(f"INITIAL_{prefix}_PASSWORD", "")
        username = os.getenv(f"INITIAL_{prefix}_USERNAME", "").strip().lower()
        full_name = os.getenv(f"INITIAL_{prefix}_NAME", prefix.title())
        if not email or not password or not username:
            print(f"Skipping {role}: variables are incomplete")
            continue
        existing = await db.query("user_profiles", f"email=eq.{email}&select=id")
        if existing:
            print(f"Skipping {role}: profile already exists")
            continue
        user = await db.create_user(email, password, {"full_name": full_name, "role": role})
        await db.insert("user_profiles", {
            "auth_user_id": user["id"], "full_name": full_name, "email": email,
            "username": username, "role": role, "active": True, "must_change_password": True,
        })
        print(f"Created {role}: {username} ({email})")


if __name__ == "__main__":
    asyncio.run(main())

