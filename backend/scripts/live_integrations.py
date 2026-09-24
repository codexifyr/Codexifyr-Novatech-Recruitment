"""Optional non-destructive live integration checks.

Usage:
  python scripts/live_integrations.py
  python scripts/live_integrations.py --network

The script reports configuration/status only and never prints credentials or response bodies.
"""
import argparse
import asyncio
import copy
import smtplib
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.config import get_settings
from app.services.ai import AIReviewClient
from app.services.n8n import N8nClient


async def check_supabase(settings) -> str:
    if not settings.supabase_ready:
        return "SKIPPED (not configured)"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{settings.supabase_url}/rest/v1/user_profiles?select=id&limit=1", headers={"apikey": settings.supabase_secret_key, "Authorization": f"Bearer {settings.supabase_secret_key}"})
        return f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        return f"ERROR ({type(exc).__name__})"


async def check_ai(settings) -> list[str]:
    results = []
    if not settings.gemini_api_key:
        results.append("gemini=SKIPPED (GEMINI_API_KEY not configured)")
    else:
        try:
            result = await AIReviewClient(settings).review("LIVE_SMOKE_TEST: return exactly the word PASS")
            results.append("gemini_primary=PASS" if result.get("provider") == "gemini" else f"gemini_primary=FAILED (provider={result.get('provider', 'unknown')})")
        except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
            results.append(f"gemini_primary=ERROR ({type(exc).__name__})")
    if not settings.groq_api_key:
        results.append("groq=SKIPPED (GROQ_API_KEY not configured)")
    elif settings.gemini_api_key:
        fallback_settings = copy.copy(settings)
        fallback_settings.gemini_model = "__live_smoke_invalid_model__"
        try:
            result = await AIReviewClient(fallback_settings).review("LIVE_SMOKE_TEST_FALLBACK: return exactly the word FALLBACK")
            results.append(f"gemini_failure_groq_fallback={result.get('provider') == 'groq'}")
        except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as exc:
            results.append(f"gemini_failure_groq_fallback=ERROR ({type(exc).__name__})")
    else:
        results.append("gemini_failure_groq_fallback=SKIPPED (Gemini not configured)")
    return results


async def check_n8n(settings) -> str:
    if not settings.n8n_webhook_base_url or not settings.n8n_webhook_secret:
        return "SKIPPED (WEBHOOK_BASE_URL or n8n_webhook_secret not configured)"
    correlation_id = f"LIVE-SMOKE-{uuid.uuid4().hex[:12]}"
    try:
        result = await N8nClient(settings).trigger("webhook/novatech/monitoring", {"smoke_test": True, "correlation_id": correlation_id, "test_record": "LIVE_SMOKE_TEST"})
        return f"PASS keys={','.join(sorted(str(key) for key in result.keys())[:8])}"
    except Exception as exc:
        return f"ERROR ({type(exc).__name__})"


def check_smtp(settings) -> str:
    if not settings.email_enabled or not settings.smtp_user:
        return "SKIPPED (not configured)"
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
        return "AUTHENTICATED"
    except (OSError, smtplib.SMTPException) as exc:
        return f"ERROR ({type(exc).__name__})"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true", help="Run non-destructive Supabase and SMTP checks")
    parser.add_argument("--live-ai", action="store_true", help="Run marked Gemini/Groq smoke calls")
    parser.add_argument("--live-n8n", action="store_true", help="Run a marked signed n8n smoke webhook")
    args = parser.parse_args()
    settings = get_settings()
    print(f"environment={settings.app_env}")
    print(f"supabase_configured={settings.supabase_ready}")
    print(f"smtp_configured={settings.email_enabled and bool(settings.smtp_user)}")
    print(f"gemini_configured={bool(settings.gemini_api_key)}")
    print(f"groq_configured={bool(settings.groq_api_key)}")
    print(f"n8n_configured={bool(settings.n8n_webhook_base_url)}")
    if args.network:
        print(f"supabase_check={await check_supabase(settings)}")
        print(f"smtp_check={check_smtp(settings)}")
    else:
        print("network_checks=SKIPPED (use --network to run)")
    if args.live_ai:
        for result in await check_ai(settings):
            print(result)
    else:
        print("ai_live_checks=SKIPPED (use --live-ai to run)")
    if args.live_n8n:
        print(f"n8n_live_check={await check_n8n(settings)}")
    else:
        print("n8n_live_check=SKIPPED (use --live-n8n to run)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
