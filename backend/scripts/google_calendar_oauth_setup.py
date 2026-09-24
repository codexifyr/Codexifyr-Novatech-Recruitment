"""Create the Google Calendar offline refresh token used for Meet scheduling.

Before running, add http://localhost:8765/callback to the OAuth client's
authorized redirect URIs and set GOOGLE_CALENDAR_CLIENT_ID/CLIENT_SECRET.
The script does not edit .env or store the returned token.
"""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import httpx
from app.config import get_settings

REDIRECT_URI = "http://localhost:8765/callback"
SCOPE = "https://www.googleapis.com/auth/calendar.events"


class CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None
    expected_state: str = ""

    def do_GET(self):  # noqa: N802
        values = parse_qs(urlparse(self.path).query)
        if values.get("state", [""])[0] != self.expected_state:
            type(self).error = "OAuth state did not match"
        elif values.get("error"):
            type(self).error = values["error"][0]
        else:
            type(self).code = values.get("code", [None])[0]
        body = b"Authorization received. You can close this tab and return to PowerShell."
        self.send_response(200 if type(self).code else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


async def main() -> None:
    settings = get_settings()
    if not settings.google_calendar_client_id or not settings.google_calendar_client_secret:
        raise SystemExit("Set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET in .env first.")
    state = secrets.token_urlsafe(24)
    CallbackHandler.expected_state = state
    server = HTTPServer(("127.0.0.1", 8765), CallbackHandler)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": settings.google_calendar_client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    print("Opening Google authorization in your browser...")
    print(auth_url)
    webbrowser.open(auth_url)
    thread.join(timeout=300)
    server.server_close()
    if CallbackHandler.error or not CallbackHandler.code:
        raise SystemExit(CallbackHandler.error or "Authorization timed out or no code was returned.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "code": CallbackHandler.code,
            "client_id": settings.google_calendar_client_id,
            "client_secret": settings.google_calendar_client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        })
    response.raise_for_status()
    refresh_token = response.json().get("refresh_token")
    if not refresh_token:
        raise SystemExit("Google did not return a refresh token. Revoke the app grant and run again with consent.")
    print("\nCopy this value into GOOGLE_CALENDAR_REFRESH_TOKEN in .env, then close this terminal:\n")
    print(refresh_token)


if __name__ == "__main__":
    asyncio.run(main())
