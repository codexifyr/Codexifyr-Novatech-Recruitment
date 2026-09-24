import hashlib
import hmac
import json
import time
import httpx
from fastapi import HTTPException
from app.config import Settings


class N8nClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def trigger(self, path: str, payload: dict) -> dict:
        if not self.settings.n8n_webhook_base_url:
            raise HTTPException(status_code=503, detail="Workflow service is not configured")
        body = json.dumps(payload, separators=(",", ":"), default=str).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.settings.n8n_webhook_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest() if self.settings.n8n_webhook_secret else ""
        headers = {"Content-Type": "application/json", "X-Webhook-Timestamp": timestamp}
        if signature:
            headers["X-Webhook-Signature"] = signature
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.settings.n8n_webhook_base_url.rstrip('/')}/{path.lstrip('/')}",
                content=body,
                headers=headers,
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Recruitment workflow could not process the request")
        try:
            return response.json()
        except ValueError:
            return {"success": True, "message": "Request submitted"}

